"""UI/UX reference engine — Mobbin & Pinterest pattern library for fix suggestions."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger("atmos.references")

# Curated industry benchmarks from public UX teardowns (Mobbin-style patterns)
SEED_REFERENCES: list[dict[str, Any]] = [
    {"source": "mobbin", "category": "checkout", "app": "Stripe", "pattern": "Single-page checkout with inline card validation",
     "image_url": "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?w=400", "tags": ["finance", "e-commerce"]},
    {"source": "mobbin", "category": "checkout", "app": "Shopify", "pattern": "3-click path: product → cart → checkout with persistent summary",
     "image_url": "https://images.unsplash.com/photo-1472851294607-062f824d29cc?w=400", "tags": ["e-commerce"]},
    {"source": "mobbin", "category": "onboarding", "app": "Linear", "pattern": "Progressive disclosure — one action per screen with skip option",
     "image_url": "https://images.unsplash.com/photo-1611224923853-80b023f02d71?w=400", "tags": ["dashboard", "generic"]},
    {"source": "mobbin", "category": "navigation", "app": "Notion", "pattern": "Sidebar + command palette (⌘K) for power users",
     "image_url": "https://images.unsplash.com/photo-1635776062127-d379bfcba9f8?w=400", "tags": ["dashboard"]},
    {"source": "mobbin", "category": "accessibility", "app": "Apple", "pattern": "44pt minimum touch targets, Dynamic Type support",
     "image_url": "https://images.unsplash.com/photo-1512941937669-90a1b58e7e9c?w=400", "tags": ["generic"]},
    {"source": "mobbin", "category": "forms", "app": "Airbnb", "pattern": "Floating labels, inline validation, clear error recovery",
     "image_url": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=400", "tags": ["e-commerce", "generic"]},
    {"source": "pinterest", "category": "cta", "app": "Pinterest UI", "pattern": "High-contrast primary button with 16px+ label, 48px height",
     "image_url": "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=400", "tags": ["generic"]},
    {"source": "pinterest", "category": "mobile", "app": "Mobile UX", "pattern": "Bottom navigation for thumb reach, sticky primary CTA",
     "image_url": "https://images.unsplash.com/photo-1512941937669-90a1b58e7e9c?w=400", "tags": ["e-commerce", "generic"]},
    {"source": "mobbin", "category": "elderly", "app": "Health apps", "pattern": "Large type (18px+), high contrast, single-column layout",
     "image_url": "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=400", "tags": ["generic"]},
    {"source": "mobbin", "category": "empty_state", "app": "Figma", "pattern": "Illustration + headline + single CTA for empty states",
     "image_url": "https://images.unsplash.com/photo-1611224923853-80b023f02d71?w=400", "tags": ["dashboard", "generic"]},
]

ISSUE_TO_CATEGORIES: dict[str, list[str]] = {
    "Accessibility": ["accessibility", "forms", "elderly"],
    "UX": ["navigation", "onboarding", "cta", "empty_state"],
    "Visual": ["cta", "mobile"],
    "Functional": ["forms", "checkout"],
    "Performance": ["mobile"],
}


async def _fetch_html(url: str, timeout: float = 12.0) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        r = await client.get(url)
        if r.status_code >= 400:
            return ""
        return r.text


def _parse_mobbin_html(html: str, limit: int = 8) -> list[dict[str, Any]]:
    """Extract pattern titles from Mobbin public pages (best-effort)."""
    refs: list[dict[str, Any]] = []
    # Mobbin uses meta tags and structured data on public flow pages
    for m in re.finditer(r'<meta\s+property="og:title"\s+content="([^"]+)"', html):
        title = m.group(1).strip()
        if len(title) > 5:
            refs.append({
                "source": "mobbin",
                "category": "flow",
                "app": "Mobbin",
                "pattern": title,
                "image_url": None,
                "tags": ["generic"],
            })
    for m in re.finditer(r'alt="([^"]{10,120})"', html):
        alt = m.group(1).strip()
        if "screenshot" in alt.lower() or "flow" in alt.lower() or "screen" in alt.lower():
            refs.append({
                "source": "mobbin",
                "category": "screen",
                "app": "Mobbin",
                "pattern": alt,
                "image_url": None,
                "tags": ["generic"],
            })
        if len(refs) >= limit:
            break
    return refs[:limit]


def _parse_pinterest_html(html: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Extract pin descriptions from Pinterest search HTML."""
    refs: list[dict[str, Any]] = []
    for m in re.finditer(r'"description":"([^"]{15,200})"', html):
        desc = m.group(1).encode().decode("unicode_escape") if "\\u" in m.group(1) else m.group(1)
        refs.append({
            "source": "pinterest",
            "category": query.replace(" ", "_"),
            "app": "Pinterest",
            "pattern": desc,
            "image_url": None,
            "tags": [query.split()[0] if query else "generic"],
        })
        if len(refs) >= limit:
            break
    # Fallback: og descriptions
    if not refs:
        for m in re.finditer(r'content="([^"]{20,180})"\s+property="og:description"', html):
            refs.append({
                "source": "pinterest",
                "category": query.replace(" ", "_"),
                "app": "Pinterest",
                "pattern": m.group(1),
                "image_url": None,
                "tags": ["generic"],
            })
            if len(refs) >= limit:
                break
    return refs[:limit]


async def scrape_mobbin_patterns(category: str = "checkout", limit: int = 6) -> list[dict[str, Any]]:
    """Scrape Mobbin public content; fall back to seed library."""
    urls = [
        f"https://mobbin.com/search/apps/web?query={quote_plus(category)}",
        "https://mobbin.com/browse/ios/apps",
    ]
    scraped: list[dict[str, Any]] = []
    for url in urls:
        try:
            html = await _fetch_html(url)
            if html:
                scraped.extend(_parse_mobbin_html(html, limit))
        except Exception as exc:  # noqa: BLE001
            logger.debug("mobbin scrape failed %s: %s", url, exc)
        if len(scraped) >= limit:
            break

    if not scraped:
        scraped = [r for r in SEED_REFERENCES if r["source"] == "mobbin" and (
            category in r.get("category", "") or category in " ".join(r.get("tags", []))
        )][:limit]
    if not scraped:
        scraped = [r for r in SEED_REFERENCES if r["source"] == "mobbin"][:limit]

    for r in scraped:
        r["ref_id"] = f"ref_{uuid.uuid4().hex[:8]}"
        r["scraped_at"] = datetime.now(timezone.utc).isoformat()
    return scraped


async def scrape_pinterest_patterns(query: str = "mobile app ui design", limit: int = 6) -> list[dict[str, Any]]:
    """Scrape Pinterest search; fall back to seed library."""
    url = f"https://www.pinterest.com/search/pins/?q={quote_plus(query)}"
    scraped: list[dict[str, Any]] = []
    try:
        html = await _fetch_html(url)
        if html:
            scraped = _parse_pinterest_html(html, query, limit)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pinterest scrape failed: %s", exc)

    if not scraped:
        scraped = [dict(r) for r in SEED_REFERENCES if r["source"] == "pinterest"][:limit]

    for r in scraped:
        r["ref_id"] = r.get("ref_id") or f"ref_{uuid.uuid4().hex[:8]}"
        r["scraped_at"] = datetime.now(timezone.utc).isoformat()
    return scraped


async def ensure_reference_cache(db, app_type: str = "generic") -> list[dict[str, Any]]:
    """Populate Mongo cache if stale (>24h) or empty."""
    cache_key = f"refs_{app_type}"
    cached = await db.ui_references.find_one({"cache_key": cache_key}, {"_id": 0})
    if cached and cached.get("references"):
