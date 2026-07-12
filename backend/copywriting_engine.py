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
            const r = el.getBoundingClientRect();
            if (r.width < 8 || r.height < 8) return;
            blocks.push({
              role,
              text: t,
              tag: el.tagName.toLowerCase(),
              above_fold: r.top < window.innerHeight * 0.85,
            });
          };

          const h1 = document.querySelector('h1');
          if (h1) push('headline', h1.innerText, h1);

          document.querySelectorAll('h2').forEach((el, i) => {
            if (i < 4) push('subhead', el.innerText, el);
          });

          const heroP = document.querySelector('main p, [class*="hero"] p, section p');
          if (heroP) push('supporting', heroP.innerText, heroP);

          document.querySelectorAll('a, button, [role=button]').forEach((el) => {
            const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
            if (t.length >= 2 && t.length <= 48) push('cta', t, el);
          });

          document.querySelectorAll('[class*="badge"], [class*="pill"], .tag').forEach((el, i) => {
            if (i < 3) push('badge', el.innerText, el);
          });

          // Deduplicate by text
          const seen = new Set();
          return blocks.filter(b => {
            const k = b.role + '|' + b.text.toLowerCase();
            if (seen.has(k)) return false;
            seen.add(k);
            return true;
          }).slice(0, 24);
        }"""
    )


def _score_copy(text: str, role: str, app_type: str) -> dict[str, Any]:
    """Heuristic marketing score — clarity, length, specificity."""
    words = text.split()
    n = len(words)
    issues = []
    score = 78

    vague = re.compile(
        r"\b(best|amazing|revolutionary|seamless|next-gen|cutting[- ]edge|world[- ]class|synergy|leverage|robust)\b",
        re.I,
    )
    if vague.search(text):
        score -= 12
        issues.append("Contains vague marketing adjectives — prefer concrete outcomes")

    if role == "headline" and n > 14:
        score -= 10
        issues.append("Headline longer than ~14 words — hard to scan")
    if role == "headline" and n < 3:
        score -= 8
        issues.append("Headline too short — missing benefit or audience")

    if role == "cta":
        if n > 5:
            score -= 8
            issues.append("CTA too long — aim for 2–4 words")
        if not re.search(r"\b(get|start|try|buy|book|create|join|open|shop|sign|continue|claim|see)\b", text, re.I):
            score -= 6
            issues.append("CTA lacks a strong action verb")

    if not re.search(r"\d|%|\$|min|hour|day|free|no ", text, re.I) and role in ("headline", "supporting"):
        score -= 5
        issues.append("No specificity (numbers, time, price, free) — weaker conversion")

    if app_type == "finance" and re.search(r"\b(hack|crush|dominate|insane)\b", text, re.I):
        score -= 15
        issues.append("Tone mismatches fintech trust expectations")

    return {"score": max(25, min(98, score)), "issues": issues}


def _deterministic_alternatives(
    block: dict[str, Any],
    app_type: str,
    project_name: str,
) -> list[dict[str, Any]]:
    """Fallback alternatives when LLM unavailable — marketing-first templates."""
    text = block["text"]
    role = block["role"]
    voice = APP_TYPE_VOICE.get(app_type, APP_TYPE_VOICE["generic"])
    name = project_name or "your product"
