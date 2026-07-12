"""Engagement + dark-pattern audit.

Ethical dopamine / engagement suggestions (progress, celebration, first-win)
plus deceptive-design detection (confirmshaming, fake urgency, hidden costs, etc.).

Dark-pattern checks always run when the phase is included.
Engagement "max" suggestions expand when `enable_dopamine_max` is on.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from playwright.async_api import Browser

from atmos_engine import NAV_TIMEOUT_MS, VIEWPORTS, _new_context, _settle

logger = logging.getLogger("atmos.dopamine")

ProgressFn = Callable[[dict[str, Any]], Any]

# Context-tuned ethical engagement patterns
DOPAMINE_PROFILES: dict[str, dict[str, Any]] = {
    "finance": {
        "label": "Fintech engagement",
        "patterns": [
            {"id": "progress_savings", "name": "Savings progress ring", "impact": "high"},
            {"id": "micro_celebration", "name": "Subtle success animation on transfer", "impact": "medium"},
            {"id": "streak_optional", "name": "Optional savings streak (opt-in)", "impact": "low"},
        ],
        "avoid": ["gambling visuals", "slot-machine animations", "fake urgency timers"],
    },
    "e-commerce": {
        "label": "E-commerce delight",
        "patterns": [
            {"id": "cart_bounce", "name": "Add-to-cart micro-feedback", "impact": "high"},
            {"id": "checkout_progress", "name": "3-step checkout progress bar", "impact": "high"},
            {"id": "order_celebration", "name": "Order confirmation delight moment", "impact": "medium"},
        ],
        "avoid": ["infinite scroll without pause", "hidden costs reveal"],
    },
    "dashboard": {
        "label": "SaaS momentum",
        "patterns": [
            {"id": "setup_progress", "name": "Onboarding checklist with % complete", "impact": "high"},
            {"id": "empty_state_action", "name": "Empty state → first win in <60s", "impact": "high"},
            {"id": "milestone_toast", "name": "Milestone toasts (10th project, etc.)", "impact": "medium"},
        ],
        "avoid": ["notification spam", "artificial scarcity"],
    },
    "generic": {
        "label": "General engagement",
        "patterns": [
            {"id": "progress_indicator", "name": "Visible progress on multi-step flows", "impact": "high"},
            {"id": "completion_feedback", "name": "Clear success state after primary action", "impact": "high"},
            {"id": "skeleton_loading", "name": "Skeleton screens vs blank loading", "impact": "medium"},
        ],
        "avoid": ["dark patterns", "misleading CTAs"],
    },
}

DARK_PATTERN_SEVERITY = {
    "critical": 3,
    "high": 2,
    "medium": 1,
    "low": 0,
}


async def _audit_engagement_signals(page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const html = document.body.innerHTML.toLowerCase();
          const text = (document.body.innerText || '').slice(0, 8000);
          const hasProgress = !!document.querySelector('[role=progressbar], progress, .progress, [class*="progress"]');
          const hasSteps = !!document.querySelector('[class*="step"], [data-step], ol.steps, .stepper');
          const hasCelebration = /confetti|celebrat|success|checkmark|done|complete/i.test(html);
          const hasSkeleton = /skeleton|shimmer|placeholder/i.test(html);
          const hasStreak = /streak|day\\s+\\d+|badge/i.test(html);
          const hasEmptyState = /get started|no (items|results|data)|empty/i.test(text.slice(0, 2000));
          const ctaCount = document.querySelectorAll('button, [role=button]').length;
          const formCount = document.querySelectorAll('form').length;
          return { hasProgress, hasSteps, hasCelebration, hasSkeleton, hasStreak, hasEmptyState, ctaCount, formCount };
        }"""
    )


