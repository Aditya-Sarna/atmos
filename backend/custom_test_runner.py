"""Execute user-written test cases with Playwright video recording."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import Browser, Page

from atmos_engine import NAV_TIMEOUT_MS, SCREENSHOTS_DIR, VIEWPORTS, _new_context, _safe_name, _settle

logger = logging.getLogger("atmos.custom_tests")

ProgressFn = Callable[[dict[str, Any]], Any]

VALID_ACTIONS = {"navigate", "click", "fill", "press", "wait", "assert_visible", "assert_text", "screenshot"}


async def _resolve_url(base_url: str, step_url: str) -> str:
    if step_url.startswith("http"):
        return step_url
    base = base_url.rstrip("/")
    if not base.endswith("/") and not step_url.startswith("/"):
        return f"{base}/{step_url}"
    return urljoin(base + "/", step_url.lstrip("/"))


async def _execute_step(page: Page, step: dict[str, Any], base_url: str) -> dict[str, Any]:
    action = step.get("action", "").lower()
    result: dict[str, Any] = {"action": action, "status": "pass", "detail": ""}

    if action == "navigate":
        url = await _resolve_url(base_url, step.get("url", "/"))
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        await _settle(page)
        result["detail"] = f"Navigated to {url}"

    elif action == "click":
        selector = step.get("selector") or step.get("text")
        if not selector:
            raise ValueError("click step requires selector or text")
        if selector.startswith("text="):
            await page.get_by_text(selector[5:], exact=False).first.click(timeout=8000)
        else:
            await page.click(selector, timeout=8000)
        await _settle(page)
        result["detail"] = f"Clicked {selector}"

    elif action == "fill":
        selector = step.get("selector")
        value = step.get("value", "")
        if not selector:
            raise ValueError("fill step requires selector")
        if selector.startswith("text="):
            label = selector[5:]
            loc = page.get_by_label(label, exact=False)
            if await loc.count() == 0:
                loc = page.get_by_placeholder(label, exact=False)
            await loc.first.fill(value, timeout=8000)
        else:
            await page.fill(selector, value, timeout=8000)
        result["detail"] = f"Filled {selector}"

    elif action == "press":
        key = step.get("key", "Enter")
        await page.keyboard.press(key)
        await page.wait_for_timeout(300)
        result["detail"] = f"Pressed {key}"

    elif action == "wait":
        ms = int(step.get("ms", step.get("timeout", 1000)))
        await page.wait_for_timeout(ms)
        result["detail"] = f"Waited {ms}ms"

    elif action == "assert_visible":
        selector = step.get("selector")
        if not selector:
            raise ValueError("assert_visible requires selector")
        el = page.locator(selector).first
        if not await el.is_visible(timeout=5000):
            result["status"] = "fail"
            result["detail"] = f"Element not visible: {selector}"
        else:
            result["detail"] = f"Visible: {selector}"

    elif action == "assert_text":
        text = step.get("text", "")
        content = await page.inner_text("body")
        if text.lower() not in content.lower():
            result["status"] = "fail"
            result["detail"] = f"Text not found: {text}"
        else:
            result["detail"] = f"Found text: {text}"

    elif action == "screenshot":
        name = step.get("name", "step")
        result["detail"] = f"Screenshot checkpoint: {name}"

    else:
        raise ValueError(f"Unknown action: {action}")

    return result


async def run_custom_test_case(
    browser: Browser,
    base_url: str,
    case: dict[str, Any],
    run_id: str,
    *,
    on_progress: Optional[ProgressFn] = None,
    viewport_label: str = "Desktop 1440",
) -> dict[str, Any]:
    """Run one user-defined test case; record full session as .webm."""
    case_id = case.get("case_id") or case.get("id") or f"ctc_{uuid.uuid4().hex[:8]}"
    name = case.get("name", "Custom test")
    steps = case.get("steps") or []
    vp = next((v for v in VIEWPORTS if v["label"] == viewport_label), VIEWPORTS[-1])

    slug = _safe_name(f"custom_{case_id}")
    video_name = f"{run_id}_{slug}.webm"

    ctx = await _new_context(browser, vp, record_video=True, record_dir=SCREENSHOTS_DIR)
    page = await ctx.new_page()
    step_results: list[dict[str, Any]] = []
    overall = "pass"

    try:
        if on_progress:
            await on_progress({
                "type": "custom_test_start",
                "case_id": case_id,
                "name": name,
                "steps": [s.get("description") or s.get("action", "") for s in steps],
            })

        for idx, step in enumerate(steps):
            step_desc = step.get("description") or f"{step.get('action')} {step.get('selector') or step.get('url') or ''}"
            if on_progress:
                await on_progress({
                    "type": "custom_test_step",
                    "case_id": case_id,
                    "step_index": idx,
                    "step": step_desc,
                    "status": "running",
                })
            try:
                sr = await _execute_step(page, step, base_url)
                sr["step_index"] = idx
                sr["description"] = step_desc
                step_results.append(sr)
                if sr["status"] == "fail":
                    overall = "fail"
                shot_name = f"{run_id}_{slug}_step{idx}.png"
                await page.screenshot(path=str(SCREENSHOTS_DIR / shot_name), full_page=False)
                if on_progress:
                    await on_progress({
                        "type": "custom_test_step",
                        "case_id": case_id,
                        "step_index": idx,
                        "step": step_desc,
                        "status": sr["status"],
                        "screenshot_url": f"/api/screens/{shot_name}",
                        "detail": sr.get("detail"),
                    })
            except Exception as exc:  # noqa: BLE001
                overall = "fail"
                step_results.append({
                    "step_index": idx,
                    "description": step_desc,
                    "status": "fail",
                    "detail": str(exc),
                })
                if on_progress:
                    await on_progress({
                        "type": "custom_test_step",
                        "case_id": case_id,
                        "step_index": idx,
                        "step": step_desc,
                        "status": "fail",
                        "detail": str(exc),
                    })
                if not step.get("optional"):
                    break

        await page.close()
        video_path = await page.video.path() if page.video else None
        video_url = f"/api/screens/{video_name}" if video_path and Path(video_path).exists() else None

        result = {
            "case_id": case_id,
            "name": name,
            "status": overall,
            "video_url": video_url,
            "step_results": step_results,
            "steps_passed": sum(1 for s in step_results if s.get("status") == "pass"),
            "steps_total": len(steps),
            "source": "custom",
        }
        if on_progress:
            await on_progress({"type": "custom_test_complete", **result})
        return result

    except Exception as exc:  # noqa: BLE001
        logger.warning("custom test %s failed: %s", case_id, exc)
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
        return {
            "case_id": case_id,
            "name": name,
            "status": "fail",
            "video_url": None,
            "error": str(exc),
            "step_results": step_results,
            "source": "custom",
        }
    finally:
        await ctx.close()


async def run_custom_test_cases(
    browser: Browser,
    base_url: str,
    cases: list[dict[str, Any]],
    run_id: str,
    on_progress: Optional[ProgressFn] = None,
) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        results.append(await run_custom_test_case(browser, base_url, case, run_id, on_progress=on_progress))
    return results


def nl_step_to_action(step: str, base_url: str) -> dict[str, Any]:
    """Best-effort map of natural-language plan steps → Playwright actions."""
    import re
    s = (step or "").strip()
    low = s.lower()

    m = re.search(r"(?:navigate|go|open|visit)\s+(?:to\s+)?(\S+)", low)
    if m:
        target = m.group(1).strip("'\"")
        if target.startswith("http") or target.startswith("/"):
            return {"action": "navigate", "url": target, "label": s}
        return {"action": "navigate", "url": "/", "label": s}

    m = re.search(r"(?:fill|type|enter)\s+['\"]?(.+?)['\"]?\s+(?:with|as|=)\s+['\"]?(.+?)['\"]?$", low)
    if m:
        return {"action": "fill", "selector": f"text={m.group(1).strip()}", "value": m.group(2).strip(), "label": s}

    m = re.search(r"(?:click|tap|press)\s+(?:on\s+)?['\"]?(.+?)['\"]?$", low)
    if m and "press tab" not in low and "press enter" not in low:
        target = m.group(1).strip()
        return {"action": "click", "text": target, "selector": f"text={target}", "label": s}

    if "press tab" in low or low.strip() == "tab":
        return {"action": "press", "key": "Tab", "label": s}
    if "press enter" in low or "hit enter" in low:
        return {"action": "press", "key": "Enter", "label": s}

    if low.startswith("wait"):
        ms = 800
        num = re.search(r"(\d+)", low)
        if num:
            ms = int(num.group(1))
            if ms < 50:
                ms *= 1000
        return {"action": "wait", "ms": min(ms, 5000), "label": s}

    if low.startswith("assert") or low.startswith("verify") or low.startswith("expect"):
        m = re.search(r"(?:see|visible|find)\s+['\"]?(.+?)['\"]?$", low)
        if m:
            return {"action": "assert_visible", "selector": f"text={m.group(1).strip()}", "label": s}
        return {"action": "wait", "ms": 400, "label": s}

    # Default: try click by visible text of the whole step (truncated)
    snippet = s[:60]
    return {"action": "click", "text": snippet, "selector": f"text={snippet}", "label": s}


async def run_plan_cases_playwright(
    browser: Browser,
    base_url: str,
    cases: list[dict[str, Any]],
    run_id: str,
    on_progress: Optional[ProgressFn] = None,
) -> list[dict[str, Any]]:
    """Execute plan / seeded cases as real Playwright steps (with video), not sleep theater."""
    prepared = []
    for case in cases:
        raw_steps = case.get("steps") or []
        actions = []
        for st in raw_steps:
            if isinstance(st, dict) and st.get("action"):
                actions.append(st)
            else:
                actions.append(nl_step_to_action(str(st), base_url))
        # Always start from base URL
        if not actions or actions[0].get("action") != "navigate":
            actions = [{"action": "navigate", "url": "/", "label": f"Open {base_url}"}] + actions
        prepared.append({
            "case_id": case.get("id") or case.get("case_id") or f"plan_{uuid.uuid4().hex[:8]}",
            "name": case.get("name", "Plan case"),
            "steps": actions,
            "enabled": True,
            "category": case.get("category", "UX"),
            "explanation": case.get("explanation") or case.get("rationale") or "",
            "expected_result": case.get("expected_result", "pass"),
            "frames": case.get("frames") or [],
            "source": "plan",
        })
    return await run_custom_test_cases(browser, base_url, prepared, run_id, on_progress=on_progress)
