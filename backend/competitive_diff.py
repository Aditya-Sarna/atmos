"""Competitive side-by-side UX diff — your app vs Stripe/Shopify with annotated patterns."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.async_api import Browser

from atmos_engine import NAV_TIMEOUT_MS, SCREENSHOTS_DIR, VIEWPORTS, _new_context, _safe_name, _settle

logger = logging.getLogger("atmos.competitive")

ProgressFn = Callable[[dict[str, Any]], Any]

COMPETITOR_PAGES: dict[str, list[dict[str, Any]]] = {
    "e-commerce": [
        {
            "name": "Shopify",
            "url": "https://www.shopify.com/",
            "flow": "checkout",
            "patterns": [
                "Persistent cart summary on checkout",
                "Trust badges adjacent to payment CTA",
                "3-click product → cart → pay path",
                "High-contrast primary CTA (48px height)",
            ],
        },
        {
            "name": "Stripe",
            "url": "https://stripe.com/payments",
            "flow": "payments",
            "patterns": [
                "Minimal form — only essential fields visible",
                "Inline validation with calm error copy",
                "Single accent color on white/neutral base",
                "Progressive disclosure for advanced options",
            ],
        },
    ],
    "finance": [
        {
            "name": "Stripe",
            "url": "https://stripe.com/payments",
            "flow": "payments",
            "patterns": [
                "Trust-first layout — security cues above fold",
                "Monochrome + one accent blue",
                "Dense but scannable 8px grid",
            ],
        },
        {
            "name": "Wise",
            "url": "https://wise.com/",
            "flow": "transfer",
            "patterns": [
                "Real-time fee transparency before confirm",
                "Large numeric amounts with clear currency",
                "Step-by-step transfer wizard",
            ],
        },
    ],
    "dashboard": [
        {
            "name": "Linear",
            "url": "https://linear.app/",
            "flow": "onboarding",
            "patterns": ["Keyboard-first navigation", "Minimal chrome", "Instant feedback on actions"],
        },
        {
            "name": "Notion",
            "url": "https://www.notion.so/product",
            "flow": "workspace",
            "patterns": ["Empty state with template gallery", "Sidebar + content split", "Slash commands"],
        },
    ],
    "generic": [
        {
            "name": "Stripe",
            "url": "https://stripe.com/",
            "flow": "landing",
            "patterns": ["Hero + single primary CTA", "Social proof logos", "Clear value prop in <8 words"],
        },
        {
            "name": "Apple",
            "url": "https://www.apple.com/",
            "flow": "product",
            "patterns": ["Full-bleed imagery", "Generous whitespace", "One message per viewport"],
        },
    ],
}


async def _capture_page(browser: Browser, url: str, run_id: str, slug: str) -> Optional[str]:
    vp = VIEWPORTS[-1]
    ctx = await _new_context(browser, vp)
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        await _settle(page)
        name = f"{run_id}_{_safe_name(slug)}.png"
        path = SCREENSHOTS_DIR / name
        await page.screenshot(path=str(path), full_page=False)
        return f"/api/screens/{name}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("competitive capture failed %s: %s", url, exc)
        return None
    finally:
        await ctx.close()


def _stitch_side_by_side(yours_path: Path, theirs_path: Path, out_path: Path, labels: tuple[str, str]) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    try:
        img_a = Image.open(yours_path).convert("RGB")
        img_b = Image.open(theirs_path).convert("RGB")
        h = max(img_a.height, img_b.height)
        w = max(img_a.width, img_b.width)
        img_a = img_a.resize((w, h))
        img_b = img_b.resize((w, h))
        composite = Image.new("RGB", (w * 2 + 20, h + 40), (245, 245, 247))
        composite.paste(img_a, (0, 40))
        composite.paste(img_b, (w + 20, 40))
        draw = ImageDraw.Draw(composite)
        draw.text((10, 10), labels[0], fill=(29, 29, 31))
        draw.text((w + 30, 10), labels[1], fill=(0, 113, 227))
        draw.line([(w + 10, 40), (w + 10, h + 40)], fill=(200, 200, 200), width=2)
        composite.save(out_path, "PNG")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("stitch failed: %s", exc)
        return False


async def _compare_patterns(
    your_url: str,
    competitor: dict[str, Any],
    your_page_url: str,
    *,
    db=None,
    user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Judge which competitor patterns appear missing — LLM when available, else heuristic."""
    patterns = competitor.get("patterns") or []
    if db and user_id and patterns:
        try:
            from user_llm_proxy import user_llm_json
            data = await user_llm_json(
                db,
                user_id,
                (
                    f"Your product URL: {your_page_url or your_url}\n"
                    f"Competitor: {competitor.get('name')} ({competitor.get('url')})\n"
                    f"Flow: {competitor.get('flow')}\n"
                    f"Patterns to judge:\n- " + "\n- ".join(patterns)
                ),
                system=(
                    "You are a senior product designer comparing two products. "
                    "For each competitor pattern, say if the user's product likely has it, "
                    "is missing it, or needs review. Return JSON: "
                    '{"annotations":[{"pattern":"...","status":"present|missing|review","note":"..."}]}'
                ),
            )