async def _audit_dark_patterns(page) -> list[dict[str, Any]]:
    """Detect common deceptive design patterns in the live DOM."""
    raw = await page.evaluate(
        """() => {
          const text = (document.body.innerText || '');
          const html = document.body.innerHTML || '';
          const lower = text.toLowerCase();
          const findings = [];

          function add(id, name, severity, evidence, recommendation, category) {
            findings.push({ id, name, severity, evidence: String(evidence).slice(0, 160), recommendation, category });
          }

          // Fake urgency / scarcity
          const urgencyRe = /only\\s+\\d+\\s+left|hurry|expires? in|limited time|selling fast|people (are )?viewing|in your cart|offer ends|last chance|act now|almost gone/i;
          if (urgencyRe.test(text)) {
            const m = text.match(urgencyRe);
            add('fake_urgency', 'Fake urgency / scarcity', 'high',
              m ? m[0] : 'urgency language',
              'Remove fabricated countdown/scarcity unless inventory is verified in real time.',
              'urgency');
          }
          if (document.querySelector('[class*="countdown"], [class*="timer"], [data-countdown]')) {
            add('countdown_timer', 'Countdown / expiry timer', 'medium',
              'countdown/timer element in DOM',
              'Ensure timers reflect real offer expiry; never reset on refresh to manufacture pressure.',
              'urgency');
          }

          // Confirmshaming
          const shameRe = /no[, ]? (thanks|i (don.?t|do not) want|i.?ll (pass|skip)|i prefer to (pay|miss)|not interested).*?(miss|lose|poor|dumb|ugly|hate)/i;
          const shameBtns = [...document.querySelectorAll('a, button, [role=button], label')].filter(el => {
            const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
            return /no[, ]thanks|i.?ll pass|skip (this )?offer|not now|maybe later/i.test(t)
              && /miss|lose|don.?t want|prefer to (stay|pay|miss)/i.test(t + ' ' + (el.parentElement?.innerText || '').slice(0, 200));
          });
          if (shameRe.test(text) || shameBtns.length) {
            add('confirmshaming', 'Confirmshaming', 'high',
              shameBtns[0]?.innerText?.trim()?.slice(0, 80) || 'shaming decline copy',
              'Decline paths should be neutral ("No thanks") — not guilt or insult.',
              'confirmshaming');
          }

          // Pre-checked marketing / upsell
          const checkedExtras = [...document.querySelectorAll('input[type=checkbox]')].filter(c => {
            if (!c.checked) return false;
            const label = (c.labels && c.labels[0] ? c.labels[0].innerText : '')
              + ' ' + (c.getAttribute('name') || '') + ' ' + (c.getAttribute('aria-label') || '');
            return /newsletter|marketing|upsell|add.?on|insurance|warranty|donate|share|sms|promo/i.test(label);
          });
          if (checkedExtras.length) {
            add('prechecked_optin', 'Pre-checked opt-in / upsell', 'high',
              checkedExtras[0].name || checkedExtras[0].getAttribute('aria-label') || 'checked box',
              'Marketing and paid add-ons must be opt-in unchecked by default (GDPR / FTC).',
              'forced_action');
          }

          // Hidden costs language
          if (/\\+\\s*(tax|fees|shipping)|taxes?\\s+(and|&)\\s+fees|additional fees|excl\\.?\\s*VAT|price may vary/i.test(text)
              && /checkout|cart|total|pay/i.test(text)) {
            add('hidden_costs', 'Possible hidden costs reveal', 'high',
              'tax/fee language near checkout',
              'Show all-in price before payment CTA; never surprise fees on the last step.',
              'hidden_costs');
          }

          // Misdirection — visually dominant distractor vs primary
          const buttons = [...document.querySelectorAll('button, [role=button], a.btn, input[type=submit]')];
          const primaryLooking = buttons.filter(b => {
            const s = getComputedStyle(b);
            const bg = s.backgroundColor;
            return /rgb\\(0,\\s*113,\\s*227\\)|rgb\\(0,\\s*122,\\s*255\\)|#0071e3|#0a84ff|rgb\\(34,\\s*197,\\s*94\\)/i.test(bg)
              || /primary|cta/i.test(b.className);
          });
          const declineLooking = buttons.filter(b => /no thanks|skip|cancel|not now|decline/i.test(b.innerText || ''));
          if (primaryLooking.length && declineLooking.length) {
            const d = declineLooking[0];
            const ds = getComputedStyle(d);
            if (parseFloat(ds.opacity) < 0.55 || ds.visibility === 'hidden' || ds.fontSize.replace('px','') < 11) {
              add('misdirection', 'Misdirection on decline path', 'medium',
                (d.innerText || '').slice(0, 60),
                'Keep accept and decline equally legible; do not hide the exit.',
                'misdirection');
            }
          }

          // Bait and switch / disguised ads
          if (/sponsored|ad choice|advertisement/i.test(text) === false) {
            const adish = [...document.querySelectorAll('a, button')].filter(el =>
              /download now|install|claim (your )?prize|you.?ve won|free gift/i.test(el.innerText || '')
            );
            if (adish.length) {
              add('disguised_ad', 'Possible disguised ad / bait CTA', 'medium',
                (adish[0].innerText || '').slice(0, 60),
                'Label ads clearly; never style promotions as system UI.',
                'disguised_ads');
            }
          }

          // Roach motel — easy signup language, hard cancel
          if (/sign up in seconds|instant (access|account)|one.?click (signup|join)/i.test(text)
              && !/cancel (anytime|easily)|unsubscribe|manage subscription/i.test(text)) {
            add('roach_motel', 'Easy in / hard out (roach motel signal)', 'medium',
              'easy signup without cancel path copy',
              'Surface cancel/unsubscribe with equal clarity to signup.',
              'obstruction');
          }

          // Forced continuity
          if (/free trial|then\\s+\\$?\\d+|auto.?renew|will be charged|subscription starts/i.test(text)
              && !/cancel before|remind me before charge|no charge until/i.test(text)) {
            add('forced_continuity', 'Forced continuity risk', 'high',
              'trial/auto-renew language',
              'Disclose renewal date, price, and one-click cancel before collecting payment.',
              'forced_continuity');
          }

          // Privacy zuckering — over-broad consent
          if (/by (continuing|clicking|signing).*(agree|accept).*(privacy|terms|cookies|partners|third.?party)/i.test(text)
              && /all (partners|purposes)|share with|sell (your )?data/i.test(text)) {
            add('privacy_zuckering', 'Bundled / coercive privacy consent', 'high',
              'bundled agree-to-everything copy',
              'Separate essential terms from marketing/data-sharing; allow granular consent.',
              'privacy');
          }

          // Trick questions / double negatives in forms
          if (/uncheck.*(if you|to not)|do not uncheck|opt.?out by (un)?checking/i.test(text)) {
            add('trick_question', 'Trick question / confusing opt-out', 'medium',
              'double-negative opt-out copy',
              'Use plain language: checked = yes, unchecked = no.',
              'interface_interference');
          }

          // Social proof that may be fabricated
          if (/\\d+\\s+(people|users|shoppers)\\s+(bought|purchased|viewing)/i.test(text)
              && !/updated|live from/i.test(text)) {
            add('social_proof_pressure', 'Pressure social proof', 'low',
              'N people bought/viewing',
              'If shown, back with real-time verified counts or remove.',
              'urgency');
          }

          return findings;
        }"""
    )
    return list(raw or [])


def _generate_suggestions(
    signals: dict[str, Any],
    app_type: str,
    *,
    engagement_max: bool = False,
) -> list[dict[str, Any]]:
    profile = DOPAMINE_PROFILES.get(app_type, DOPAMINE_PROFILES["generic"])
    suggestions: list[dict[str, Any]] = []

    if not signals.get("hasProgress") and not signals.get("hasSteps"):
        suggestions.append({
            "id": "add_progress",
            "title": "Add visible progress feedback",
            "thesis": "Variable reward + progress visibility increases task completion up to 40% (HCI research).",
            "recommendation": "Add a step indicator or progress bar to multi-step flows.",
            "impact": "high",
            "pattern_ref": "progress_indicator",
            "kind": "engagement",
        })

    if signals.get("formCount", 0) > 0 and not signals.get("hasCelebration"):
        suggestions.append({
            "id": "completion_moment",
            "title": "Missing completion celebration",
            "thesis": "A clear success moment (checkmark, subtle animation) reinforces the reward loop after form submit.",
            "recommendation": "Add a success screen or toast with positive visual feedback after primary conversions.",
            "impact": "high",
            "pattern_ref": "micro_celebration",
            "kind": "engagement",
        })

    if signals.get("hasEmptyState") and signals.get("ctaCount", 0) < 3:
        suggestions.append({
            "id": "empty_first_win",
            "title": "Empty state needs a fast first win",
            "thesis": "Users get a healthy dopamine spike on first accomplishment — guide to one quick action within 60 seconds.",
            "recommendation": "Replace passive empty states with a single prominent 'Create your first X' CTA.",
            "impact": "high",
            "pattern_ref": "empty_state_action",
            "kind": "engagement",
        })

    if not signals.get("hasSkeleton") and signals.get("ctaCount", 0) > 5:
        suggestions.append({
            "id": "skeleton_loading",
            "title": "Add skeleton loading states",
            "thesis": "Perceived wait time drops when users see content-shaped placeholders (skeleton screens).",
            "recommendation": "Use skeleton UI during data fetches instead of spinners or blank screens.",
            "impact": "medium",
            "pattern_ref": "skeleton_loading",
            "kind": "engagement",
        })

    if engagement_max:
        for pat in profile.get("patterns", []):
            pid = pat["id"]
            if not any(s.get("pattern_ref") == pid for s in suggestions):
                suggestions.append({
                    "id": f"pattern_{pid}",
                    "title": f"Consider: {pat['name']}",
                    "thesis": f"Industry pattern for {profile['label']} with {pat['impact']} engagement impact.",
                    "recommendation": f"Implement {pat['name']} tailored to your app's primary conversion flow.",
                    "impact": pat["impact"],
                    "pattern_ref": pid,
                    "kind": "engagement_max",
                })

    return suggestions[:10]


