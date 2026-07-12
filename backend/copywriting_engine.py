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
    alts: list[dict[str, Any]] = []

    for profile in MARKETING_PROFILES[:4]:
        pid = profile["id"]
        if role == "headline":
            templates = {
                "skeptical_buyer": f"Ship faster with {name} — proven by teams who measure results",
                "busy_professional": f"{name}: the fastest path from idea to live",
                "first_time_visitor": f"{name} helps you test products like a real user",
                "power_user": f"Full-stack UX intelligence for {name} builders",
                "enterprise_buyer": f"Enterprise-grade product testing with audit-ready evidence",
            }
        elif role == "cta":
            templates = {
                "skeptical_buyer": "See a sample report",
                "busy_professional": "Start in 2 min",
                "first_time_visitor": "Try it free",
                "power_user": "Run full audit",
                "enterprise_buyer": "Book a demo",
            }
        elif role == "supporting":
            templates = {
                "skeptical_buyer": f"See before/after diffs, persona scores, and competitive gaps — not vague advice.",
                "busy_professional": f"One run. Clear scores. Fixes you can ship today.",
                "first_time_visitor": f"{name} watches your product like a real user and tells you what to fix.",
                "power_user": f"Crawl, fuzz, funnel analysis, and PR-ready patches in one pipeline.",
                "enterprise_buyer": f"Evidence packs your design, PM, and eng leads can share with leadership.",
            }
        else:
            templates = {
                "skeptical_buyer": f"{text} — with proof",
                "busy_professional": text.split(",")[0][:60],
                "first_time_visitor": f"Simply put: {text[:80]}",
                "power_user": text,
                "enterprise_buyer": f"{text} — built for teams",
            }

        alt_text = templates.get(pid, text)
        alts.append({
            "profile_id": pid,
            "profile_label": profile["label"],
            "text": alt_text,
            "rationale": f"Optimized for {profile['focus']}. Voice: {profile['voice']}. App tone: {voice['tone']}.",
            "marketing_angle": profile["focus"].split(",")[0].strip(),
        })

    return alts


async def _llm_alternatives(
    db,
    user_id: Optional[str],
    block: dict[str, Any],
    project: dict[str, Any],
    app_type: str,
) -> list[dict[str, Any]]:
    try:
        from user_llm_proxy import user_llm_json
    except Exception:  # noqa: BLE001
        return _deterministic_alternatives(block, app_type, project.get("name", ""))

    voice = APP_TYPE_VOICE.get(app_type, APP_TYPE_VOICE["generic"])
    profiles_blob = "\n".join(
        f"- {p['id']}: {p['label']} — {p['focus']} ({p['voice']})" for p in MARKETING_PROFILES
    )
    prompt = (
        f"Product: {project.get('name')} (type: {app_type})\n"
        f"URL: {project.get('url')}\n"
        f"App voice: {voice['tone']}. Avoid: {voice['avoid']}. CTA style: {voice['cta_style']}.\n"
        f"Copy role: {block['role']}\n"
        f"Current text: \"{block['text']}\"\n"
        f"Marketing profiles:\n{profiles_blob}\n\n"
        "You are a senior conversion copywriter. Marketing-first. Return ONLY minified JSON:\n"
        '{"alternatives":[{"profile_id":"...","text":"...","rationale":"≤20 words","marketing_angle":"≤6 words"}]}\n'
        "Give exactly one alternative per profile. Stronger than the original. JSON only."
    )
    uid = user_id or "system"
    try:
        data = await user_llm_json(
            db, uid, prompt,
            system="You are Atmos Copy — marketing-first conversion copywriter. JSON only.",
            session_id=f"copy_{uuid.uuid4().hex[:8]}",
        )
        alts = data.get("alternatives") or []
        if not alts:
            return _deterministic_alternatives(block, app_type, project.get("name", ""))
        # Enrich labels
        by_id = {p["id"]: p for p in MARKETING_PROFILES}
        out = []
        for a in alts:
            pid = a.get("profile_id", "first_time_visitor")
            p = by_id.get(pid, MARKETING_PROFILES[2])
