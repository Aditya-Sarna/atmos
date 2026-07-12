"""Marketing-first copywriting engine — app-context + user-profile alternatives.

Extracts live messaging from the product, then proposes alternative phrasings
optimized for conversion, clarity, and persona fit (marketing first).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Callable, Optional

from playwright.async_api import Browser, Page

from atmos_engine import NAV_TIMEOUT_MS, VIEWPORTS, _new_context, _settle

logger = logging.getLogger("atmos.copywriting")

ProgressFn = Callable[[dict[str, Any]], Any]

# Marketing-first user profiles (not just a11y personas)
MARKETING_PROFILES: list[dict[str, Any]] = [
    {
        "id": "skeptical_buyer",
        "label": "Skeptical Buyer",
        "focus": "Proof, risk reversal, concrete outcomes",
        "voice": "specific numbers, social proof, no hype",
    },
    {
        "id": "busy_professional",
        "label": "Busy Professional",
        "focus": "Speed, time saved, one clear action",
        "voice": "short verbs, outcome in ≤8 words",
    },
    {
        "id": "first_time_visitor",
        "label": "First-Time Visitor",
        "focus": "Clarity, jargon-free, what / for whom / why now",
        "voice": "plain language, benefit before feature",
    },
    {
        "id": "power_user",
        "label": "Power User / Champion",
        "focus": "Capability, control, advanced value",
        "voice": "precise, technical-ok, efficiency cues",
    },
    {
        "id": "enterprise_buyer",
        "label": "Enterprise Buyer",
        "focus": "Trust, compliance, ROI, team scale",
        "voice": "credible, calm, security & outcomes",
    },
]

APP_TYPE_VOICE: dict[str, dict[str, str]] = {
    "finance": {
        "tone": "trustworthy, precise, calm",
        "avoid": "hype, slang, urgency gimmicks",
        "cta_style": "Start free · Get started · Open account",
    },
    "e-commerce": {
        "tone": "benefit-led, scannable, confident",
        "avoid": "vague adjectives without proof",
        "cta_style": "Shop now · Add to cart · Buy",
    },
    "dashboard": {
        "tone": "product-led, efficient, clear hierarchy",
        "avoid": "marketing fluff on empty states",
        "cta_style": "Create · Invite · Get started",
    },
    "calendar": {
        "tone": "simple, time-aware, low friction",
        "avoid": "long explanations before booking",
        "cta_style": "Book · Schedule · Confirm",
    },
    "generic": {
        "tone": "clear, benefit-first, human",
        "avoid": "jargon, empty superlatives",
        "cta_style": "Get started · Try free · Learn more",
    },
}


async def _extract_copy_blocks(page: Page) -> list[dict[str, Any]]:
    """Pull hero, CTAs, headlines, and key marketing strings from the live DOM."""
    return await page.evaluate(
        """() => {
          const blocks = [];
          const push = (role, text, el) => {
            const t = (text || '').replace(/\\s+/g, ' ').trim();
            if (t.length < 2 || t.length > 280) return;
