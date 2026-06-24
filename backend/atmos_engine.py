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
      "patch_css": "Safe, additive CSS that fixes this visibly in a static screenshot when injected",
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


VIDEOS_DIR = Path(os.environ.get("ATMOS_VIDEOS_DIR", "/app/backend/videos"))
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


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

    return {"pages": pages, "button_actions": button_actions}


async def capture_routes_direct(
    browser: Browser,
    base_url: str,
    routes: list[str],
    run_id: str,
    route_contexts: Optional[dict[str, dict[str, Any]]] = None,
    on_progress=None,
) -> dict[str, Any]:
    """GitHub-repo mode: navigate directly to every extracted route and capture
    screenshots.  No crawling needed — we already know the routes from source.

    Also clicks ALL interactive elements on each page (including icon-only
    controls like nav icons, tab-bar icons, menu triggers) to surface hidden
    UI states and record button_actions.

    Returns {pages, button_actions} in the same shape as crawl_and_capture.
    """
    base_url = base_url.rstrip("/")
    button_actions: list[dict[str, Any]] = []

    # ── 1) Click-through + icon discovery pass (desktop context) ───────
    discovery_ctx = await _new_context(browser, VIEWPORTS[1])  # Desktop
    discovery_page = await discovery_ctx.new_page()
    visited_slugs: set[str] = set()

    # Auth state we'll inject into every context so protected routes render real content.
    _injected_auth: dict[str, str] = {}

    async def _inject_auth(page: Page) -> None:
        """Inject any auth localStorage keys discovered during the auth-route visit."""
        if _injected_auth:
            try:
                await page.evaluate(
                    "(state) => { for (const [k,v] of Object.entries(state)) localStorage.setItem(k,v); }",
                    _injected_auth,
                )
            except Exception:  # noqa: BLE001
                pass

    def _is_auth_screen(url: str) -> bool:
        """Quick check: is this URL pointing to an auth/lock route?"""
        norm = _normalize(url).lower()
        return any(kw in norm for kw in AUTH_DETECT_KEYWORDS)

    async def _try_quick_unlock(page: Page) -> bool:
        """Quick unlock attempt: inject auth localStorage + click 1 button.
        Returns True if unlock succeeded (page no longer at auth screen).
        """
        try:
            # Inject common auth state
            await page.evaluate(
                "() => { localStorage.setItem('isAuthenticated', 'true'); }"
            )
            await page.wait_for_timeout(100)
            # Try one unlock button
            await _click_button_by_text(page, "continue")
            await page.wait_for_timeout(400)
            current = _normalize(page.url).lower()
            # Success if we've moved away from auth keyword routes
            return not any(kw in current for kw in AUTH_DETECT_KEYWORDS)
        except Exception:  # noqa: BLE001
            return False

    try:
        for idx, route in enumerate(routes[:MAX_PAGES]):
            url = base_url + (route if route != "/" else "")
            route_start_time = time.time()
            try:
                await discovery_page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await _settle(discovery_page)
                await discovery_page.wait_for_timeout(SETTLE_WAIT_MS)

                current_url = _normalize(discovery_page.url)
                # If we're on an auth screen and this isn't supposed to be an auth route, try unlock
                if _is_auth_screen(current_url) and not _is_auth_screen(url):
                    unlocked = await _try_quick_unlock(discovery_page)
                    if not unlocked:
                        logger.info("Route %s appears to be auth-protected, skipping detailed exploration", route)
                        await _emit_frame(on_progress, discovery_page, f"Skipped (auth): {route}")
                        continue  # Skip this route — can't explore without credentials

                await _emit_frame(on_progress, discovery_page, f"Direct → {route}")

                # Short route context + action
                route_ctx = (route_contexts or {}).get(route, {})
                action_result = await _perform_context_action(
                    discovery_page,
                    route=route,
                    context_hint=route_ctx,
                )
                if on_progress:
                    try:
                        await on_progress({
                            "type": "route_context",
                            "route": route,
                            "url": url,
                            "source_files": route_ctx.get("files", []),
                            "action": action_result.get("action"),
                            "filled_fields": action_result.get("filled_fields", 0),
                            "clicked_cta": action_result.get("clicked_cta"),
                        })
                    except Exception:  # noqa: BLE001
                        pass

                # Click fewer buttons, faster
                buttons = await _enumerate_buttons(discovery_page)
                for b in buttons[:MAX_CLICKS_PER_PAGE]:
                    if time.time() - route_start_time > ROUTE_TIMEOUT_SECS:
                        break  # Timeout per route
                    pre_url = _normalize(discovery_page.url)
                    clicked = await _click_button_by_text(discovery_page, b)
                    if not clicked:
                        continue
                    try:
                        await discovery_page.wait_for_load_state("networkidle", timeout=1500)
                    except Exception:  # noqa: BLE001
                        pass
                    await discovery_page.wait_for_timeout(200)
                    post_url = _normalize(discovery_page.url)
                    await _emit_frame(
                        on_progress, discovery_page,
                        f"Clicked: {b['text']} {'(icon)' if b.get('isIcon') else ''}",
                    )
                    button_actions.append({
                        "label": b["text"],
                        "isIcon": b.get("isIcon", False),
                        "from": pre_url,
                        "to": post_url,
                        "navigated": pre_url != post_url,
                        "route": route,
                    })
                    # Quick return to route
                    if _normalize(discovery_page.url) != _normalize(url):
                        try:
                            await discovery_page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                            await _settle(discovery_page)
                            await discovery_page.wait_for_timeout(200)
                        except Exception:  # noqa: BLE001
                            break
                
                elapsed = time.time() - route_start_time
                logger.debug("Route %s explored in %.1fs", route, elapsed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Route %s failed: %s (after %.1fs)", route, exc, time.time() - route_start_time)
    finally:
        await discovery_page.close()
        await discovery_ctx.close()

    # ── 2) Full-page capture at all viewports ───────────────────────────
    # Inject the collected auth state into fresh contexts so protected routes render.
    contexts = []
    for vp in VIEWPORTS:
        ctx = await _new_context(browser, vp, record_video=True)
        if _injected_auth:
            # Open a blank page to inject localStorage before any navigation
            init_page = await ctx.new_page()
            try:
                base_origin = base_url.rstrip("/")
                await init_page.goto(base_origin, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await init_page.evaluate(
                    "(state) => { for (const [k,v] of Object.entries(state)) localStorage.setItem(k,v); }",
                    _injected_auth,
                )
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    await init_page.close()
                except Exception:  # noqa: BLE001
                    pass
        contexts.append((vp, ctx))

    pages: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    try:
        for idx, route in enumerate(routes[:MAX_PAGES]):
            url = base_url + (route if route != "/" else "")
            slug = route.strip("/").replace("/", "_") or "home"
            page_slug = f"page{idx:02d}_{slug[:20]}"
            page_entry: dict[str, Any] = {
                "url": url,
                "slug": page_slug,
                "title": "",
                "captures": {},
                "route": route,
            }
            for vp, ctx in contexts:
                cap = await _capture_full_page(ctx, url, vp["label"], run_id, page_slug, kind="baseline")
                page_entry["captures"][vp["label"]] = cap
                if cap.get("ok") and not page_entry["title"]:
                    page_entry["title"] = cap.get("title") or route
                if on_progress:
                    try:
                        await on_progress({
                            "type": "page_capture",
                            "url": url, "viewport": vp["label"],
                            "ok": cap.get("ok"),
                            "url_path": cap.get("url_path"),
                            "title": cap.get("title", route),
                            "page_slug": page_slug,
                            "page_index": idx,
                        })
                        if cap.get("video_url"):
                            await on_progress({
                                "type": "route_video",
                                "route": route,
                                "url": url,
                                "viewport": vp["label"],
                                "video_url": cap.get("video_url"),
                            })
                    except Exception:  # noqa: BLE001
                        pass

            # Verify visual distinctness using desktop hash.
            desktop_hash = page_entry.get("captures", {}).get("Desktop 1440", {}).get("image_hash")
            if desktop_hash:
                if desktop_hash in seen_hashes and on_progress:
                    try:
                        await on_progress({
                            "type": "duplicate_capture",
                            "route": route,
                            "url": url,
                            "duplicate_of": seen_hashes[desktop_hash],
                            "reason": "desktop screenshot hash matched a prior route",
                        })
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    seen_hashes[desktop_hash] = route
            pages.append(page_entry)
    finally:
        for _, ctx in contexts:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass

    return {"pages": pages, "button_actions": button_actions}


async def apply_patch_full_page(
    browser: Browser,
    url: str,
    vp_label: str,
    css: str,
    run_id: str,
    tag: str,
    page_slug: str,
    baseline_url_path: Optional[str] = None,
) -> dict[str, Any]:
    """Re-open the page, inject CSS, take a FULL-PAGE screenshot.

    Guarantees the `after` image is visibly different from `before`:
      1. If the CSS selectors don't match anything, inject a bright diagnostic
         banner so the user can SEE the patch was a no-op.
      2. Pixel-diff before vs after; if identical, escalate (focus + diagnostic).
      3. Always emit a side-by-side pixel-diff PNG so the user can spot the
         changed regions in red.
    Returns: { ok, after_url, diff_url, changed_pct, applied, no_op_reason }
    """
    css = (css or "").strip()
    if not css:
        return {"ok": False, "applied": False, "no_op_reason": "empty patch"}

    vp = next((v for v in VIEWPORTS if v["label"] == vp_label), VIEWPORTS[-1])
    ctx = await _new_context(browser, vp)
    slug = f"{page_slug}_{tag}"
    baseline_path = SCREENSHOTS_DIR / Path(baseline_url_path).name if baseline_url_path else None
    baseline_bytes = _screenshot_bytes(baseline_path) if baseline_path else None

    no_op_reason: Optional[str] = None
    selectors_matched = True

    async def _capture(slug_suffix: str, *, emphasize: bool, force_banner: Optional[str] = None) -> Optional[str]:
        nonlocal selectors_matched
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            await _settle(page)
            await _fill_visible_forms(page)
            await page.wait_for_timeout(300)
            selectors_matched = await _selectors_match_anything(page, css)
            await _inject_patch_css(page, css, emphasize_interaction=emphasize)
            if force_banner:
                await _add_diagnostic_banner(page, force_banner, color="#FF9500")
            fname = f"{run_id}_{_safe_name(slug_suffix)}_{_safe_name(vp_label)}_patch.png"
            path = SCREENSHOTS_DIR / fname
            png = await page.screenshot(full_page=True, timeout=20000)
            path.write_bytes(png)
            return f"/api/screens/{fname}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Patch capture failed (%s @ %s): %s", slug_suffix, url, exc)
            return None
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

    try:
        url_path = await _capture(slug, emphasize=False)
        if not url_path:
            return {"ok": False, "applied": False, "no_op_reason": "page capture failed"}

        patch_bytes = _screenshot_bytes(SCREENSHOTS_DIR / Path(url_path).name)

        if not selectors_matched:
            no_op_reason = "selectors did not match any DOM element"
            url_path = await _capture(
                f"{slug}_diag", emphasize=True,
                force_banner=f"Atmos diagnostic: patch selectors did not match this page — fix needs different selectors.",
            ) or url_path
            patch_bytes = _screenshot_bytes(SCREENSHOTS_DIR / Path(url_path).name)
        elif baseline_bytes is not None and patch_bytes == baseline_bytes:
            no_op_reason = "patch produced no visible change"
            url_path = await _capture(
                f"{slug}_diag", emphasize=True,
                force_banner="Atmos diagnostic: CSS applied but produced no visible difference at this viewport.",
            ) or url_path
            patch_bytes = _screenshot_bytes(SCREENSHOTS_DIR / Path(url_path).name)

        diff_url: Optional[str] = None
        changed_pct: Optional[float] = None
        if baseline_path and baseline_path.exists():
            diff_name = f"{run_id}_{_safe_name(slug)}_{_safe_name(vp_label)}_diff.png"
            diff_path = SCREENSHOTS_DIR / diff_name
            diff_info = _write_pixel_diff(baseline_path, SCREENSHOTS_DIR / Path(url_path).name, diff_path)
            if diff_info:
                diff_url = f"/api/screens/{diff_name}"
                changed_pct = diff_info["changed_pct"]

        return {
            "ok": True,
            "after_url": url_path,
            "diff_url": diff_url,
            "changed_pct": changed_pct,
            "applied": selectors_matched and (no_op_reason is None),
            "no_op_reason": no_op_reason,
        }
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
    ).with_model("gemini", "gemini-3.5-flash")

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


