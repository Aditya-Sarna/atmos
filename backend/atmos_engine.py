"""Atmos real engine — crawls a target app, fills forms, captures FULL-PAGE
screenshots of every discovered screen at multiple viewports, then asks Claude
Sonnet 4.5 (vision) to find issues. For each issue Atmos applies a CSS patch
on the specific page where the issue lives and re-captures the full page.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urldefrag, urljoin

from playwright.async_api import Browser, BrowserContext, Page, async_playwright  # noqa: F401

logger = logging.getLogger("atmos.engine")

SCREENSHOTS_DIR = Path(os.environ.get(
    "ATMOS_SCREENSHOTS_DIR",
    str(Path(__file__).resolve().parent / "screenshots"),
))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def configure_playwright_browsers() -> None:
    """Use pre-baked cloud browsers when present; otherwise Playwright's default cache."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    cloud_browsers = Path("/pw-browsers")
    if cloud_browsers.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cloud_browsers)


configure_playwright_browsers()

# Reduced to 2 viewports (mobile + desktop) so crawling N pages stays under ~3 min.
VIEWPORTS = [
    {"label": "iPhone SE",    "w": 375,  "h": 667,  "device_scale": 2, "mobile": True},
    {"label": "Desktop 1440", "w": 1440, "h": 900,  "device_scale": 1, "mobile": False},
]

# Crawl budget — much higher now that we drive the crawl with link + button clicks.
MAX_PAGES = int(os.environ.get("ATMOS_MAX_PAGES", "24"))
MAX_LINKS_PER_PAGE = int(os.environ.get("ATMOS_MAX_LINKS_PER_PAGE", "24"))
MAX_CLICKS_PER_PAGE = 3  # Reduced for speed
NAV_TIMEOUT_MS = 8000  # Shorter nav timeout
SETTLE_WAIT_MS = 400  # Faster settle
ROUTE_TIMEOUT_SECS = 25  # Max time per route
AUTH_DETECT_KEYWORDS = {"lock", "auth", "login", "signin", "signup", "pin", "onboarding"}

