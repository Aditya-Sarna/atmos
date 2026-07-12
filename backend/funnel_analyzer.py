"""Real conversion funnel analysis with click-path counting and annotated video."""

from __future__ import annotations

import logging
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from playwright.async_api import Browser, Page

from atmos_engine import NAV_TIMEOUT_MS, SCREENSHOTS_DIR, VIEWPORTS, _new_context, _safe_name, _settle

logger = logging.getLogger("atmos.funnel")

ProgressFn = Callable[[dict[str, Any]], Any]

# Industry click-to-conversion benchmarks (from public UX teardowns / Mobbin flow analysis)
INDUSTRY_FUNNEL_BENCHMARKS: dict[str, dict[str, Any]] = {
    "e-commerce": {
        "goal_keywords": ["checkout", "cart", "buy", "purchase", "pay", "order", "add to cart"],
        "competitors": {"Amazon": 3, "Shopify": 4, "Apple Store": 4, "Etsy": 5},
        "industry_avg": 4,
    },
    "finance": {
        "goal_keywords": ["pay", "checkout", "transfer", "send", "subscribe", "confirm"],
        "competitors": {"Stripe": 3, "PayPal": 4, "Wise": 4, "Revolut": 3},
        "industry_avg": 4,
    },
    "calendar": {
        "goal_keywords": ["book", "schedule", "confirm", "create event", "save"],
        "competitors": {"Google Calendar": 2, "Calendly": 3, "Fantastical": 3},
        "industry_avg": 3,
    },
    "dashboard": {
        "goal_keywords": ["create", "new", "add", "invite", "export"],
        "competitors": {"Linear": 2, "Notion": 3, "Vercel": 3},
        "industry_avg": 3,
    },
    "generic": {
        "goal_keywords": ["sign up", "get started", "continue", "submit", "create", "buy", "checkout"],
        "competitors": {"Apple": 3, "Stripe": 3, "Linear": 2},
        "industry_avg": 4,
    },
}


FUNNEL_OVERLAY_CSS = """
#atmos-funnel-overlay {
  position: fixed; top: 16px; left: 16px; right: 16px; z-index: 2147483647;
  background: rgba(0,113,227,0.95); color: #fff; padding: 14px 18px; border-radius: 14px;
  font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 15px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25); pointer-events: none;
}
#atmos-funnel-overlay .step { font-weight: 700; font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.1em; opacity: 0.85; }
#atmos-funnel-overlay .action { margin-top: 4px; font-size: 16px; font-weight: 600; }
#atmos-funnel-counter {
  position: fixed; bottom: 20px; right: 20px; z-index: 2147483647;
  background: #1D1D1F; color: #fff; padding: 12px 20px; border-radius: 999px;
  font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 18px; font-weight: 700;
  box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}
"""


async def _show_funnel_step(page: Page, step_num: int, action: str, total_clicks: int) -> None:
    await page.evaluate(
        """([css, step, action, clicks]) => {
          let s = document.getElementById('atmos-funnel-style');
          if (!s) { s = document.createElement('style'); s.id = 'atmos-funnel-style'; document.head.appendChild(s); }
          s.textContent = css;
          let o = document.getElementById('atmos-funnel-overlay');
          if (!o) { o = document.createElement('div'); o.id = 'atmos-funnel-overlay'; document.body.appendChild(o); }
          o.innerHTML = '<div class="step">Step ' + step + '</div><div class="action">' + action + '</div>';
          let c = document.getElementById('atmos-funnel-counter');
          if (!c) { c = document.createElement('div'); c.id = 'atmos-funnel-counter'; document.body.appendChild(c); }
          c.textContent = clicks + ' click' + (clicks === 1 ? '' : 's') + ' so far';
        }""",
        [FUNNEL_OVERLAY_CSS, step_num, action, total_clicks],
    )
    await page.wait_for_timeout(900)


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/') or '/'}"


def _build_action_graph(
    pages: list[dict[str, Any]],
    button_actions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build adjacency list from discovered button actions."""
    graph: dict[str, list[dict[str, Any]]] = {}
    page_urls = {_normalize_url(p["url"]): p for p in pages}
