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
    "dashboard": ["Linear", "Notion", "Asana", "Monday.com", "Height"],
    "calendar": ["Calendly", "Cal.com", "Google Calendar"],
    "crypto": ["Phoenix", "Muun", "Breez", "BlueWallet", "Wallet of Satoshi", "Strike"],
    "devtool": ["Cursor", "GitHub Copilot", "Linear", "Vercel", "Railway"],
    "generic": ["Notion", "Stripe", "Linear", "Figma"],
}

VERTICAL_SUBS: dict[str, list[str]] = {
    "finance": ["fintech", "personalfinance", "banking", "Entrepreneur"],
    "e-commerce": ["ecommerce", "shopify", "smallbusiness"],
    "dashboard": ["SaaS", "startups", "ProductManagement", "webdev"],
    "calendar": ["productivity", "getdisciplined"],
    "crypto": ["Bitcoin", "lightningnetwork", "CryptoCurrency", "bitcoin_devs"],
    "devtool": ["cursor", "ChatGPTCoding", "LocalLLaMA", "ExperiencedDevs", "webdev"],
    "generic": ["startups", "SaaS", "webdev", "ProductManagement"],
}


async def _fetch(url: str, *, timeout: float = 18.0, as_json: bool = False) -> Any:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=HEADERS) as client:
        r = await client.get(url)
        if r.status_code >= 400:
            return {} if as_json else ""
        return r.json() if as_json else r.text


def _product_context_blob(
    project: dict[str, Any],
    pages: Optional[list[dict]],
    page_summaries: Optional[list[dict]],
    button_actions: Optional[list[dict]],
) -> str:
    parts = [
        f"name={project.get('name')}",
        f"url={project.get('url')}",
        f"app_type={project.get('app_type')}",
        f"github={project.get('github_owner')}/{project.get('github_repo')}"
        if project.get("github_owner") else "",
    ]
    for p in (pages or [])[:12]:
        parts.append(f"page:{p.get('title') or ''} {p.get('url') or ''}")
    for s in (page_summaries or [])[:8]:
        parts.append(f"summary:{s.get('summary') or ''}")
    for a in (button_actions or [])[:20]:
        parts.append(f"action:{a.get('label') or ''}")
    return "\n".join(x for x in parts if x)[:6000]


def _infer_vertical(project: dict[str, Any], blob: str) -> str:
    """Prefer project.app_type; refine from crawl only when app_type is generic."""
    app_type = (project.get("app_type") or "generic").lower().strip()
    aliases = {
        "fintech": "finance", "payments": "finance", "saas": "dashboard",
        "productivity": "dashboard", "ecommerce": "e-commerce", "shop": "e-commerce",
        "bitcoin": "crypto", "web3": "crypto", "wallet": "crypto",
        "developer": "devtool", "devtools": "devtool",
    }
    if app_type and app_type not in {"generic", "other", "unknown", ""}:
        mapped = aliases.get(app_type, app_type)
        return mapped if mapped in VERTICAL_SUBS else mapped

    b = blob.lower()
    if re.search(r"\b(bitcoin|lightning|satoshi|non[- ]custodial|lnurl|bolt11)\b", b):
        return "crypto"
    if re.search(r"\b(cursor|copilot|claude\s*code|developer\s*tool|sdk)\b", b):
        return "devtool"
    if re.search(r"\b(stripe|payment|fintech|bank|invoice|kyc)\b", b):
        return "finance"
    if re.search(r"\b(shop|cart|checkout|storefront|sku)\b", b):
        return "e-commerce"
    if re.search(r"\b(calendar|scheduling|booking|availability)\b", b):
        return "calendar"
    if re.search(r"\b(dashboard|kanban|sprint|roadmap|workspace)\b", b):
        return "dashboard"
    return "generic"