# Verbs we will NOT click during exploration — destructive / session-breaking.
FORBIDDEN_CLICK_TEXT = re.compile(
    r"\b(log\s*out|sign\s*out|delete|remove|cancel\s+subscription|uninstall|destroy|wipe|reset\s+password|deactivate|close\s+account|unsubscribe)\b",
    re.I,
)

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
      "patch_css": "Safe, additive CSS that fixes this visibly in a static screenshot when injected. CRITICAL: selectors MUST be GENERIC (e.g. 'button', 'a', 'h1', 'input[type=text]', 'form', '[role=button]') so they actually match the page DOM. DO NOT invent class names. If you don't know the exact selector, use the tag + an attribute that appears in the page text (e.g. 'button:has-text(\"Continue\")') or a structural selector like 'main > section:first-child h2'. Each rule must be visually obvious (bg color, outline, font-size, padding ≥8px change).",
      "patch_explanation": "1 sentence explaining what the patch does",
      "alternatives": [
        {"label": "<6 words", "summary": "<25 words", "tradeoff": "<20 words", "patch_css": "alt CSS (same selector rules as above)"},
        {"label": "<6 words", "summary": "<25 words", "tradeoff": "<20 words", "patch_css": "alt CSS (same selector rules as above)"}
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
    "the problem on the specific page in a STATIC full-page PNG (no hover-only, no :focus-only, "
    "no aria-only changes). Use concrete selectors with layout/color/size/spacing changes that are "
    "obvious without user interaction. Patches must be additive CSS (no @import, no JS, no DOM "
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


VIDEOS_DIR = Path(os.environ.get("ATMOS_VIDEOS_DIR") or (
    "/app/backend/videos" if Path("/app/backend").exists() else str(Path(__file__).resolve().parent / "videos")
))
try:
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Unit tests / restricted sandboxes — video dir is optional until record_video is used
    VIDEOS_DIR = Path(__file__).resolve().parent / "videos"
    try:
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


async def _new_context(
    browser: Browser,
    vp: dict[str, Any],
    *,
    record_video: bool = False,
    record_dir: Optional[str] = None,
) -> BrowserContext:
    is_mobile = bool(vp.get("mobile", False))
    kwargs: dict[str, Any] = {}
    if record_video:
        kwargs["record_video_dir"] = str(record_dir or VIDEOS_DIR)
        kwargs["record_video_size"] = {"width": vp["w"], "height": vp["h"]}

    return await browser.new_context(
        viewport={"width": vp["w"], "height": vp["h"]},
        device_scale_factor=vp.get("device_scale", 1),
        is_mobile=is_mobile,
        has_touch=is_mobile,
        # Required so injected <style> patches apply on CSP-restricted production sites.
        bypass_csp=True,
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ) if is_mobile else (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        **kwargs,
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
            """() => {
                const hrefs = new Set();
                // Standard anchor links
                document.querySelectorAll('a[href]').forEach(a => { if(a.href) hrefs.add(a.href); });
                // Any element with a generic href attribute (SVG links, custom elements, etc.)
                document.querySelectorAll('[href]').forEach(el => {
                    const v = el.getAttribute('href');
                    if (v && !v.startsWith('#') && !v.startsWith('mailto:') && !v.startsWith('tel:')) hrefs.add(el.href || v);
                });
                // data-href / data-path / data-url patterns used by some React Router wrappers
                document.querySelectorAll('[data-href],[data-path],[data-url]').forEach(el => {
                    const v = el.dataset.href || el.dataset.path || el.dataset.url;
                    if (v) hrefs.add(v);
                });
                // React Router NavLink active items often have 'to' preserved in dataset
                document.querySelectorAll('[data-to]').forEach(el => { if(el.dataset.to) hrefs.add(el.dataset.to); });
                return Array.from(hrefs);
            }"""
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


async def _enumerate_buttons(page: Page) -> list[dict[str, Any]]:
    """Return [{text, type, rect, isIcon}] for every visible interactive element.

    Captures BOTH text-labelled controls AND icon-only elements (SVG icons,
    aria-label-only buttons, elements with title attribute but no inner text).
    """
    try:
        raw = await page.evaluate(
            """() => {
                const out = [];
                const seen = new Set();
                const SELECTORS = [
                    'button', '[role="button"]', '[role="menuitem"]', '[role="tab"]',
                    'input[type="button"]', 'input[type="submit"]',
                    'a[href]', '[role="link"]',
                    '[aria-label]', '[title]',
                ];
                const els = Array.from(new Set(
                    SELECTORS.flatMap(s => Array.from(document.querySelectorAll(s)))
                ));
                for (const el of els) {
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                    if (!el.offsetParent && style.position !== 'fixed' && style.position !== 'absolute') continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 8 || r.height < 8) continue;
                    // Text-labelled button
                    const visibleText = (el.innerText || el.value || '').trim();
                    const ariaLabel = (el.getAttribute('aria-label') || el.title || el.getAttribute('data-tooltip') || '').trim();
                    const text = (visibleText || ariaLabel).slice(0, 80);
                    const hasSvg = !!(el.querySelector('svg') || (el.tagName === 'svg'));
                    const isIconOnly = (!visibleText || visibleText.length === 0) && (hasSvg || !!ariaLabel);
                    if (!text && !isIconOnly) continue;
                    const key = (text || `icon@${Math.round(r.x)},${Math.round(r.y)}`).toLowerCase();
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push({
                        text: text || '[icon]',
                        type: el.tagName.toLowerCase(),
                        rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
                        isIcon: isIconOnly,
                    });
                    if (out.length >= 60) break;
                }
                return out;
            }"""
        )
    except Exception:  # noqa: BLE001
        return []
    safe: list[dict[str, Any]] = []
    for b in raw:
        text = b.get("text", "")
        if FORBIDDEN_CLICK_TEXT.search(text):
            continue
        safe.append(b)
    return safe


async def _click_button_by_text(page: Page, button: dict[str, Any] | str) -> bool:
    """Click a discovered interactive control.

    Prefer semantic locators when we have a text label, but fall back to a
    coordinate click using the descriptor captured during enumeration. This is
    more reliable for Framer Motion buttons and other custom controls whose
    accessible name does not round-trip cleanly.
    """
    text = button if isinstance(button, str) else (button.get("text") or "")
    try:
        if text:
            await page.get_by_role("button", name=text, exact=True).first.click(timeout=2000, no_wait_after=True)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if text:
            await page.get_by_role("tab", name=text, exact=True).first.click(timeout=2000, no_wait_after=True)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if text:
            await page.get_by_role("menuitem", name=text, exact=True).first.click(timeout=2000, no_wait_after=True)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if text:
            await page.get_by_role("link", name=text, exact=True).first.click(timeout=2000, no_wait_after=True)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if text:
            await page.get_by_text(text, exact=True).first.click(timeout=2000, no_wait_after=True)
            return True
    except Exception:  # noqa: BLE001
        pass
    if isinstance(button, dict):
        rect = button.get("rect") or {}
        x = rect.get("x")
        y = rect.get("y")
        w = rect.get("w")
        h = rect.get("h")
        if all(isinstance(v, (int, float)) for v in (x, y, w, h)):
            try:
                await page.mouse.click(x + w / 2, y + h / 2, delay=30)
                return True
            except Exception:  # noqa: BLE001
                pass
    return False


_SELECTOR_RX = re.compile(r"([^{}@]+)\{", re.M)


def _extract_selectors(css: str) -> list[str]:
    """Pull every top-level selector list out of a CSS string. Skips at-rules."""
    out: list[str] = []
    for m in _SELECTOR_RX.finditer(css or ""):
        chunk = m.group(1).strip()
        if chunk.startswith("@") or not chunk:
            continue
        for sel in chunk.split(","):
            sel = sel.strip()
            if sel and not sel.startswith("@"):
                out.append(sel)
    return out


async def _selectors_match_anything(page: Page, css: str) -> bool:
    """Heuristic: did any of the CSS selectors actually match a DOM node?
    If not, the patch is a visual no-op and we need a diagnostic overlay."""
    selectors = _extract_selectors(css)
    if not selectors:
        return False
    try:
        return bool(await page.evaluate(
            """(sels) => sels.some(s => {
                try { return document.querySelector(s) != null; }
                catch (_) { return false; }
            })""",
            selectors[:40],
        ))
    except Exception:  # noqa: BLE001
        return False


async def _inject_patch_css(page: Page, css: str, *, emphasize_interaction: bool = False) -> None:
    """Inject a CSS patch and wait for layout/paint. Mirrors baseline page state first."""
    css = (css or "").strip()
    if not css:
        return

    try:
        await page.add_style_tag(content=css)
    except Exception as exc:  # noqa: BLE001
        logger.warning("add_style_tag failed: %s", exc)

    # Also inject via evaluate so patches survive strict CSP even if add_style_tag is ignored.
    try:
        await page.evaluate(
            """(css) => {
                let el = document.getElementById('atmos-patch-style');
                if (!el) {
                    el = document.createElement('style');
                    el.id = 'atmos-patch-style';
                    (document.head || document.documentElement).appendChild(el);
                }
                el.textContent = css;
            }""",
            css,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluate style inject failed: %s", exc)

    needs_focus = emphasize_interaction or bool(re.search(r":focus(-visible)?", css, re.I))
    if needs_focus:
        try:
            await page.evaluate(
                """() => {
                    const pick = document.querySelector(
                        'a[href], button, input:not([type=hidden]), textarea, select, [tabindex]:not([tabindex="-1"])'
                    );
                    if (pick) pick.focus();
                }"""
            )
            await page.keyboard.press("Tab")
        except Exception:  # noqa: BLE001
            pass

    try:
        await page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(450)


def _screenshot_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes() if path.exists() else None
    except Exception:  # noqa: BLE001
        return None


ASYNC_DIAGNOSTIC_BANNER_JS = r"""(payload) => {
    const root = document.body || document.documentElement;
    if (!root) return;
    const old = document.getElementById('atmos-diagnostic-banner');
    if (old) old.remove();
    const banner = document.createElement('div');
    banner.id = 'atmos-diagnostic-banner';
    banner.style.cssText = [
        'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:2147483647',
        'padding:14px 20px', 'font:600 14px/1.3 -apple-system, system-ui, sans-serif',
        'color:#fff', `background:${payload.color}`, 'box-shadow:0 8px 24px rgba(0,0,0,0.18)',
        'text-align:left', 'border-bottom:3px solid rgba(0,0,0,0.25)',
    ].join(';') + ';';
    banner.textContent = payload.text;
    root.prepend(banner);
    document.documentElement.style.scrollPaddingTop = '60px';
}"""


async def _add_diagnostic_banner(page: Page, text: str, color: str = "#FF9500") -> None:
    try:
        await page.evaluate(ASYNC_DIAGNOSTIC_BANNER_JS, {"text": text, "color": color})
        await page.wait_for_timeout(120)
    except Exception:  # noqa: BLE001
        pass


def _write_pixel_diff(before_path: Path, after_path: Path, out_path: Path) -> Optional[dict[str, Any]]:
    """Generate a side-by-side image with red overlay highlighting changed pixels.
    Returns {changed_pct, diff_path} or None on failure."""
    try:
        from PIL import Image, ImageChops, ImageDraw  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    try:
        a = Image.open(before_path).convert("RGB")
        b = Image.open(after_path).convert("RGB")
        # Pad shorter image so heights match
        if a.size != b.size:
            w = max(a.width, b.width)
            h = max(a.height, b.height)
            ca = Image.new("RGB", (w, h), "white"); ca.paste(a, (0, 0)); a = ca
            cb = Image.new("RGB", (w, h), "white"); cb.paste(b, (0, 0)); b = cb
        diff = ImageChops.difference(a, b).convert("L")
        mask = diff.point(lambda p: 255 if p > 12 else 0)
        changed = sum(mask.getdata()) / 255
        total = mask.width * mask.height
        pct = (changed / total * 100.0) if total else 0.0

        overlay = b.copy()
        red = Image.new("RGB", b.size, (255, 59, 48))
        overlay.paste(red, mask=mask)

        canvas_w = a.width + b.width + 16
        canvas_h = max(a.height, b.height)
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        canvas.paste(a, (0, 0))
        canvas.paste(overlay, (a.width + 16, 0))
        draw = ImageDraw.Draw(canvas)
        draw.text((10, 6), "BEFORE", fill=(255, 59, 48))
        draw.text((a.width + 26, 6), f"AFTER · {pct:.2f}% pixels changed", fill=(0, 113, 227))
        canvas.save(out_path, format="PNG", optimize=True)
        return {"changed_pct": round(pct, 3), "diff_path": out_path}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pixel diff failed: %s", exc)
        return None


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
        # Match baseline state for patch captures so before/after differ only by the CSS fix.
        await _fill_visible_forms(page)
        await page.wait_for_timeout(300)
        if inject_css:
            await _inject_patch_css(page, inject_css)

        fname = f"{run_id}_{_safe_name(page_slug)}_{_safe_name(vp_label)}_{kind}.png"
        path = SCREENSHOTS_DIR / fname
        png = await page.screenshot(full_page=True, timeout=20000)
        path.write_bytes(png)
        image_hash = hashlib.sha1(png).hexdigest()[:16]
        title = ""
        try:
            title = (await page.title())[:120]
        except Exception:  # noqa: BLE001
            pass
        video_url: Optional[str] = None
        try:
            if page.video:
                # Must close page before the video file is finalized.
                await page.close()
                raw_video_path = await page.video.path()
                if raw_video_path:
                    vf = Path(raw_video_path)
                    vname = f"{run_id}_{_safe_name(page_slug)}_{_safe_name(vp_label)}_{kind}.webm"
                    vdest = SCREENSHOTS_DIR / vname
                    if vf.exists():
                        vdest.write_bytes(vf.read_bytes())
                        video_url = f"/api/screens/{vname}"
        except Exception:  # noqa: BLE001
            video_url = None

        return {
            "ok": True,
            "url_path": f"/api/screens/{fname}",
            "title": title,
            "image_hash": image_hash,
            "video_url": video_url,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Full-page capture failed (%s @ %s): %s", url, vp_label, exc)
        return {"ok": False, "error": str(exc)[:200]}
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass


def _infer_route_action(route: str, context_hint: Optional[dict[str, Any]] = None) -> str:
    r = (route or "").lower()
    if any(k in r for k in ("send", "pay", "transfer", "checkout")):
        return "submit_payment"
    if any(k in r for k in ("receive", "request", "redeem")):
        return "receive_flow"
    if any(k in r for k in ("login", "signin", "auth", "onboarding", "lock")):
        return "auth_flow"
    if any(k in r for k in ("profile", "settings", "security", "backup")):
        return "settings_flow"
    if any(k in r for k in ("scan", "camera", "qr")):
        return "scan_flow"
    if context_hint and context_hint.get("action"):
        return str(context_hint["action"])
    return "generic"


async def _perform_context_action(
    page: Page,
    *,
    route: str,
    context_hint: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Use route + code hint context to perform a relevant action.

    This is intentionally deterministic and safe: fill forms, then click one
    primary CTA that matches the route's likely intent.
    """
    action = _infer_route_action(route, context_hint)
    filled = await _fill_visible_forms(page)

    cta_by_action: dict[str, list[str]] = {
        "submit_payment": ["send", "pay", "continue", "next", "confirm", "submit"],
        "receive_flow": ["receive", "request", "generate", "continue"],
        "auth_flow": ["sign in", "login", "continue", "next", "unlock", "get started"],
        "settings_flow": ["save", "update", "enable", "backup", "continue"],
        "scan_flow": ["scan", "open camera", "continue", "allow"],
        "generic": ["continue", "next", "submit", "save", "confirm"],
    }
    clicked = None
    for label in cta_by_action.get(action, cta_by_action["generic"]):
        ok = await _click_button_by_text(page, label)
        if ok:
            clicked = label
            try:
                await page.wait_for_load_state("networkidle", timeout=2200)
            except Exception:  # noqa: BLE001
                pass
            await page.wait_for_timeout(300)
            break

    return {
        "action": action,
        "filled_fields": filled,
        "clicked_cta": clicked,
    }


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------


async def _emit_frame(on_progress, page: Page, label: str, kind: str = "live") -> None:
    """Capture a small JPEG of the current viewport and publish as a live-stream frame."""
    if not on_progress:
        return
    try:
        png = await page.screenshot(full_page=False, type="jpeg", quality=72, timeout=4000)
    except Exception:  # noqa: BLE001
        return
    try:
        await on_progress({
            "type": "live_frame",
            "kind": kind,
            "label": label,
            "image_b64": base64.b64encode(png).decode("ascii"),
        })
    except Exception:  # noqa: BLE001
        pass


async def crawl_and_capture(browser: Browser, start_url: str, run_id: str, on_progress=None) -> dict[str, Any]:
    """Discover up to MAX_PAGES same-origin pages and capture each one at
    every viewport. The discovery pass now actually CLICKS visible safe
    buttons to surface modals / route changes that don't have an <a> tag.

    Returns {pages, button_actions}.
    """
    start_norm = _normalize(start_url)
    discovered_urls: list[str] = [start_norm]
    button_actions: list[dict[str, Any]] = []

    # ── 1) Interactive discovery on a single desktop context ───────────
    discovery_ctx = await _new_context(browser, VIEWPORTS[1])  # Desktop for richer link harvest
    discovery_page = await discovery_ctx.new_page()
    explored_urls: set[str] = set()

    # Track ALL URL changes emitted by pushState / hash navigation / redirects.
    nav_discovered: list[str] = []

    def _on_frame_navigated(frame) -> None:  # noqa: ANN001
        try:
            if frame == discovery_page.main_frame:
                u = _normalize(frame.url)
                if u and _same_origin(start_url, u) and u not in discovered_urls and u not in nav_discovered:
                    nav_discovered.append(u)
        except Exception:  # noqa: BLE001
            pass

    discovery_page.on("framenavigated", _on_frame_navigated)

    try:
        while len(explored_urls) < len(discovered_urls) and len(discovered_urls) < MAX_PAGES * 2:
            current_url = next((u for u in discovered_urls if u not in explored_urls), None)
            if not current_url:
                break
            explored_urls.add(current_url)
            try:
                await discovery_page.goto(current_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await _settle(discovery_page)
                # Give JS frameworks (React, Vue, etc.) extra time to render client-side routes.
                await discovery_page.wait_for_timeout(600)
                await _emit_frame(on_progress, discovery_page, f"Exploring — {current_url}")

                # Flush any URLs captured by the framenavigated listener so far.
                for u in list(nav_discovered):
                    if u not in discovered_urls:
                        discovered_urls.append(u)
                nav_discovered.clear()

                harvested = await _extract_links(discovery_page, current_url)
                for u in harvested:
                    if u not in discovered_urls:
                        discovered_urls.append(u)

                # Click safe controls one by one for THIS page, then return to THIS page.
                buttons = await _enumerate_buttons(discovery_page)
                for b in buttons[:MAX_CLICKS_PER_PAGE]:
                    pre_url = _normalize(discovery_page.url)
                    clicked = await _click_button_by_text(discovery_page, b)
                    if not clicked:
                        continue
                    try:
                        await discovery_page.wait_for_load_state("networkidle", timeout=2500)
                    except Exception:  # noqa: BLE001
                        pass
                    await discovery_page.wait_for_timeout(400)
                    post_url = _normalize(discovery_page.url)
                    await _emit_frame(on_progress, discovery_page, f"Clicked: {b['text']}")
                    button_actions.append({
                        "label": b["text"],
                        "from": pre_url,
                        "to": post_url,
                        "navigated": pre_url != post_url,
                    })
                    if post_url != pre_url and _same_origin(start_url, post_url) and post_url not in discovered_urls:
                        discovered_urls.append(post_url)

                    # Flush nav listener hits (pushState navigations triggered by the click).
                    for u in list(nav_discovered):
                        if u not in discovered_urls:
                            discovered_urls.append(u)
                    nav_discovered.clear()

                    new_links = await _extract_links(discovery_page, post_url)
                    for u in new_links:
                        if u not in discovered_urls and _same_origin(start_url, u):
                            discovered_urls.append(u)

                    # Return to the page currently being explored so later clicks are independent.
                    if _normalize(discovery_page.url) != current_url:
                        try:
                            await discovery_page.goto(current_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                            await _settle(discovery_page)
                            await discovery_page.wait_for_timeout(400)
                        except Exception:  # noqa: BLE001
                            break

                    if len(discovered_urls) >= MAX_PAGES * 2:
                        break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Discovery failed for %s: %s", current_url, exc)
    finally:
        await discovery_page.close()
        await discovery_ctx.close()

    # Cap to MAX_PAGES; keep order with start URL first.
    target_urls = discovered_urls[:MAX_PAGES]

    # ── 2) Capture every target page at every viewport ─────────────────
    contexts = []
    for vp in VIEWPORTS:
        contexts.append((vp, await _new_context(browser, vp)))

    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    try:
        for idx, url in enumerate(target_urls):
            if url in seen:
                continue
            seen.add(url)
            page_slug = f"page{idx:02d}"
            page_entry: dict[str, Any] = {
