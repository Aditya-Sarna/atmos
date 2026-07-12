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