def _extract_context_terms(blob: str, name: str) -> list[str]:
    stop = {
        "about", "with", "from", "your", "this", "that", "have", "will", "home", "page",
        "https", "http", "www", "com", "app", "apps", "product", "atmos", "summary",
        "action", "title", "name", "url", "type", "github",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", blob or "")
    scored: Counter = Counter()
    name_l = (name or "").lower()
    for w in words:
        wl = w.lower()
        if wl in stop or wl == name_l or wl.isdigit():
            continue
        scored[wl] += 1
    return [w for w, _ in scored.most_common(12)][:8]


def _category_label(vertical: str) -> str:
    return {
        "finance": "fintech / payments",
        "e-commerce": "e-commerce / retail",
        "dashboard": "SaaS / productivity",
        "calendar": "scheduling / calendar",
        "crypto": "crypto / wallets",
        "devtool": "developer tools",
        "generic": "this product category",
    }.get(vertical, vertical.replace("-", " "))


# ── 1) Keyword / research plan ───────────────────────────────────────────────


def _heuristic_research_plan(project: dict[str, Any], vertical: str, blob: str) -> dict[str, Any]:
    """Category + crawl-context keyword plan. Seed peers only; no hard-coded domain essays."""
    name = project.get("name") or urlparse(project.get("url") or "").netloc or "product"
    category = _category_label(vertical)
    competitors = list(VERTICAL_COMPETITORS.get(vertical, VERTICAL_COMPETITORS["generic"]))
    subs = list(VERTICAL_SUBS.get(vertical, VERTICAL_SUBS["generic"]))
    terms = _extract_context_terms(blob, name)
    t0, t1, t2 = (terms + ["onboarding", "pricing", "settings"])[:3]
    c0, c1, c2 = (competitors + ["Notion", "Stripe", "Linear"])[:3]

    framing = (
        f"Research is scoped to {category} around {name}. "
        f"Live crawl signals emphasize: {', '.join(terms[:5]) or 'core product flows'}. "
        f"Peers ({', '.join(competitors[:4])}) often act as the de-facto design reference — "
        f"teams ask what a shipped competitor did more than they run formal research."
    )

    questions = [
        f"How do teams in {category} make design decisions, and what role do designers play?",
        f"How do builders/operators start work on {name}-like products — what is the workflow?",
        f"What resources exist for {category}, and where does the format fail users or AI-assisted workflows?",
        f"What recurring pain points show up around {t0}, {t1}, and {t2}?",
        f"Which {c0}/{c1} patterns is {name} measured against?",
    ]

    keywords = [
        {"query": f'{name} missing OR "I wish" OR "please add" OR frustrating', "intent": "feature", "sources": ["reddit", "github", "google"], "why": f"Direct demand for {name}"},
        {"query": f"{name} vs {c0} OR {c1}", "intent": "design_pattern", "sources": ["reddit", "google"], "why": "Competitive design copying"},
        {"query": f'{c0} review "confusing" OR "broken" OR "hate" {t0}', "intent": "pain", "sources": ["play", "google", "reddit"], "why": f"Peer pain on {t0}"},
        {"query": f"{c1} feature request {t1}", "intent": "feature", "sources": ["github", "reddit"], "why": f"Peer request volume for {t1}"},
        {"query": f"{category} onboarding drop off OR confusing setup", "intent": "pain", "sources": ["reddit", "google"], "why": "Activation friction"},
        {"query": f"{c0} vs {c1} UX {t2}", "intent": "design_pattern", "sources": ["reddit", "google"], "why": "De-facto pattern comparison"},
        {"query": f"{name} alternative 2025 OR 2026", "intent": "feature", "sources": ["reddit", "google"], "why": "Switching intent"},
        {"query": f'{category} "without a designer" OR copied UX OR "design system"', "intent": "workflow", "sources": ["reddit"], "why": "How design decisions get made"},
        {"query": f'{t0} {t1} "how do I" {name}', "intent": "pain", "sources": ["reddit", "google"], "why": "Support-shaped language"},
        {"query": f'{c2} pricing OR "too expensive" OR fees review', "intent": "pain", "sources": ["play", "reddit"], "why": "Monetization / trust friction"},
    ]
    for term in terms[:4]:
        keywords.append({
            "query": f"{term} UX OR confusing OR missing {c0}",
            "intent": "pain",
            "sources": ["reddit", "google", "github"],
            "why": f"Live crawl term: {term}",
        })

    return {
        "domain_framing": framing,
        "research_questions": questions,
        "vertical": vertical,
        "category": category,
        "competitors": competitors,
        "subreddits": subs,
        "context_terms": terms,
        "keywords": keywords[:14],
        "github_queries": [
            f"{name} feature request is:issue",
            f'{name} "would be nice" OR missing OR confusing is:issue',
            f"{c0} {t0} is:issue",
            f"{c1} enhancement label:enhancement",
        ],
        "play_queries": [f"{c} app" for c in competitors[:5]] + [name],
        "google_queries": [
            f'{c} app review "I wish" OR "please add" OR missing OR confusing'
            for c in competitors[:4]
        ] + [f"{name} review missing feature"],
        "planner": "heuristic",
        "planned_at": datetime.now(timezone.utc).isoformat(),
    }


async def plan_research_keywords(
    project: dict[str, Any],
    *,
    blob: str,
    vertical: str,
    db=None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """LLM plans product/category-specific keywords; heuristic uses crawl context."""
    base = _heuristic_research_plan(project, vertical, blob)
    if not db or not user_id:
        return base

    try:
        from user_llm_proxy import user_llm_json

        prompt = f"""Plan scraping keywords for THIS product only.

Product / crawl context:
{blob[:4500]}

Declared category: {vertical} ({base.get('category')})
Seed peers (replace if wrong): {base['competitors']}
Seed subreddits (replace if wrong): {base['subreddits']}
Context terms from crawl: {base.get('context_terms')}

QUALITY BAR = research depth (archetypes, workflows, design-decision patterns, resource format gaps, numbered pains).
That bar is structural — do NOT inject Bitcoin/Lightning/crypto content unless this product is actually in that category.

Return STRICT JSON:
{{
  "domain_framing": "2-4 sentences on structural dynamics of THIS product's category",
  "research_questions": ["4-6 deep questions scoped to this product/category"],
  "competitors": ["5-8 real peers for THIS product"],
  "subreddits": ["4-8 relevant subs without r/"],
  "keywords": [
    {{
      "query": "specific search using product name, peers, and crawl jargon",
      "intent": "pain|feature|workflow|archetype|resource|design_pattern",
      "sources": ["reddit","github","play","google"],
      "why": "why this query matters for this product"
    }}
  ],
  "github_queries": ["3-6 GitHub search strings"],
  "play_queries": ["relevant Play app names"],
  "google_queries": ["review search strings"]
}}

Rules: 8-14 specific keywords; never unrelated vertical jargon; never generic-only queries like bare "feature request".
"""
        planned = await user_llm_json(
            db, user_id, prompt,
            system="Plan high-signal, product-specific research queries. JSON only.",
            session_id="demand-plan",
        )
        if not isinstance(planned, dict) or not planned.get("keywords"):
            return base
        merged = {**base, **{k: planned[k] for k in planned if planned[k]}, "planner": "llm"}
        merged["keywords"] = (planned.get("keywords") or base["keywords"])[:14]
        merged["category"] = base.get("category")
        merged["context_terms"] = base.get("context_terms")
        return merged
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword planner LLM failed: %s", exc)
        return base


# ── 2) Scrapers ──────────────────────────────────────────────────────────────


def _evidence(
    *,
    source: str,
    text: str,
    url: Optional[str] = None,
    weight: int = 1,
    meta: Optional[dict] = None,
) -> dict[str, Any]:
    text = (text or "").strip()
    return {
        "source": source,
        "text": text[:1200],
        "snippet": text[:220].replace("\n", " "),
        "url": url,
        "weight": max(1, min(25, weight)),
        "feature_ids": [fid for fid, pat in FEATURE_PATTERNS if pat.search(text)],
        **(meta or {}),
    }


async def _reddit_comments(permalink: str, limit: int = 8) -> list[str]:
    if not permalink:
        return []
    path = permalink if permalink.endswith(".json") else permalink.rstrip("/") + ".json"
    if not path.startswith("http"):
        path = "https://www.reddit.com" + path
    try:
        data = await _fetch(path, as_json=True)
        if not isinstance(data, list) or len(data) < 2:
            return []
        comments = []
        for child in ((data[1].get("data") or {}).get("children") or [])[:limit]:
            body = ((child.get("data") or {}).get("body")) or ""
            if len(body) > 40:
                comments.append(body)
        return comments
    except Exception:  # noqa: BLE001
        return []


async def scrape_reddit_research(plan: dict[str, Any], limit_posts: int = 35) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    subs = plan.get("subreddits") or VERTICAL_SUBS["generic"]
    kw_items = [k for k in (plan.get("keywords") or []) if "reddit" in (k.get("sources") or ["reddit"])]
    queries = [k["query"] for k in kw_items] or [k["query"] for k in plan.get("keywords") or []]

    for sub in subs[:5]:
        for q in queries[:6]:
            url = (
                f"https://www.reddit.com/r/{sub}/search.json"
                f"?q={quote_plus(q)}&restrict_sr=1&sort=relevance&t=year&limit=12"
            )
            try:
                data = await _fetch(url, as_json=True)
                children = (data.get("data") or {}).get("children") or []
                for child in children:
                    post = child.get("data") or {}
