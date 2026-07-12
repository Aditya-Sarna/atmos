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
