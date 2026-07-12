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
                    title = post.get("title") or ""
                    body = post.get("selftext") or ""
                    blob = f"{title}\n{body}"
                    score = int(post.get("score") or 0)
                    comments_n = int(post.get("num_comments") or 0)
                    weight = max(2, min(22, score // 8 + comments_n // 4 + 2))
                    permalink = post.get("permalink") or ""
                    evidence.append(_evidence(
                        source="reddit",
                        text=blob,
                        url=f"https://reddit.com{permalink}",
                        weight=weight,
                        meta={
                            "subreddit": sub,
                            "query": q,
                            "score": score,
                            "comments": comments_n,
                            "intent": next((k.get("intent") for k in kw_items if k.get("query") == q), None),
                        },
                    ))
                    # Deep comments on high-signal threads
                    if score >= 15 or comments_n >= 10:
                        for cbody in await _reddit_comments(permalink, limit=6):
                            evidence.append(_evidence(
                                source="reddit_comment",
                                text=cbody,
                                url=f"https://reddit.com{permalink}",
                                weight=max(1, min(10, weight // 2)),
                                meta={"subreddit": sub, "query": q, "parent_score": score},
                            ))
                    if len(evidence) >= limit_posts * 4:
                        return evidence
            except Exception as exc:  # noqa: BLE001
                logger.debug("reddit research failed %s %s: %s", sub, q, exc)
    return evidence


async def scrape_github_research(plan: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    queries = list(plan.get("github_queries") or [])
    owner, repo = project.get("github_owner"), project.get("github_repo")
    if owner and repo:
        queries = [
            f"repo:{owner}/{repo} is:issue label:enhancement",
            f"repo:{owner}/{repo} is:issue \"feature request\" OR missing OR confusing",
        ] + queries

    headers = dict(HEADERS)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for q in queries[:5]:
        url = f"https://api.github.com/search/issues?q={quote_plus(q)}&sort=reactions&order=desc&per_page=25"
        try:
            async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
                r = await client.get(url)
                if r.status_code >= 400:
                    continue
                data = r.json()
            for item in data.get("items") or []:
                blob = f"{item.get('title', '')}\n{item.get('body') or ''}"
                reactions = ((item.get("reactions") or {}).get("total_count")) or 0
                comments = int(item.get("comments") or 0)
                weight = max(2, min(20, reactions * 2 + comments // 2 + 2))
                evidence.append(_evidence(
                    source="github",
                    text=blob,
                    url=item.get("html_url"),
                    weight=weight,
                    meta={
                        "reactions": reactions,
                        "comments": comments,
                        "query": q,
                        "state": item.get("state"),
                    },
                ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("github research failed: %s", exc)
    return evidence


async def scrape_play_and_google(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Play listing + Google review snippet scrape (best-effort; bots get blocked often)."""
    evidence: list[dict[str, Any]] = []

    for name in (plan.get("play_queries") or plan.get("competitors") or [])[:5]:
        play_search = f"https://play.google.com/store/search?q={quote_plus(name)}&c=apps&hl=en"
        try:
            html = await _fetch(play_search)
            # Extract app detail hrefs
            ids = re.findall(r"id=([a-zA-Z0-9_.]+)", html or "")
            # Prefer unique package ids
            seen = []
            for pid in ids:
                if pid not in seen and "." in pid:
                    seen.append(pid)
                if len(seen) >= 2:
                    break
            for pid in seen[:2]:
                detail = await _fetch(
                    f"https://play.google.com/store/apps/details?id={quote_plus(pid)}&hl=en&gl=us"
                )
                # Reviews / description chunks
                chunks = re.findall(r">([^<]{50,280})<", detail or "")
                desc = ""
                m = re.search(r'itemprop="description"[^>]*>.*?<div[^>]*>(.*?)</div>', detail or "", re.S | re.I)
                if m:
                    desc = re.sub(r"<[^>]+>", " ", m.group(1))
                if desc:
                    evidence.append(_evidence(
                        source="play_store",
                        text=f"{name} ({pid}): {desc}",
                        url=f"https://play.google.com/store/apps/details?id={pid}",
                        weight=3,
                        meta={"competitor": name, "package": pid},
                    ))
                reviewish = [
                    t for t in chunks
                    if re.search(r"\b(wish|please|missing|add|hate|love|bug|crash|confusing|slow|fee|login)\b", t, re.I)
                ]
                for t in reviewish[:12]:
                    evidence.append(_evidence(
                        source="play_store",
                        text=t,
                        url=f"https://play.google.com/store/apps/details?id={pid}",
                        weight=2,
                        meta={"competitor": name, "package": pid},
                    ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("play scrape failed %s: %s", name, exc)

    for q in (plan.get("google_queries") or [])[:5]:
        url = f"https://www.google.com/search?q={quote_plus(q)}&hl=en&num=12"
        try:
            html = await _fetch(url)
            texts = re.findall(r">([^<]{45,240})<", html or "")
            for t in texts[:25]:
                if re.search(r"feature|missing|wish|add|need|slow|bug|confusing|review|fee|login|crash|price", t, re.I):
                    evidence.append(_evidence(
                        source="google_reviews",
                        text=t,
                        weight=2,
                        meta={"query": q},
                    ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("google scrape failed: %s", exc)

    return evidence


# ── 3) Theme clustering + tier list ──────────────────────────────────────────


def _cluster_themes(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster by feature_ids + lightweight keyword stems from evidence."""
    buckets: dict[str, dict[str, Any]] = {}

    for ev in evidence:
        ids = ev.get("feature_ids") or []
        if not ids:
            # Derive a soft theme from top nouns (skip banal stems)
            words = re.findall(r"[a-zA-Z]{5,}", (ev.get("text") or "").lower())
            stop = {
                "about", "would", "could", "should", "their", "there", "these", "those",
                "because", "really", "https", "feature", "change", "changes", "using",
                "please", "thanks", "something", "anything", "without", "having", "which",
                "where", "after", "before", "still", "other", "first", "being", "issue",
                "issues", "github", "reddit", "review", "reviews", "google", "store",
            }
            words = [w for w in words if w not in stop]
            soft = Counter(words).most_common(1)
            ids = [f"theme:{soft[0][0]}"] if soft else ["theme:general"]

        for fid in ids[:3]:
            b = buckets.setdefault(fid, {
                "theme_id": fid,
                "label": FEATURE_LABELS.get(fid, fid.replace("theme:", "").replace("_", " ").title()),
                "weight": 0,
                "count": 0,
                "sources": Counter(),
                "examples": [],
            })
            b["weight"] += int(ev.get("weight") or 1)
            b["count"] += 1
            b["sources"][ev.get("source", "unknown")] += 1
            if len(b["examples"]) < 5 and ev.get("snippet"):
                b["examples"].append({
                    "snippet": ev["snippet"],
                    "source": ev.get("source"),
                    "url": ev.get("url"),
                    "weight": ev.get("weight"),
                })

    themes = sorted(buckets.values(), key=lambda x: x["weight"], reverse=True)
    max_w = themes[0]["weight"] if themes else 1

    def tier(w: float) -> str:
        r = w / max_w
        if r >= 0.75:
            return "S"
        if r >= 0.50:
            return "A"
        if r >= 0.30:
            return "B"
        return "C"

    out = []
    for t in themes[:25]:
        out.append({
            "theme_id": t["theme_id"],
            "feature_id": t["theme_id"],
            "feature": t["label"],
            "label": t["label"],
            "mentions": t["count"],
            "live_mentions": t["count"],
            "demand_score": float(t["weight"]),
            "tier": tier(t["weight"]),
            "sources": dict(t["sources"]),
            "examples": t["examples"],
            "likely_missing_from_your_app": t["theme_id"].startswith("theme:") or t["theme_id"] in {
                "docs_for_ai", "ai_features", "design_system", "onboarding", "accessibility",
            },
            "priority_action": "Deep-dive — strong live signal" if tier(t["weight"]) in ("S", "A") else "Monitor",
        })
    return out


def _evidence_digest(evidence: list[dict[str, Any]], limit: int = 40) -> str:
    ranked = sorted(evidence, key=lambda e: int(e.get("weight") or 1), reverse=True)
    lines = []
    for e in ranked[:limit]:
        lines.append(
            f"- [{e.get('source')}|w={e.get('weight')}] {e.get('snippet')}"
            + (f" ({e.get('url')})" if e.get("url") else "")
        )
    return "\n".join(lines)


# ── 4) LLM insight markdown orchestration ───────────────────────────────────


SYNTHESIS_SYSTEM = """You are a principal product researcher writing internal research memos.
Quality bar: structural insights, user/builder archetypes with approximate % among observed signals,
workflow phases, design-decision patterns, resource format gaps, and numbered pain points.
Ground claims in the provided evidence for THIS product's category only.
Do not inject unrelated verticals (e.g. Bitcoin) unless the product is in that category.
When citing percentages, say "among observed signals in this scrape".
Never invent URLs. Markdown with clear headings. Output STRICT JSON."""


async def synthesize_research_markdown(
    *,
    project: dict[str, Any],
    plan: dict[str, Any],
    themes: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    db=None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    name = project.get("name") or "Product"
    category = plan.get("category") or plan.get("vertical") or project.get("app_type") or "product"
    digest = _evidence_digest(evidence, 45)
    theme_lines = "\n".join(
        f"- {t['tier']} | {t['label']} | weight={t['demand_score']} | sources={t['sources']}"
        for t in themes[:15]
    )

    prompt = f"""Synthesize a research pack for {name} in category: {category}.

Domain framing:
{plan.get('domain_framing')}

Research questions to answer:
{json.dumps(plan.get('research_questions') or [], indent=2)}

Peers: {plan.get('competitors')}
Crawl context terms: {plan.get('context_terms')}

Theme ranking from live scrape:
{theme_lines}

Evidence digest (weighted):
{digest}

Return JSON:
{{
  "executive_summary": "5-8 sentence structural overview for THIS category (not a feature laundry list)",
  "archetypes_md": "markdown: user/builder archetypes relevant to THIS category with % of observed signals",
  "workflows_md": "markdown: how people discover, evaluate, build, or operate in this category — phases",
  "resources_and_gaps_md": "markdown: resources that exist vs format failures for this category",
  "pain_points_md": "markdown: numbered pain points with evidence-backed detail for this product/category",
  "design_decisions_md": "markdown: how design decisions get made in THIS ecosystem",
  "proposed_features": [
    {{
      "slug": "kebab-case",
      "title": "Feature name grounded in evidence",
      "tier": "S|A|B",
      "markdown": "LONG detailed markdown: Problem / Evidence / Who it serves / Proposed solution / Decision rules / Anti-patterns / Success metrics / Why now — all scoped to this product"
    }}
  ]
}}

Write 3-5 proposed_features. Extremely detailed briefs a PM could hand to eng.
Stay inside {category}. Do not pad with unrelated vertical content.
"""

    if db and user_id:
        try:
            from user_llm_proxy import user_llm_json
            result = await user_llm_json(
                db, user_id, prompt,
                system=SYNTHESIS_SYSTEM,
                session_id="demand-synth",
            )
            if isinstance(result, dict) and result.get("executive_summary"):
                result["synthesizer"] = "llm"
                return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("synthesis LLM failed: %s", exc)

    return _heuristic_synthesis(name, plan, themes, evidence)


def _heuristic_synthesis(
    name: str,
    plan: dict[str, Any],
    themes: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Research-shaped markdown from evidence — category from plan, not a hard-coded vertical essay."""
    category = plan.get("category") or plan.get("vertical") or "this category"
    competitors = plan.get("competitors") or []
    terms = plan.get("context_terms") or []
    total_w = sum(int(e.get("weight") or 1) for e in evidence) or 1
    by_source = Counter(e.get("source") for e in evidence)
    top = themes[:6]
    s_count = sum(1 for t in themes if t["tier"] == "S")
    a_count = sum(1 for t in themes if t["tier"] == "A")

    # Archetypes from source mix + theme language (category-agnostic)
    reddit_w = sum(int(e.get("weight") or 1) for e in evidence if "reddit" in str(e.get("source")))
    github_w = sum(int(e.get("weight") or 1) for e in evidence if e.get("source") == "github")
    review_w = sum(int(e.get("weight") or 1) for e in evidence if e.get("source") in {"play_store", "google_reviews"})
    power = round(100 * github_w / total_w)
    community = round(100 * reddit_w / total_w)
    end_users = round(100 * review_w / total_w)
    other = max(0, 100 - power - community - end_users)

    quotes = [e for e in sorted(evidence, key=lambda x: -int(x.get("weight") or 1)) if e.get("snippet")][:8]

    exec_sum = (
        f"{plan.get('domain_framing', '')} "
        f"Across {len(evidence)} weighted signals "
        f"(Reddit {by_source.get('reddit', 0) + by_source.get('reddit_comment', 0)}, "
        f"GitHub {by_source.get('github', 0)}, "
        f"Play/Google {by_source.get('play_store', 0) + by_source.get('google_reviews', 0)}), "
        f"{name} in {category} shows {s_count} S-tier and {a_count} A-tier themes. "
        f"Top pressure: {', '.join(t['label'] for t in top[:3]) or 'thin live signal'}. "
        f"Context terms from the product crawl ({', '.join(terms[:5]) or 'n/a'}) shaped the keyword plan."
    )

    archetypes_md = f"""## User / operator archetypes (among observed signals)

Signals for {category} split less by preference than by where people complain and request:

| Archetype | Approx. share | Where they show up | What they optimize for |
|-----------|---------------|--------------------|------------------------|
| Power / technical operators | ~{power}% | GitHub issues | Depth, APIs, edge cases |
| Community validators | ~{community}% | Reddit threads | Peer comparison, workarounds |
| End-user reviewers | ~{end_users}% | Play / review snippets | Reliability, clarity, pricing |
| Mixed / unclassified | ~{other}% | Cross-source | — |

Implication for {name}: ship surfaces that satisfy review-driven clarity *and* issue-tracker depth — peers like {', '.join(competitors[:3]) or 'category leaders'} set the expectation bar.
"""

    workflows_md = f"""## How people begin — and how the idea mutates ({category})

### Pre-building / pre-buying
Conviction and peer products often substitute for formal research. Planned questions:
{chr(10).join('- ' + q for q in (plan.get('research_questions') or [])[:5])}

### During evaluation / building
Architecture and category constraints frequently decide UX before a dedicated designer is involved. Shipped peers ({', '.join(competitors[:4]) or 'category leaders'}) operate as the de-facto design system.

### Validation
Common loop: build or configure privately → post to Reddit / Discord / reviews → iterate on comments. Feedback skews toward the literate cohort on Reddit/GitHub; Play reviews re-balance toward mainstream friction.

### Critical paths for {name}
Crawl-weighted terms to prioritize in journeys: {', '.join(terms[:6]) or 'onboarding, core CTA, settings'}.
"""

    resources_md = f"""## Resources & format gaps ({category})

Resources often exist; the format fails. Narrative help centers and long docs are hard to enforce in support macros or AI-assisted workflows — teams need decision rules, checklists, and explicit anti-patterns.

### Evidence samples
{chr(10).join(f'> {q["snippet"]}' + (f' — {q.get("source")}' if q.get("source") else '') for q in quotes[:5])}
"""

    pains = top[:6] or [{"label": "Thin live scrape", "examples": [], "demand_score": 0, "sources": {}}]
    pain_lines = []
    for i, t in enumerate(pains, 1):
        ex = (t.get("examples") or [{}])[0].get("snippet") or "No quote captured"
        pain_lines.append(
            f"{i}. **{t['label']}** (weight {t.get('demand_score')}, sources {t.get('sources')})\n"
            f"   - Signal: “{ex}”\n"
            f"   - Implication for {name}: treat as a category gap in {category}, not a one-off complaint."
        )
    pain_points_md = f"## Common pain points — {category}\n\n" + "\n\n".join(pain_lines)

    design_md = f"""## How design decisions get made ({category})

Shipped products are the primary source of design guidance. When teams stall, the default question is usually what {competitors[0] if competitors else 'a category leader'} did — not a formal design critique.

Small teams often skip a formal design phase: ship → public feedback → iterate. Dedicated designers are scarce; domain literacy is as much a barrier as budget. When designers join late, early journeys get reworked.

For {name}, peer set to watch: {', '.join(competitors) or 'infer from scrape'}.
"""

    proposed = []
    named = [x for x in themes if x["tier"] in ("S", "A") and not str(x.get("theme_id", "")).startswith("theme:")]
    if len(named) < 3:
        named = named + [x for x in themes if x["tier"] in ("S", "A") and x not in named]
    for t in named[:4]:
        slug = re.sub(r"[^a-z0-9]+", "-", t["label"].lower()).strip("-")[:48] or "feature"
        ex = t.get("examples") or []
        quotes_md = "\n".join(f"- “{e.get('snippet')}” ({e.get('source')})" for e in ex[:3]) or "- (limited quotes)"
        md = f"""# {t['label']}

## Problem
In {category}, **{t['label']}** repeatedly surfaces for {name} and peers (tier **{t['tier']}**, weight **{t['demand_score']}**).

## Evidence
{quotes_md}

Sources: {json.dumps(t.get('sources') or {})}

## Who it serves
- Users comparing {name} to {', '.join(competitors[:3]) or 'category peers'}
- Operators filing GitHub/Reddit pain when the journey breaks
- Teams without a dedicated designer copying peer patterns

## Proposed solution
Ship a first-class **{t['label']}** experience for {name} with peer-familiar defaults, explicit empty/error states, and recoverable next actions.

### Decision rules
1. Prefer patterns users already know from {competitors[0] if competitors else 'category leaders'} for high-stakes steps.
2. Pair UI copy with a checklist of constraints / acceptance criteria.
3. Every ambiguous state needs a single recommended next action.

### Anti-patterns
- Narrative help articles as the only fix
- Silent failures
- Novel interaction on critical paths without a peer precedent

## Success metrics
- Drop in threads matching this theme within 60 days
- Task completion on the critical path covering this theme
- Fewer “how do I…” support contacts

## Why now
Among observed signals this ranks tier {t['tier']} for {category}. Gaps become public quickly via Reddit, GitHub, and store reviews.
"""
        proposed.append({"slug": slug, "title": t["label"], "tier": t["tier"], "markdown": md})

    # If scrape was thin, still propose from top research questions / context terms
    if len(proposed) < 2 and terms:
        term = terms[0]
        proposed.append({
            "slug": re.sub(r"[^a-z0-9]+", "-", term)[:40],
            "title": f"Clarify {term} journey",
            "tier": "A",
            "markdown": f"""# Clarify {term} journey

## Problem
Crawl context for {name} highlights **{term}**, but live public evidence is thin or fragmented. That usually means the journey is either underspecified in-product or undocumented in peer-comparable language.

## Proposed solution
Instrument and redesign the {term} path with peer-comparable UX ({', '.join(competitors[:3])}), decision rules, and anti-patterns specific to {category}.

## Why now
Keyword planning prioritized {term} from the live app context — validate with users before it becomes a review cluster.
""",
        })

    return {
        "executive_summary": exec_sum.strip(),
        "archetypes_md": archetypes_md.strip(),
        "workflows_md": workflows_md.strip(),
        "resources_and_gaps_md": resources_md.strip(),
        "pain_points_md": pain_points_md.strip(),
        "design_decisions_md": design_md.strip(),
        "proposed_features": proposed[:5],
        "synthesizer": "heuristic",
    }


def _write_markdown_pack(
    run_id: Optional[str],
    product: str,
    plan: dict[str, Any],
    synthesis: dict[str, Any],
) -> dict[str, Any]:
    rid = run_id or uuid.uuid4().hex[:10]
    out_dir = REPORTS_DIR / f"demand_{rid}"
    out_dir.mkdir(parents=True, exist_ok=True)
    features_dir = out_dir / "proposed_features"
    features_dir.mkdir(exist_ok=True)