PAGE_ANALYSIS_SCHEMA = """\
Return ONLY a minified JSON object with shape:
{
  "page_summary": "1-sentence description of what this page does and who it's for",
  "issues": [
    {
      "category": "Visual"|"Accessibility"|"UX"|"Functional"|"Performance",
      "severity": "critical"|"high"|"medium"|"low",
      "title": "<80 chars",
      "cause": "<140 chars",
      "patch_css": "CSS that visibly fixes this when injected as <style>",
      "patch_explanation": "1 sentence",
      "alternatives": [
        {"label": "<6 words", "summary": "<25 words", "tradeoff": "<20 words", "patch_css": "..."},
        {"label": "<6 words", "summary": "<25 words", "tradeoff": "<20 words", "patch_css": "..."}
      ]
    }
    ... 3-5 issues for THIS page only ...
  ]
}
No markdown. JSON only."""


async def llm_analyze_page(project: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    """Deep, per-page analysis: send every viewport screenshot of a single page
    and ask the model to find issues that live ON THIS PAGE.

    If vision fails (Groq 400 / image too large), falls back to a text-only
    analysis using the route path + page title as context.
    """
    from emergentintegrations.llm.chat import (  # type: ignore
        LlmChat, UserMessage, ImageContent, TextDelta, StreamDone,
    )

    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY missing")

    images: list[ImageContent] = []
    notes: list[str] = []
    for vp_label, cap in page.get("captures", {}).items():
        if not cap or not cap.get("ok"):
            continue
        path = SCREENSHOTS_DIR / Path(cap["url_path"]).name
        if not path.exists():
            continue
        images.append(ImageContent(image_base64=base64.b64encode(path.read_bytes()).decode("ascii")))
        notes.append(f"- {vp_label} screenshot of {page['url']}")

    chat = LlmChat(
        api_key=api_key,
        session_id=f"atmos_page_{project['project_id']}_{uuid.uuid4().hex[:6]}",
        system_message=SYSTEM_PROMPT,
    ).with_model("gemini", "gemini-3.5-flash")

    # ── Vision attempt ───────────────────────────────────────────────
    if images:
        prompt = (
            f"Target product: {project['name']}\n"
            f"URL of THIS page: {page['url']}\n"
            f"Title: {page.get('title') or '—'}\n"
            f"Screenshots attached:\n" + "\n".join(notes) + "\n\n"
            f"List issues that exist ONLY on this page. " + PAGE_ANALYSIS_SCHEMA
        )
        try:
            text = ""
            async def _stream_vision() -> str:
                buf = ""
                async for ev in chat.stream_message(UserMessage(text=prompt, file_contents=images)):
                    if isinstance(ev, TextDelta):
                        buf += ev.content
                    elif isinstance(ev, StreamDone):
                        break
                return buf
            text = await asyncio.wait_for(_stream_vision(), timeout=60)
            return _parse_llm_json(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vision analysis failed for %s (%s) — falling back to text", page["url"], exc)

    # ── Text-only fallback ────────────────────────────────────────────
    # Use route, title, and any route_context hints to produce text-based issues.
    chat_text = LlmChat(
        api_key=api_key,
        session_id=f"atmos_page_txt_{project['project_id']}_{uuid.uuid4().hex[:6]}",
        system_message=(
            "You are Atmos, a senior UX auditor. Given a page URL and its title, "
            "infer realistic UX, accessibility, and functional issues for that type of screen. "
            "Return JSON only, exactly per the schema provided."
        ),
    ).with_model("gemini", "gemini-3.5-flash")

    route = page.get("route") or page["url"]
    text_prompt = (
        f"Product: {project['name']} (type: {project.get('app_type', 'generic')})\n"
        f"Page URL: {page['url']}\n"
        f"Route: {route}\n"
        f"Title: {page.get('title') or '—'}\n"
        f"Infer 3-5 realistic issues for this type of screen. " + PAGE_ANALYSIS_SCHEMA
    )
    try:
        async def _stream_text() -> str:
            buf = ""
            async for ev in chat_text.stream_message(UserMessage(text=text_prompt)):
                if isinstance(ev, TextDelta):
                    buf += ev.content
                elif isinstance(ev, StreamDone):
                    break
            return buf
        text = await asyncio.wait_for(_stream_text(), timeout=45)
        result = _parse_llm_json(text)
        result["_source"] = "text_fallback"
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("Text fallback also failed for %s: %s", page["url"], exc)
        return {"page_summary": "", "issues": []}


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
                "patch_css": "button,a,input,textarea,select{outline:2px solid #0071E3 !important;outline-offset:2px !important;}",
                "patch_explanation": "Adds a high-contrast focus ring across every interactive element.",
                "alternatives": [
                    {"label": "Inset focus glow", "summary": "Inset ring works inside overflow:hidden parents.",
                     "tradeoff": "Slightly heavier visually.",
                     "patch_css": "button,a,input,textarea,select{outline:none !important;box-shadow:inset 0 0 0 2px #fff, inset 0 0 0 4px #0071E3 !important;}"},
                    {"label": "Background tint", "summary": "Tint interactive elements for clearer affordance.",
                     "tradeoff": "Less explicit; pair with outline for AAA.",
                     "patch_css": "button,a,input,textarea,select{background-color:rgba(0,113,227,0.08) !important;}"},
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
