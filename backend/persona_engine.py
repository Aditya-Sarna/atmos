"""Academic persona-based UX simulation with Playwright video + annotations.

Rules derived from:
- JMIR mHealth 2023 systematic review (e43186) — elderly mobile UX
- Nielsen Norman Group Heuristic #7 — flexibility & efficiency (novice vs expert)
- WCAG 2.2 touch target / contrast guidance
- Think-aloud usability studies with older adults (JMIR Human Factors 2024)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.async_api import Browser, Page

from atmos_engine import NAV_TIMEOUT_MS, SCREENSHOTS_DIR, VIEWPORTS, _new_context, _safe_name, _settle

logger = logging.getLogger("atmos.personas")

ProgressFn = Callable[[dict[str, Any]], Any]

PERSONA_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "elderly",
        "label": "Elderly User (65+)",
        "focus": "Vision, dexterity, slow reading",
        "citations": ["JMIR mHealth 2023 e43186", "Aging Clin Exp Res 2025"],
        "viewport": "iPhone SE",
        "typing_delay_ms": 450,
        "rules": [
            {"id": "touch_44", "weight": 15, "desc": "Interactive targets ≥44×44px (WCAG 2.5.5)"},
            {"id": "font_16", "weight": 12, "desc": "Body text ≥16px for readability"},
            {"id": "contrast", "weight": 12, "desc": "Text contrast ratio ≥4.5:1"},
            {"id": "nav_simple", "weight": 10, "desc": "Primary action visible without scrolling"},
            {"id": "error_recovery", "weight": 8, "desc": "Clear error messages with recovery path"},
        ],
    },
    {
        "id": "blind",
        "label": "Blind User",
        "focus": "Screen reader, keyboard-only",
        "citations": ["WCAG 2.2", "WebAIM Million 2024"],
        "viewport": "Desktop 1440",
        "keyboard_only": True,
        "rules": [
            {"id": "aria_labels", "weight": 18, "desc": "Form controls have accessible names"},
            {"id": "landmarks", "weight": 12, "desc": "Page has main/nav landmarks"},
            {"id": "focus_visible", "weight": 14, "desc": "Keyboard focus indicator visible"},
            {"id": "skip_link", "weight": 8, "desc": "Skip-to-content or logical tab order"},
            {"id": "alt_text", "weight": 10, "desc": "Meaningful images have alt text"},
        ],
    },
    {
        "id": "low_vision",
        "label": "Low-Vision User",
        "focus": "200–400% zoom",
        "citations": ["WCAG 1.4.4", "JMIR e43186"],
        "viewport": "Desktop 1440",
        "zoom_factor": 2.0,
        "rules": [
            {"id": "reflow", "weight": 15, "desc": "Content reflows at 200% zoom without horizontal scroll"},
            {"id": "contrast_high", "weight": 12, "desc": "High contrast mode legibility"},
            {"id": "text_scale", "weight": 10, "desc": "Text remains readable when scaled"},
            {"id": "no_hover_only", "weight": 10, "desc": "Critical actions not hover-only"},
        ],
    },
    {
        "id": "color_blind",
        "label": "Color-Blind User",
        "focus": "Protanopia / Deuteranopia",
        "citations": ["WCAG 1.4.1", "Colour Blind Awareness"],
        "viewport": "Desktop 1440",
        "color_filter": "protanopia",
        "rules": [
            {"id": "not_color_only", "weight": 18, "desc": "Status not conveyed by color alone"},
            {"id": "link_distinguish", "weight": 12, "desc": "Links distinguishable without color hue"},
            {"id": "chart_patterns", "weight": 8, "desc": "Charts/icons have non-color cues"},
        ],
    },
    {
        "id": "first_time",
        "label": "First-Time User",
        "focus": "Discoverability, confusion points",
        "citations": ["Nielsen #6 Recognition", "NN/g Novice vs Expert"],
        "viewport": "iPhone SE",
        "rules": [
            {"id": "primary_cta", "weight": 15, "desc": "Primary CTA identifiable within 5 seconds"},
            {"id": "clear_labels", "weight": 12, "desc": "Buttons use action verbs, not jargon"},
            {"id": "progress_hint", "weight": 10, "desc": "Multi-step flows show progress or context"},
            {"id": "empty_state", "weight": 8, "desc": "Empty states guide next action"},
        ],
    },
    {
        "id": "power_user",
        "label": "Power User",
        "focus": "Shortcuts, efficiency",
        "citations": ["Nielsen #7 Flexibility", "NN/g UI Accelerators"],
        "viewport": "Desktop 1440",
        "rules": [
            {"id": "keyboard_shortcuts", "weight": 14, "desc": "Keyboard shortcuts or command palette"},
            {"id": "bulk_actions", "weight": 10, "desc": "Bulk/multi-select for repeated tasks"},
            {"id": "search_quick", "weight": 12, "desc": "Global search or quick-jump (⌘K style)"},
            {"id": "click_efficiency", "weight": 14, "desc": "Core task reachable in ≤3 clicks from home"},
        ],
    },
    {
        "id": "child",
        "label": "Child User (8–12)",
        "focus": "Readability, misclick potential",
        "citations": ["ACM IDC child UX", "COPPA design patterns"],
        "viewport": "iPhone SE",
        "rules": [
            {"id": "large_targets", "weight": 15, "desc": "Touch targets ≥48px to prevent mis-taps"},
            {"id": "simple_language", "weight": 12, "desc": "Reading level ≤ grade 6 on primary copy"},
            {"id": "destructive_guard", "weight": 10, "desc": "Destructive actions require confirmation"},
            {"id": "no_tiny_links", "weight": 10, "desc": "No inline text links smaller than 14px"},
        ],
    },
]


ANNOTATION_CSS = """
#atmos-persona-overlay {
  position: fixed; bottom: 16px; left: 16px; right: 16px; z-index: 2147483647;
  background: rgba(29,29,31,0.92); color: #fff; padding: 12px 16px; border-radius: 12px;
  font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 14px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.35); pointer-events: none;
  border-left: 4px solid {color};
}
#atmos-persona-overlay .persona { font-weight: 600; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.08em; color: {color}; margin-bottom: 4px; }
"""


async def _show_annotation(page: Page, persona_label: str, message: str, color: str = "#FF9500") -> None:
    css = ANNOTATION_CSS.format(color=color)
    await page.evaluate(
        """([css, label, msg]) => {
          let s = document.getElementById('atmos-persona-style');
          if (!s) { s = document.createElement('style'); s.id = 'atmos-persona-style'; document.head.appendChild(s); }
          s.textContent = css;
          let el = document.getElementById('atmos-persona-overlay');
          if (!el) { el = document.createElement('div'); el.id = 'atmos-persona-overlay'; document.body.appendChild(el); }
          el.innerHTML = '<div class="persona">' + label + '</div><div>' + msg + '</div>';
        }""",
        [css, persona_label, message],
    )
    await page.wait_for_timeout(800)


async def _hide_annotation(page: Page) -> None:
    await page.evaluate("() => { const el = document.getElementById('atmos-persona-overlay'); if (el) el.remove(); }")


async def _audit_touch_targets(page: Page, min_px: int = 44) -> tuple[bool, str]:
    result = await page.evaluate(
        """(minPx) => {
          const bad = [];
          for (const el of document.querySelectorAll('button, a, input, [role=button], [onclick]')) {
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            if (r.width < minPx || r.height < minPx) {
              const t = (el.innerText || el.getAttribute('aria-label') || el.tagName).slice(0, 30);
              bad.push(t + ' (' + Math.round(r.width) + '×' + Math.round(r.height) + 'px)');
            }
          }
          return { ok: bad.length === 0, bad: bad.slice(0, 5) };
        }""",
        min_px,
    )
    if result["ok"]:
        return True, "All interactive targets meet minimum size"
    return False, f"Small targets: {', '.join(result['bad'])}"


async def _audit_font_size(page: Page, min_px: int = 16) -> tuple[bool, str]:
    result = await page.evaluate(
        """(minPx) => {
          const body = document.body;
          const fs = parseFloat(getComputedStyle(body).fontSize) || 16;
          const small = [];
          for (const el of document.querySelectorAll('p, span, label, li, td')) {
            const t = (el.innerText || '').trim();
            if (t.length < 8) continue;
            const f = parseFloat(getComputedStyle(el).fontSize);
            if (f < minPx) { small.push(t.slice(0, 40) + ' (' + Math.round(f) + 'px)'); if (small.length >= 3) break; }
