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
