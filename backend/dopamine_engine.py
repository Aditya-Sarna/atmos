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
