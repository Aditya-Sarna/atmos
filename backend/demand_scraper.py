"""Research-grade demand intelligence.

Pipeline:
  1) Plan specific keywords / research questions for *this* product today
  2) Scrape Reddit (posts + comments), GitHub issues, Google/Play review signals
  3) Cluster evidence into themes (not generic regex buckets alone)
  4) LLM-orchestrate detailed insight .md briefs (ecosystem, workflows, pain, features)

Quality bar: structural insights, builder archetypes, workflow phases, and proposed
features with decision rules / anti-patterns — not a shallow S/A/B/C laundry list.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote_plus, urlparse

import httpx

logger = logging.getLogger("atmos.demand")

ProgressFn = Callable[[dict[str, Any]], Any]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

REPORTS_DIR = Path(os.environ.get(
    "ATMOS_REPORTS_DIR",
    str(Path(__file__).resolve().parent / "reports"),
))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Legacy regex buckets kept as secondary classifiers after theme clustering
FEATURE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("dark_mode", re.compile(r"\bdark\s*mode\b|\bdark\s*theme\b", re.I)),
    ("offline_mode", re.compile(r"\boffline\b|\bno\s*internet\b", re.I)),
    ("export_pdf", re.compile(r"\bexport\b.*\b(pdf|csv|excel)\b|\bdownload\s*report\b", re.I)),
    ("sso_login", re.compile(r"\b(sso|saml|okta|single\s*sign)\b", re.I)),
    ("mobile_app", re.compile(r"\b(ios|android|mobile\s*app|native\s*app)\b", re.I)),
    ("api_access", re.compile(r"\b(public\s*api|api\s*access|webhooks?)\b", re.I)),
    ("integrations", re.compile(r"\b(integrat|slack|jira|zapier|notion|linear)\b", re.I)),
    ("notifications", re.compile(r"\b(push\s*notif|email\s*alert|reminders?)\b", re.I)),
    ("collaboration", re.compile(r"\b(collab|share\s*with|team\s*workspace|invite)\b", re.I)),
    ("search", re.compile(r"\b(global\s*search|better\s*search|⌘k|cmd\s*k)\b", re.I)),
    ("accessibility", re.compile(r"\b(a11y|screen\s*reader|accessibility|wcag)\b", re.I)),
    ("performance", re.compile(r"\b(slow|lag|performance|loading\s*forever)\b", re.I)),
    ("pricing_clarity", re.compile(r"\b(pricing|too\s*expensive|free\s*tier|hidden\s*fees)\b", re.I)),
    ("onboarding", re.compile(r"\b(onboarding|getting\s*started|confusing\s*setup)\b", re.I)),
    ("checkout_ux", re.compile(r"\b(checkout|cart|payment\s*failed|one[- ]click)\b", re.I)),
    ("analytics", re.compile(r"\b(analytics|dashboard|insights|metrics)\b", re.I)),
    ("ai_features", re.compile(r"\b(ai\s*(feature|assist|suggest|coding)|chatgpt|claude|copilot|vibe\s*cod)\b", re.I)),
    ("multi_language", re.compile(r"\b(i18n|localization|translate|multi[- ]language)\b", re.I)),
    ("undo_history", re.compile(r"\b(undo|version\s*history|rollback)\b", re.I)),
    ("templates", re.compile(r"\btemplates?\b", re.I)),
    ("docs_for_ai", re.compile(r"\b(context\s*window|system\s*prompt|decision\s*rules|anti[- ]patterns?|bolts?)\b", re.I)),
    ("self_custody", re.compile(r"\b(self[- ]custody|seed\s*phrase|recovery\s*phrase|non[- ]custodial)\b", re.I)),
    ("design_system", re.compile(r"\b(design\s*system|ux\s*pattern|what\s+did\s+\w+\s+do|copied\s+from)\b", re.I)),
]

FEATURE_LABELS: dict[str, str] = {
    "dark_mode": "Dark mode / theme",
    "offline_mode": "Offline mode",
    "export_pdf": "Export (PDF/CSV)",
    "sso_login": "SSO / enterprise login",
    "mobile_app": "Native mobile app",
    "api_access": "Public API / webhooks",
    "integrations": "Third-party integrations",
    "notifications": "Smart notifications",
    "collaboration": "Team collaboration",
    "search": "Powerful search / command palette",
    "accessibility": "Accessibility improvements",
    "performance": "Performance & speed",
    "pricing_clarity": "Clearer pricing / free tier",
    "onboarding": "Simpler onboarding",
    "checkout_ux": "Checkout / payment UX",
    "analytics": "Analytics & insights",
    "ai_features": "AI-native development / assist",
    "multi_language": "Multi-language support",
    "undo_history": "Undo / version history",
    "templates": "Templates library",
    "docs_for_ai": "AI-consumable docs / constraint packs",
    "self_custody": "Self-custody / recovery clarity",
    "design_system": "Domain design patterns / de-facto systems",
}

VERTICAL_COMPETITORS: dict[str, list[str]] = {
    "finance": ["Stripe", "Wise", "Revolut", "Cash App", "PayPal", "Brex"],
    "e-commerce": ["Shopify", "Amazon", "Etsy", "BigCommerce"],