DARK_PATTERN_DISCLAIMER = (
    "DISCLAIMER: The suggestions below describe deceptive design patterns that some "
    "products use to increase conversion. Atmos lists them for competitive awareness "
    "and red-team / ethics review only. Implementing them can harm users, violate "
    "consumer-protection law (e.g. FTC, DSA, GDPR), and damage trust. Prefer ethical "
    "engagement alternatives. Atmos does not recommend shipping these patterns."
)

# Catalog of known dark patterns — suggested when NOT detected on the page.
DARK_PATTERN_CATALOG: list[dict[str, Any]] = [
    {
        "id": "fake_urgency",
        "name": "Fake urgency / scarcity",
        "category": "urgency",
        "conversion_claim": "Scarcity cues often lift short-term conversion 5–15% in e-commerce tests.",
        "how": "Show 'Only N left' or 'Hurry — offer ends' near the CTA (even when inventory is not live).",
        "where": "Product detail, cart, checkout, pricing.",
        "risk": "Illegal if fabricated; trains distrust when users notice resets.",
        "app_types": ["e-commerce", "finance", "generic", "dashboard"],
    },
    {
        "id": "countdown_timer",
        "name": "Countdown / expiry timer",
        "category": "urgency",
        "conversion_claim": "Time pressure increases impulse checkout rates.",
        "how": "Add a ticking timer on a discount that resets on refresh.",
        "where": "Landing hero, checkout banner, modal upsell.",
        "risk": "Deceptive if the expiry is not real.",
        "app_types": ["e-commerce", "generic"],
    },
    {
        "id": "confirmshaming",
        "name": "Confirmshaming",
        "category": "confirmshaming",
        "conversion_claim": "Guilt-framed decline paths raise opt-in rates for newsletters and trials.",
        "how": "Style the decline as 'No thanks, I hate saving money' vs a bright Accept.",
        "where": "Exit-intent modal, trial upgrade, newsletter gate.",
        "risk": "Manipulative; banned in several dark-pattern regulations.",
        "app_types": ["e-commerce", "dashboard", "generic", "finance"],
    },
    {
        "id": "prechecked_optin",
        "name": "Pre-checked opt-in / upsell",
        "category": "forced_action",
        "conversion_claim": "Default-on add-ons and marketing boxes convert passive consent.",
        "how": "Pre-check insurance, newsletter, or SMS boxes on signup/checkout.",
        "where": "Checkout, registration, billing.",
        "risk": "Often unlawful under GDPR; chargebacks and complaints.",
        "app_types": ["e-commerce", "finance", "dashboard", "generic"],
    },
    {
        "id": "hidden_costs",
        "name": "Hidden costs at the last step",
        "category": "hidden_costs",
        "conversion_claim": "Low sticker price increases funnel entry; fees drop out later.",
        "how": "Advertise a low price, reveal tax/shipping/service fees only on payment.",
        "where": "Cart → checkout total.",
        "risk": "FTC / consumer-law exposure; high abandon + support cost.",
        "app_types": ["e-commerce", "finance", "generic"],
    },
    {
        "id": "misdirection",
        "name": "Misdirection (visual hierarchy)",
        "category": "misdirection",
        "conversion_claim": "Making Accept loud and Decline nearly invisible steers clicks.",
        "how": "Primary CTA high-contrast; Skip/No as tiny grey text.",
        "where": "Paywalls, cookie walls, upgrade screens.",
        "risk": "Accessibility + deceptive-design claims.",
        "app_types": ["dashboard", "e-commerce", "generic", "finance"],
    },
    {
        "id": "forced_continuity",
        "name": "Forced continuity (trial → charge)",
