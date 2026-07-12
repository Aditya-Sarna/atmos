"""Route LLM calls through the user's IDE model quota (preferred) — no Atmos API key.

Priority:
  1) Atmos IDE extension + vscode.lm / Copilot / Cursor-listed models (no pasted key)
  2) Optional user-configured OpenAI-compatible endpoint (legacy / advanced)
  3) Emergent fallback only if ATMOS_ALLOW_EMERGENT_FALLBACK=1
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("atmos.user_llm")

DEFAULT_SYSTEM = "You are Atmos, an autonomous UX testing agent. Respond with valid JSON when asked."
ALLOW_EMERGENT = os.environ.get("ATMOS_ALLOW_EMERGENT_FALLBACK", "0").strip().lower() in {
    "1", "true", "yes",
}


async def get_user_llm_config(db, user_id: str) -> Optional[dict[str, Any]]:
    doc = await db.user_llm_configs.find_one({"user_id": user_id, "enabled": True}, {"_id": 0})
    if doc and (doc.get("base_url") or doc.get("mode") == "ide_native"):
        return doc
    base = os.environ.get("ATMOS_USER_LLM_BASE_URL", "").strip()
    if base:
        return {
            "provider": os.environ.get("ATMOS_USER_LLM_PROVIDER", "openai_compatible"),
            "base_url": base.rstrip("/"),
            "api_key": os.environ.get("ATMOS_USER_LLM_API_KEY", ""),
            "model": os.environ.get("ATMOS_USER_LLM_MODEL", "gpt-4o"),
            "enabled": True,
            "mode": "http",
        }
    return None


async def user_llm_json(
    db,
    user_id: str,
    prompt: str,
    *,
    system: str = DEFAULT_SYSTEM,
    session_id: str = "atmos",
    images_b64: Optional[list[str]] = None,
    purpose: str = "json",
) -> dict[str, Any]:
    text = await user_llm_text(
        db, user_id, prompt,
        system=system,
        session_id=session_id,
        images_b64=images_b64,
        purpose=purpose,
        expect_json=True,
    )
    return _parse_json(text)


async def user_llm_text(
    db,
    user_id: str,
    prompt: str,
    *,
    system: str = DEFAULT_SYSTEM,
    session_id: str = "atmos",
    images_b64: Optional[list[str]] = None,
    purpose: str = "text",
    expect_json: bool = False,
) -> str:
    """Prefer IDE-native quota; never require the user to paste a key."""
    # 1) IDE bridge
    try:
        from ide_llm_bridge import run_via_ide
        return await run_via_ide(
            db, user_id,
            system=system,
            prompt=prompt,
            images_b64=images_b64,
            expect_json=expect_json,
            purpose=purpose,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("IDE LLM bridge unavailable (%s); trying HTTP config", exc)

    # 2) Optional HTTP endpoint (power users / CI) — still user's key, not Atmos
    config = await get_user_llm_config(db, user_id)
    if config and config.get("base_url") and config.get("mode") != "ide_native":
        try:
            return await _call_openai_compatible(config, system, prompt, images_b64=images_b64)
        except Exception as exc:  # noqa: BLE001
            logger.warning("user HTTP LLM failed: %s", exc)

    # 3) Optional Emergent (operator-funded) — off by default
    if ALLOW_EMERGENT:
        return await _call_emergent_text(prompt, system, session_id, images_b64=images_b64)

    raise RuntimeError(
        "No user LLM available. Install the Atmos extension in Cursor/VS Code and keep it open "
        "so runs use your IDE model quota (Copilot / Cursor models). No API key paste required."
    )


async def user_llm_vision_json(
    db,
    user_id: str,
    prompt: str,
    images_b64: list[str],
    *,
    system: str = DEFAULT_SYSTEM,
    purpose: str = "vision",
) -> dict[str, Any]:
    return await user_llm_json(
        db, user_id, prompt,
        system=system,
        images_b64=images_b64,
        purpose=purpose,
    )


async def _call_openai_compatible(
    config: dict[str, Any],
    system: str,
    prompt: str,
    *,
    images_b64: Optional[list[str]] = None,
) -> str:
    base = config["base_url"].rstrip("/")
    model = config.get("model") or "gpt-4o"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = config.get("api_key") or ""
    if key:
        headers["Authorization"] = f"Bearer {key}"

    if config.get("provider") == "anthropic":
        url = f"{base}/v1/messages"
        content: list[dict[str, Any]] = []
        for b64 in (images_b64 or [])[:3]:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })
        content.append({"type": "text", "text": prompt})
        body = {
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        headers["anthropic-version"] = "2023-06-01"
        headers["x-api-key"] = key
        headers.pop("Authorization", None)
    else:
        url = f"{base}/v1/chat/completions"
        user_content: Any
        if images_b64:
