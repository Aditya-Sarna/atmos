"""Per-screen, context-aware test-case generation + execution with video.

For every screen discovered by ``flow_explorer``, we:

1. Read the screen's purpose (LLM, with a deterministic fallback) and its input
   fields.
2. Generate an *elaborate*, screen-specific battery of test cases — boundary,
   malformed and adversarial inputs tailored to each field (e.g. a name field:
   empty, 1000 chars, numerics, ``@#$``, emoji, RTL unicode, SQL/XSS; a PIN:
   too short, too long, non-numeric, mismatch).
3. Replay the screen's recorded action path in a *fresh, video-recording*
   browser context, perform the single test input, observe the app's reaction,
   grade it, and save a ``.webm`` clip — one video **per test case**.

Public entry-point
-------------------
    results = await generate_and_run_screen_tests(
        browser, screens, run_id, project, on_progress=...)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import Browser, Page

from atmos_engine import (
    SCREENSHOTS_DIR,
    VIEWPORTS,
    NAV_TIMEOUT_MS,
    _new_context,
    _settle,
    _safe_name,
    _parse_llm_json,
)
from fuzz_generator import _classify_field, _detect_validation_outcome, _grade
from flow_explorer import replay_path, _fill_field

logger = logging.getLogger("atmos.screentests")

MAX_FIELDS_PER_SCREEN = 4
MAX_CASES_PER_SCREEN = int(os.environ.get("ATMOS_MAX_CASES_PER_SCREEN", "6"))
MAX_TOTAL_CASES = int(os.environ.get("ATMOS_MAX_TOTAL_CASES", "48"))
CASE_TIMEOUT_SECS = int(os.environ.get("ATMOS_CASE_TIMEOUT_SECS", "40"))

SUBMIT_CTAS = ["continue", "next", "submit", "confirm", "save", "done",
               "verify", "create", "send", "pay", "sign in", "log in", "go"]


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


async def _llm_screen_brief(project: dict[str, Any], screen: dict[str, Any], db=None) -> dict[str, Any]:
    """Ask the user's IDE model for the screen's purpose + extra context-specific cases."""
    if db is None:
        return {}

    field_lines = []
    for f in screen.get("fields", [])[:MAX_FIELDS_PER_SCREEN]:
        field_lines.append(
            f"- label='{f.get('label_text') or f.get('name') or f.get('type')}' "
            f"type={f.get('type')} maxlength={f.get('maxlength')} required={f.get('required')}"
        )
    prompt = (
        f"Product: {project.get('name')} (type: {project.get('app_type', 'generic')})\n"
        f"Screen name: {screen.get('name')}\n"
        f"Route: {screen.get('route')}\n"
        f"Heading: {screen.get('heading')}\n"
        f"Visible text: {screen.get('body_snippet', '')[:240]}\n"
        f"Input fields:\n" + ("\n".join(field_lines) or "(none)") + "\n\n"
        "You are Atmos, a senior QA engineer. Return ONLY minified JSON:\n"
        '{"purpose":"1 sentence — what this screen is for and who uses it",'
        '"cases":[{"field":"<exact field label above or \\"-\\">",'
        '"name":"short case title","value":"the literal input to type",'
        '"expectation":"reject"|"accept_silently"|"accept_but_warn",'
        '"rationale":"why this case matters for THIS screen"}]}\n'
        "Generate 4-6 ELABORATE, screen-specific cases that go beyond generic "
        "boundary checks — reflect this screen's real purpose. JSON only."
    )
    try:
        from user_llm_proxy import user_llm_json
        data = await user_llm_json(
            db,
            project.get("user_id") or "user_local_dev",
            prompt,
            system="You are Atmos, a meticulous QA engineer. Output JSON only.",
            purpose="screen_brief",
        )
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("screen brief LLM failed for %s: %s", screen.get("name"), exc)
        return {}


def _deterministic_cases(screen: dict[str, Any]) -> list[dict[str, Any]]:
    """Boundary/adversarial battery per field, derived from the field archetype."""
    cases: list[dict[str, Any]] = []
    for f in screen.get("fields", [])[:MAX_FIELDS_PER_SCREEN]:
        archetype, raw_cases = _classify_field(f)
        label = f.get("label_text") or f.get("name") or f.get("placeholder") or archetype
        for case_label, value, expectation in raw_cases:
            cases.append({
                "field": label,
                "selector": f.get("selector"),
                "name": f"{archetype} · {label} → {case_label}",
                "value": value,
                "expectation": expectation,
                "rationale": f"{archetype} boundary case: {case_label}",
                "source": "deterministic",
            })
    return cases


def _match_selector(screen: dict[str, Any], field_label: str) -> Optional[str]:
    fl = (field_label or "").strip().lower()
    for f in screen.get("fields", []):
        cand = (f.get("label_text") or f.get("name") or f.get("placeholder") or "").strip().lower()
        if cand and (cand == fl or fl in cand or cand in fl):
            return f.get("selector")
    fields = screen.get("fields", [])
    return fields[0].get("selector") if fields else None


def _merge_cases(screen: dict[str, Any], brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Interleave LLM cases (context-specific) with the deterministic battery."""
    llm_cases: list[dict[str, Any]] = []
    for c in (brief.get("cases") or []):
        sel = _match_selector(screen, c.get("field", ""))
        if not sel:
