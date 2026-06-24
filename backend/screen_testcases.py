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


async def _llm_screen_brief(project: dict[str, Any], screen: dict[str, Any]) -> dict[str, Any]:
    """Ask the model for the screen's purpose + extra context-specific cases.
    Falls back to {} on any failure."""
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        return {}
    try:
        from emergentintegrations.llm.chat import (  # type: ignore
            LlmChat, UserMessage, TextDelta, StreamDone,
        )
    except Exception:  # noqa: BLE001
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
    chat = LlmChat(
        api_key=api_key,
        session_id=f"atmos_screen_{uuid.uuid4().hex[:8]}",
        system_message="You are Atmos, a meticulous QA engineer. Output JSON only.",
    ).with_model("gemini", "gemini-3.5-flash")
    try:
        text = ""
        async for ev in chat.stream_message(UserMessage(text=prompt)):
            if isinstance(ev, TextDelta):
                text += ev.content
            elif isinstance(ev, StreamDone):
                break
        return _parse_llm_json(text)
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
            continue
        llm_cases.append({
            "field": c.get("field") or "",
            "selector": sel,
            "name": c.get("name") or "Context case",
            "value": str(c.get("value", "")),
            "expectation": c.get("expectation", "accept_but_warn"),
            "rationale": c.get("rationale", ""),
            "source": "llm",
        })
    det = _deterministic_cases(screen)
    merged: list[dict[str, Any]] = []
    i = j = 0
    while (i < len(llm_cases) or j < len(det)) and len(merged) < MAX_CASES_PER_SCREEN:
        if i < len(llm_cases):
            merged.append(llm_cases[i]); i += 1
        if j < len(det) and len(merged) < MAX_CASES_PER_SCREEN:
            merged.append(det[j]); j += 1
    return merged


# ---------------------------------------------------------------------------
# Execution with video
# ---------------------------------------------------------------------------


async def _click_first_cta(page: Page, labels: list[str]) -> Optional[str]:
    for label in labels:
        try:
            await page.get_by_role("button", name=label, exact=False).first.click(
                timeout=1200, no_wait_after=True)
            return label
        except Exception:  # noqa: BLE001
            continue
    return None


async def _run_case_with_video(
    browser: Browser,
    screen: dict[str, Any],
    case: dict[str, Any],
    run_id: str,
    vp: dict[str, Any],
    on_progress=None,
) -> dict[str, Any]:
    case_id = f"st_{uuid.uuid4().hex[:8]}"
    vp_label = vp["label"]
    value = case.get("value", "")
    value_disp = value if len(value) <= 60 else value[:60] + "…"
    field = case.get("field", "input")
    steps = [
        f"Reach screen: {screen.get('name')}",
        f"Focus field: {field}",
        f"Enter: {value_disp or '(empty)'}",
        "Submit & read validation",
    ]

    if on_progress:
        await on_progress({"type": "test_case", "phase": "start", "id": case_id,
                           "name": case.get("name"), "category": "Screen test",
                           "steps": steps, "status": "running",
                           "expected_result": case.get("expectation"),
                           "explanation": case.get("rationale", "")})

    ctx = await _new_context(browser, vp, record_video=True)
    page = await ctx.new_page()
    verdict = "warn"
    outcome: dict[str, Any] = {}
    screenshot_url: Optional[str] = None
    video_url: Optional[str] = None
    try:
        await replay_path(page, screen.get("path", []))
        if on_progress:
            await on_progress({"type": "test_case_step", "case_id": case_id, "step_index": 1,
                               "step": steps[1], "viewport": vp_label})
        sel = case.get("selector")
        filled = await _fill_field(page, sel, value) if sel else False
        try:
            await page.keyboard.press("Tab")
        except Exception:  # noqa: BLE001
            pass
        if on_progress:
            await on_progress({"type": "test_case_step", "case_id": case_id, "step_index": 2,
                               "step": steps[2], "viewport": vp_label})
        await _click_first_cta(page, SUBMIT_CTAS)
        await page.wait_for_timeout(500)
        outcome = await _detect_validation_outcome(page)
        verdict = _grade(case.get("expectation", "accept_but_warn"), outcome) if filled else "warn"

        # Screenshot of the result.
        fname = f"{run_id}_screentest_{case_id}.jpg"
        try:
            png = await page.screenshot(full_page=False, type="jpeg", quality=72, timeout=5000)
            (SCREENSHOTS_DIR / fname).write_bytes(png)
            screenshot_url = f"/api/screens/{fname}"
            if on_progress:
                await on_progress({"type": "live_frame", "kind": "screen_test",
                                   "label": f"{screen.get('name')}: {case.get('name')}",
                                   "image_b64": base64.b64encode(png).decode("ascii"),
                                   "screenshot_url": screenshot_url})
        except Exception:  # noqa: BLE001
            pass

        # Finalize the video (must close the page first).
        try:
            video = page.video
            await page.close()
            if video:
                raw = await video.path()
                if raw and Path(raw).exists():
                    vname = f"{run_id}_screentest_{case_id}_{_safe_name(vp_label)}.webm"
                    (SCREENSHOTS_DIR / vname).write_bytes(Path(raw).read_bytes())
                    video_url = f"/api/screens/{vname}"
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("case run failed (%s): %s", case.get("name"), exc)
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass

    rejected = bool(outcome.get("visible_error") or outcome.get("invalid_count") or outcome.get("aria_invalid"))
    explanation = (
        f"Expected the screen to {case.get('expectation', 'handle this')}. "
        + ("The app showed a validation error / rejected the input."
           if rejected else "The app accepted the input without complaint.")
        + (f" Errors: {' | '.join(outcome.get('error_texts', [])[:2])}" if outcome.get("error_texts") else "")
    )

    done = {
        "id": case_id, "name": case.get("name"), "category": "Screen test",
        "steps": steps, "status": verdict, "expected_result": case.get("expectation"),
        "explanation": explanation,
    }
    if on_progress:
        await on_progress({"type": "test_case", "phase": "end", **done})
        await on_progress({
            "type": "screen_test",
            "id": case_id,
            "screen_id": screen.get("screen_id"),
            "screen_name": screen.get("name"),
            "screen_purpose": screen.get("purpose", ""),
            "route": screen.get("route"),
            "field": field,
            "case_name": case.get("name"),
            "value": value_disp,
            "expectation": case.get("expectation"),
            "rationale": case.get("rationale", ""),
            "verdict": verdict,
            "source": case.get("source", "deterministic"),
            "video_url": video_url,
            "screenshot_url": screenshot_url,
            "viewport": vp_label,
        })

    return {**done, "screen_name": screen.get("name"), "field": field,
            "value": value_disp, "rationale": case.get("rationale", ""),
            "video_url": video_url, "screenshot_url": screenshot_url}


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


async def generate_and_run_screen_tests(
    browser: Browser,
    screens: list[dict[str, Any]],
    run_id: str,
    project: dict[str, Any],
    *,
    on_progress=None,
    viewport: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    vp = viewport or VIEWPORTS[0]
    results: list[dict[str, Any]] = []
    total = 0

    for screen in screens:
        if total >= MAX_TOTAL_CASES:
            break
        if not screen.get("fields"):
            continue  # no inputs to probe on this screen

        brief = await _llm_screen_brief(project, screen)
        if brief.get("purpose"):
            screen["purpose"] = brief["purpose"]
        elif not screen.get("purpose"):
            screen["purpose"] = (screen.get("heading") or screen.get("name") or "").strip()

        cases = _merge_cases(screen, brief)
        if not cases:
            continue

        if on_progress:
            try:
                await on_progress({
                    "type": "screen_context",
                    "screen_id": screen.get("screen_id"),
                    "screen_name": screen.get("name"),
                    "purpose": screen.get("purpose", ""),
                    "route": screen.get("route"),
                    "field_count": len(screen.get("fields", [])),
                    "planned_cases": len(cases),
                })
            except Exception:  # noqa: BLE001
                pass

        for case in cases:
            if total >= MAX_TOTAL_CASES:
                break
            total += 1
            try:
                res = await asyncio.wait_for(
                    _run_case_with_video(browser, screen, case, run_id, vp, on_progress),
                    timeout=CASE_TIMEOUT_SECS,
                )
                results.append(res)
            except asyncio.TimeoutError:
                logger.warning("screen test timed out: %s / %s", screen.get("name"), case.get("name"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("screen test errored: %s", exc)

    logger.info("Screen tests: ran %d cases across %d screens", len(results), len(screens))
    return results
