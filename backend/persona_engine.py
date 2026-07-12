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
