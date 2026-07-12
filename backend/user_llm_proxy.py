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
            parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for b64 in images_b64[:3]:
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            user_content = parts
        else:
            user_content = prompt
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()

    if config.get("provider") == "anthropic":
        parts = data.get("content") or []
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text")

    choices = data.get("choices") or []
    if choices:
        return choices[0].get("message", {}).get("content") or ""
    return ""


async def _call_emergent_text(
    prompt: str,
    system: str,
    session_id: str,
    images_b64: Optional[list[str]] = None,
) -> str:
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        return "{}" if images_b64 is None else "{}"
    try:
        from emergentintegrations.llm.chat import (  # type: ignore
            LlmChat, UserMessage, ImageContent, TextDelta, StreamDone,
        )
    except Exception:  # noqa: BLE001
        return "{}"

    chat = LlmChat(api_key=api_key, session_id=session_id, system_message=system).with_model(
        "anthropic", "claude-sonnet-4-5-20250929"
    )
    files = [ImageContent(image_base64=b) for b in (images_b64 or [])[:5]]
    text = ""
    msg = UserMessage(text=prompt, file_contents=files) if files else UserMessage(text=prompt)
    async for ev in chat.stream_message(msg):
        if isinstance(ev, TextDelta):
            text += ev.content
        elif isinstance(ev, StreamDone):
            break
    return text.strip()


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract outermost object
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {"raw": text}
