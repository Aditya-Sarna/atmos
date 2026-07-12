"""IDE-native LLM bridge — run Atmos prompts on the user's IDE model quota.

Flow:
  1. Backend enqueues a job when an LLM call is needed
  2. Atmos VS Code / Cursor extension heartbeats + polls pending jobs
  3. Extension runs the prompt via vscode.lm (Copilot / IDE models) — no pasted API key
  4. Extension posts the result; backend awaiters resume

This is the preferred path so Atmos never bills the operator's LLM key.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("atmos.ide_llm")

AGENT_TTL_SEC = 20
DEFAULT_JOB_TIMEOUT_SEC = 180


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def register_agent(
    db,
    user_id: str,
    *,
    ide: str = "vscode",
    models: Optional[list[str]] = None,
    supports_vision: bool = False,
    extension_version: str = "0.0.0",
    preferred_model: Optional[str] = None,
    preferred_vision_model: Optional[str] = None,
) -> dict[str, Any]:
    doc = {
        "user_id": user_id,
        "ide": ide,
        "models": models or [],
        "supports_vision": supports_vision,
        "extension_version": extension_version,
        "preferred_model": preferred_model,
        "preferred_vision_model": preferred_vision_model,
        "last_seen": _utcnow().isoformat(),
        "online": True,
    }
    await db.ide_llm_agents.update_one({"user_id": user_id}, {"$set": doc}, upsert=True)
    return doc


async def agent_is_online(db, user_id: str) -> bool:
    doc = await db.ide_llm_agents.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        return False
    try:
        last = datetime.fromisoformat(doc["last_seen"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return False
    return (_utcnow() - last) <= timedelta(seconds=AGENT_TTL_SEC)


async def get_agent(db, user_id: str) -> Optional[dict[str, Any]]:
    if not await agent_is_online(db, user_id):
        return None
    return await db.ide_llm_agents.find_one({"user_id": user_id}, {"_id": 0})


async def enqueue_job(
    db,
    user_id: str,
    *,
    system: str,
    prompt: str,
    images_b64: Optional[list[str]] = None,
    expect_json: bool = False,
    model_hint: Optional[str] = None,
    purpose: str = "general",
) -> str:
    job_id = f"llmjob_{uuid.uuid4().hex[:16]}"
    # Cap image payload — keep first 3 screenshots, truncated markers only in job meta
    images = (images_b64 or [])[:3]
    await db.ide_llm_jobs.insert_one({
        "job_id": job_id,
        "user_id": user_id,
        "status": "pending",
        "system": system,
        "prompt": prompt,
        "images_b64": images,
        "expect_json": expect_json,
        "model_hint": model_hint,
        "purpose": purpose,
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
        "result_text": None,
        "error": None,
        "model_used": None,
    })
    return job_id


async def claim_pending_jobs(db, user_id: str, limit: int = 2) -> list[dict[str, Any]]:
    """Atomically claim pending jobs for this user's IDE agent."""
    out: list[dict[str, Any]] = []
    for _ in range(limit):
        doc = await db.ide_llm_jobs.find_one_and_update(
            {"user_id": user_id, "status": "pending"},
            {"$set": {"status": "running", "updated_at": _utcnow().isoformat()}},
