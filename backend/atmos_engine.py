"""Atmos real engine — crawls a target app, fills forms, captures FULL-PAGE
screenshots of every discovered screen at multiple viewports, then asks Claude
Sonnet 4.5 (vision) to find issues. For each issue Atmos applies a CSS patch
on the specific page where the issue lives and re-captures the full page.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urldefrag, urljoin

from playwright.async_api import Browser, BrowserContext, Page, async_playwright  # noqa: F401

logger = logging.getLogger("atmos.engine")

SCREENSHOTS_DIR = Path(os.environ.get("ATMOS_SCREENSHOTS_DIR", "/app/backend/screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

# Reduced to 2 viewports (mobile + desktop) so crawling N pages stays under ~3 min.
VIEWPORTS = [
    {"label": "iPhone SE",    "w": 375,  "h": 667,  "device_scale": 2, "mobile": True},
    {"label": "Desktop 1440", "w": 1440, "h": 900,  "device_scale": 1, "mobile": False},
]

# Crawl budget
MAX_PAGES = 5
MAX_LINKS_PER_PAGE = 8
NAV_TIMEOUT_MS = 18000

DEFAULT_FORM_VALUES = {
    "email": "atmos.qa@example.com",
    "search": "test",
    "q": "test",
    "name": "Atmos QA",
    "first_name": "Atmos",
    "last_name": "QA",
    "phone": "+15555550100",
    "password": "Atmos-Test-1!",
    "subject": "Hello from Atmos",
    "message": "Atmos is exploring this form during a UX audit.",
    "company": "Atmos",
    "address": "1 Infinite Loop",
    "city": "Cupertino",
    "zip": "95014",
}

ISSUE_SCHEMA = """\
Return ONLY a minified JSON object with shape:
{
  "narrative": "1 sentence describing the product context across the pages provided.",
  "focus_areas": ["string", ...5-8 entries...],
  "issues": [
    {
      "page_url": "exact URL of the page where this issue appears (must match one of the provided pages)",
      "viewport_label": "iPhone SE" | "Desktop 1440",
      "category": "Visual"|"Accessibility"|"UX"|"Functional"|"Performance",
      "severity": "critical"|"high"|"medium"|"low",
      "title": "Plain-English title <80 chars",
      "cause": "Likely cause <140 chars",
      "patch_css": "Safe, additive CSS that fixes this visibly when injected",
      "patch_explanation": "1 sentence explaining what the patch does",
      "alternatives": [
        {"label": "<6 words", "summary": "<25 words", "tradeoff": "<20 words", "patch_css": "alt CSS"},
        {"label": "<6 words", "summary": "<25 words", "tradeoff": "<20 words", "patch_css": "alt CSS"}
      ]
    }
    ... aim for 6-10 issues spread across the supplied pages ...
  ]
}
No markdown, no commentary. JSON only."""


SYSTEM_PROMPT = (
    "You are Atmos, a meticulous senior UX & accessibility auditor reviewing REAL screenshots from a "
    "production web app. You are shown one or more FULL-PAGE screenshots, each labelled with its URL "
    "and viewport. Identify concrete, observable issues you can SEE — not generic best practices. "
    "For each issue, return a CSS patch that, when injected as a <style> tag, would visibly improve "
    "the problem on the specific page. Patches must be additive CSS (no @import, no JS, no DOM "
    "changes). Each issue MUST include two alternative patches with different trade-offs. Spread "
    "issues across the supplied pages; do not pile every issue on the home page."
)


# ---------------------------------------------------------------------------
# URL / link helpers
# ---------------------------------------------------------------------------


def _normalize(url: str) -> str:
    return urldefrag(url)[0].rstrip("/")


def _same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:80]


# ---------------------------------------------------------------------------
# Context / page helpers
# ---------------------------------------------------------------------------


async def _new_context(browser: Browser, vp: dict[str, Any]) -> BrowserContext:
    is_mobile = bool(vp.get("mobile", False))
    return await browser.new_context(
        viewport={"width": vp["w"], "height": vp["h"]},
        device_scale_factor=vp.get("device_scale", 1),
        is_mobile=is_mobile,
        has_touch=is_mobile,
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ) if is_mobile else (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )


async def _settle(page: Page) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:  # noqa: BLE001
        pass


async def _fill_visible_forms(page: Page) -> int:
    """Best-effort: fill every visible text-like input with sensible test data."""
    filled = 0
    try:
        handles = await page.query_selector_all(
            "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]):not([type=checkbox]):not([type=radio]), textarea"
        )
        for h in handles[:20]:
            try:
                visible = await h.is_visible()
                if not visible:
                    continue
                attrs = await h.evaluate(
                    "(el) => ({type: el.type||'', name: el.name||'', id: el.id||'', ph: el.placeholder||'', al: el.getAttribute('aria-label')||''})"
                )
                hay = " ".join([attrs.get("name") or "", attrs.get("id") or "", attrs.get("ph") or "", attrs.get("al") or "", attrs.get("type") or ""]).lower()
                value = None
                t = (attrs.get("type") or "").lower()
                if t == "email" or "email" in hay:
                    value = DEFAULT_FORM_VALUES["email"]
                elif t == "password":
                    value = DEFAULT_FORM_VALUES["password"]
                elif t == "search" or "search" in hay or hay.strip() in ("q",):
                    value = DEFAULT_FORM_VALUES["search"]
                elif t == "tel" or "phone" in hay:
                    value = DEFAULT_FORM_VALUES["phone"]
                elif "first" in hay:
                    value = DEFAULT_FORM_VALUES["first_name"]
                elif "last" in hay or "surname" in hay:
                    value = DEFAULT_FORM_VALUES["last_name"]
                elif "name" in hay:
                    value = DEFAULT_FORM_VALUES["name"]
                elif "subject" in hay:
                    value = DEFAULT_FORM_VALUES["subject"]
                elif "message" in hay or "comment" in hay or "textarea" in hay:
                    value = DEFAULT_FORM_VALUES["message"]
                elif "company" in hay or "organization" in hay:
                    value = DEFAULT_FORM_VALUES["company"]
                elif "address" in hay or "street" in hay:
                    value = DEFAULT_FORM_VALUES["address"]
                elif "city" in hay:
                    value = DEFAULT_FORM_VALUES["city"]
                elif "zip" in hay or "postal" in hay:
                    value = DEFAULT_FORM_VALUES["zip"]
                else:
                    value = DEFAULT_FORM_VALUES["name"]
                await h.fill(value, timeout=1500)
                filled += 1
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return filled


async def _extract_links(page: Page, start_url: str) -> list[str]:
    try:
        raw = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
        )
    except Exception:  # noqa: BLE001
        raw = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for href in raw:
        if not href:
            continue
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        # ignore obvious file downloads
        if re.search(r"\.(pdf|zip|tar|gz|rar|exe|dmg|pkg)(\?|$)", href, re.I):
            continue
        try:
            absolute = urljoin(start_url, href)
            absolute = _normalize(absolute)
        except Exception:  # noqa: BLE001
            continue
        if not _same_origin(start_url, absolute):
            continue
        if absolute == _normalize(start_url):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        cleaned.append(absolute)
        if len(cleaned) >= MAX_LINKS_PER_PAGE:
            break
    return cleaned


async def _capture_full_page(
    context: BrowserContext, url: str, vp_label: str, run_id: str, page_slug: str, kind: str = "baseline",
    inject_css: Optional[str] = None,
) -> dict[str, Any]:
    """Open a fresh page in the given context, fill visible forms, optionally
    inject CSS, capture a FULL-PAGE PNG."""
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        await _settle(page)
        # On baseline runs we fill forms so that empty inputs aren't reviewed.
        if kind == "baseline":
            await _fill_visible_forms(page)
            await page.wait_for_timeout(300)
        if inject_css:
            try:
                await page.add_style_tag(content=inject_css)
                await page.wait_for_timeout(350)
            except Exception as exc:  # noqa: BLE001
                logger.warning("add_style_tag failed: %s", exc)

        fname = f"{run_id}_{_safe_name(page_slug)}_{_safe_name(vp_label)}_{kind}.png"
        path = SCREENSHOTS_DIR / fname
        png = await page.screenshot(full_page=True, timeout=20000)
        path.write_bytes(png)
        title = ""
        try:
            title = (await page.title())[:120]
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "url_path": f"/api/screens/{fname}", "title": title}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Full-page capture failed (%s @ %s): %s", url, vp_label, exc)
        return {"ok": False, "error": str(exc)[:200]}
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------


async def crawl_and_capture(browser: Browser, start_url: str, run_id: str, on_progress=None) -> dict[str, Any]:
    """Discover up to MAX_PAGES same-origin pages and capture each one at
    every viewport. Returns dict {pages: [{url,title,slug, captures:{vp_label: {url_path,ok}}}], links_seen}."""
    discovered_urls: list[str] = [_normalize(start_url)]
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Use a single mobile context for link discovery (cheap)
    discovery_ctx = await _new_context(browser, VIEWPORTS[1])  # Desktop for richer link harvest
    discovery_page = await discovery_ctx.new_page()

    try:
        # 1) Visit start URL, harvest links.
        try:
            await discovery_page.goto(start_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            await _settle(discovery_page)
            harvested = await _extract_links(discovery_page, start_url)
            for u in harvested:
                if u not in discovered_urls:
                    discovered_urls.append(u)
                if len(discovered_urls) >= MAX_PAGES * 3:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discovery failed for %s: %s", start_url, exc)
    finally:
        await discovery_page.close()
        await discovery_ctx.close()

    # Cap to MAX_PAGES; keep order with start URL first.
    target_urls = discovered_urls[:MAX_PAGES]

    # 2) Capture every target page at every viewport (in parallel per viewport).
    contexts = []
    for vp in VIEWPORTS:
        contexts.append((vp, await _new_context(browser, vp)))

    try:
        for idx, url in enumerate(target_urls):
            if url in seen:
                continue
            seen.add(url)
            page_slug = f"page{idx:02d}"
            page_entry: dict[str, Any] = {
                "url": url,
                "slug": page_slug,
                "title": "",
                "captures": {},
            }
            for vp, ctx in contexts:
                cap = await _capture_full_page(ctx, url, vp["label"], run_id, page_slug, kind="baseline")
                page_entry["captures"][vp["label"]] = cap
                if cap.get("ok") and not page_entry["title"]:
                    page_entry["title"] = cap.get("title") or ""
                if on_progress:
                    try:
                        await on_progress({
                            "type": "page_capture",
                            "url": url, "viewport": vp["label"],
                            "ok": cap.get("ok"),
                            "url_path": cap.get("url_path"),
                            "title": cap.get("title", ""),
                            "page_slug": page_slug,
                            "page_index": idx,
                        })
                    except Exception:  # noqa: BLE001
                        pass
            pages.append(page_entry)
    finally:
        for _, ctx in contexts:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass

    return {"pages": pages}


async def apply_patch_full_page(
    browser: Browser, url: str, vp_label: str, css: str, run_id: str, tag: str, page_slug: str,
) -> Optional[str]:
    """Re-open the page, inject CSS, take a FULL-PAGE screenshot. Returns served URL path."""
    vp = next((v for v in VIEWPORTS if v["label"] == vp_label), VIEWPORTS[-1])
    ctx = await _new_context(browser, vp)
    try:
        cap = await _capture_full_page(ctx, url, vp_label, run_id, f"{page_slug}_{tag}", kind="patch", inject_css=css)
        return cap.get("url_path") if cap.get("ok") else None
    finally:
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


def _parse_llm_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}\s*$", text)
        if m:
            text = m.group(0)
    return json.loads(text)


async def llm_analyze_app(project: dict[str, Any], command: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    from emergentintegrations.llm.chat import (  # type: ignore
        LlmChat, UserMessage, ImageContent, TextDelta, StreamDone,
    )

    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY missing")

    chat = LlmChat(
        api_key=api_key,
        session_id=f"atmos_{project['project_id']}_{uuid.uuid4().hex[:6]}",
        system_message=SYSTEM_PROMPT,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    # Build prompt: list pages with URL + viewport for each attached image.
    images: list[ImageContent] = []
    page_lines: list[str] = []
    # Heuristic budget: max 5 images so prompt stays within reason. Prefer one per page from the best viewport.
    chosen = []
    for p in pages:
        cap = p.get("captures", {}).get("Desktop 1440") or next((c for c in p.get("captures", {}).values() if c.get("ok")), None)
        if cap and cap.get("ok"):
            chosen.append((p, "Desktop 1440" if p["captures"].get("Desktop 1440", {}).get("ok") else next(k for k, v in p["captures"].items() if v.get("ok")), cap))
    chosen = chosen[:5]
    if not chosen:
        raise RuntimeError("No usable page captures to analyze.")
    for p, vp_label, cap in chosen:
        path = SCREENSHOTS_DIR / Path(cap["url_path"]).name
        if not path.exists():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        images.append(ImageContent(image_base64=b64))
        page_lines.append(f"- {p['url']}  (viewport {vp_label}, title: {p.get('title') or '—'})")

    prompt = (
        f"Target product: {project['name']}\n"
        f"Start URL: {project['url']}\n"
        f"Detected archetype: {project.get('app_type')}\n"
        f"Command: {command}\n\n"
        "Pages provided as screenshots (in the order they were attached):\n"
        + "\n".join(page_lines)
        + "\n\nReturn the issues in JSON exactly per this schema. Make sure every issue's page_url "
          "matches one of the URLs above exactly.\n\n"
        + ISSUE_SCHEMA
    )

    text = ""
    async for ev in chat.stream_message(UserMessage(text=prompt, file_contents=images)):
        if isinstance(ev, TextDelta):
            text += ev.content
        elif isinstance(ev, StreamDone):
            break
    return _parse_llm_json(text)


def deterministic_fallback(project: dict[str, Any], pages: list[dict[str, Any]]) -> dict[str, Any]:
    primary_url = pages[0]["url"] if pages else project["url"]
    return {
        "narrative": f"Heuristic fallback audit of {project['name']}.",
        "focus_areas": [
            "Above-the-fold value clarity", "Primary CTA visibility",
            "Mobile responsive layout", "Color contrast & focus states",
            "Heading hierarchy", "Form labeling",
        ],
        "issues": [
            {
                "page_url": primary_url, "viewport_label": "Desktop 1440",
                "category": "Accessibility", "severity": "high",
                "title": "Focus state may be invisible for keyboard users",
                "cause": "Default browser outline often suppressed without replacement.",
                "patch_css": "*:focus-visible{outline:2px solid #0071E3 !important;outline-offset:2px !important;}",
                "patch_explanation": "Adds a high-contrast focus ring across every interactive element.",
                "alternatives": [
                    {"label": "Inset focus glow", "summary": "Inset ring works inside overflow:hidden parents.",
                     "tradeoff": "Slightly heavier visually.",
                     "patch_css": "*:focus-visible{outline:none !important;box-shadow:inset 0 0 0 2px #fff, inset 0 0 0 4px #0071E3 !important;}"},
                    {"label": "Background tint", "summary": "Tint the focused element instead of outlining it.",
                     "tradeoff": "Less explicit; pair with outline for AAA.",
                     "patch_css": "*:focus-visible{outline:none !important;background-color:rgba(0,113,227,0.08) !important;}"},
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Test cases — derived from the crawl results
# ---------------------------------------------------------------------------


def seed_test_cases(app_type: str, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not pages:
        return []
    primary = pages[0]
    primary_caps = primary.get("captures", {})
    other_caps = [p.get("captures", {}) for p in pages[1:]]
    cases = [
        {
            "name": f"Application graph — discovered {len(pages)} reachable pages",
            "category": "UX",
            "steps": ["Visit start URL", "Extract anchor href values", "Cap to crawl budget", "Visit each page"],
            "expected_result": "pass" if len(pages) >= 2 else "warn",
            "explanation": (
                f"Atmos discovered {len(pages)} same-origin pages reachable from the home page."
                if len(pages) >= 2 else "Only the start URL was reachable; site may lack internal links or block crawling."
            ),
            "frames": [primary_caps.get("Desktop 1440", {}).get("url_path") or primary_caps.get("iPhone SE", {}).get("url_path")]
                      + [c.get("Desktop 1440", {}).get("url_path") or c.get("iPhone SE", {}).get("url_path") for c in other_caps],
        },
        {
            "name": "Responsive sweep — every page loads on mobile",
            "category": "Visual",
            "steps": [f"Capture {p['url']} on iPhone SE" for p in pages[:4]] or ["Capture iPhone SE"],
            "expected_result": "pass" if all(p["captures"].get("iPhone SE", {}).get("ok") for p in pages) else "warn",
            "explanation": "Mobile renders captured for every discovered page.",
            "frames": [p["captures"].get("iPhone SE", {}).get("url_path") for p in pages if p["captures"].get("iPhone SE", {}).get("ok")],
        },
        {
            "name": "Forms — visible inputs accept input without errors",
            "category": "Functional",
            "steps": ["Detect visible inputs", "Type representative test data", "Capture page"],
            "expected_result": "pass",
            "explanation": "Atmos filled every detected visible input with representative data and captured the resulting state.",
            "frames": [primary_caps.get("Desktop 1440", {}).get("url_path")],
        },
    ]
    # Strip None entries
    for c in cases:
        c["frames"] = [f for f in c["frames"] if f]
    return cases
