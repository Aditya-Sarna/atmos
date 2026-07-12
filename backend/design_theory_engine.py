"""Design fundamentals engine — typography, color, spacing with context-aware themes.

Maps app context (fintech, elderly-care, e-commerce, etc.) to appropriate design
theory expectations. Flags violations of fundamental design principles.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from playwright.async_api import Browser, Page

from atmos_engine import NAV_TIMEOUT_MS, SCREENSHOTS_DIR, VIEWPORTS, _new_context, _safe_name, _settle

logger = logging.getLogger("atmos.design_theory")

ProgressFn = Callable[[dict[str, Any]], Any]

# Context-specific design expectations (research-backed heuristics)
CONTEXT_THEMES: dict[str, dict[str, Any]] = {
    "finance": {
        "label": "Fintech / Finance",
        "description": "Trust, clarity, restrained palette — blues/grays, no playful gradients",
        "fonts": {"min_body_px": 15, "preferred": ["Inter", "SF Pro", "Roboto", "system-ui"], "avoid": ["Comic Sans", "Papyrus"]},
        "colors": {"prefer": ["#0071E3", "#0052CC", "#1D1D1F", "#FFFFFF"], "avoid_hues": ["hot pink", "neon green"], "max_accent_count": 2},
        "spacing": {"min_touch_px": 44, "section_padding_min_px": 24, "grid_base_px": 8},
        "contrast_min": 4.5,
    },
    "e-commerce": {
        "label": "E-commerce",
        "description": "Product focus, clear CTAs, scannable hierarchy",
        "fonts": {"min_body_px": 16, "preferred": ["Inter", "Helvetica", "Arial"], "avoid": []},
        "colors": {"prefer": ["high contrast CTA"], "avoid_hues": [], "max_accent_count": 3},
        "spacing": {"min_touch_px": 44, "section_padding_min_px": 16, "grid_base_px": 4},
        "contrast_min": 4.5,
    },
    "elderly-care": {
        "label": "Elderly / Healthcare",
        "description": "Large type, warm trustworthy tones, generous whitespace, low cognitive load",
        "fonts": {"min_body_px": 18, "preferred": ["Georgia", "Merriweather", "system-ui"], "avoid": ["thin weights"]},
        "colors": {"prefer": ["warm neutrals", "soft blue", "green accents"], "avoid_hues": ["low contrast gray-on-gray"], "max_accent_count": 2},
        "spacing": {"min_touch_px": 48, "section_padding_min_px": 32, "grid_base_px": 8},
        "contrast_min": 7.0,
    },
    "dashboard": {
        "label": "Dashboard / SaaS",
        "description": "Information density balanced with scanability, 8px grid",
        "fonts": {"min_body_px": 14, "preferred": ["Inter", "SF Pro", "Geist"], "avoid": []},
        "colors": {"prefer": ["neutral bg", "single accent"], "avoid_hues": [], "max_accent_count": 2},
        "spacing": {"min_touch_px": 36, "section_padding_min_px": 16, "grid_base_px": 8},
        "contrast_min": 4.5,
    },
    "generic": {
        "label": "General web",
        "description": "WCAG-aligned fundamentals",
        "fonts": {"min_body_px": 16, "preferred": ["system-ui"], "avoid": []},
        "colors": {"prefer": [], "avoid_hues": [], "max_accent_count": 4},
        "spacing": {"min_touch_px": 44, "section_padding_min_px": 16, "grid_base_px": 8},
        "contrast_min": 4.5,
    },
}

APP_TYPE_TO_THEME = {
    "finance": "finance",
    "e-commerce": "e-commerce",
    "calendar": "dashboard",
    "dashboard": "dashboard",
    "generic": "generic",
}


async def _audit_design_tokens(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const body = document.body;
          const cs = getComputedStyle(body);
          const fonts = new Set();
          const colors = new Set();
          const fontSizes = [];
          const paddings = [];
          const margins = [];
          const walk = (el, depth) => {
            if (depth > 6) return;
            const s = getComputedStyle(el);
            if (s.fontFamily) fonts.add(s.fontFamily.split(',')[0].replace(/['"]/g,'').trim());
            if (s.color) colors.add(s.color);
            if (s.backgroundColor && s.backgroundColor !== 'rgba(0, 0, 0, 0)') colors.add(s.backgroundColor);
            const fs = parseFloat(s.fontSize);
            if (fs) fontSizes.push(fs);
            const p = parseFloat(s.paddingTop) + parseFloat(s.paddingBottom);
            const m = parseFloat(s.marginTop) + parseFloat(s.marginBottom);
            if (p > 0) paddings.push(p);
            if (m > 0) margins.push(m);
            for (const c of el.children) walk(c, depth + 1);
          };
          walk(body, 0);
          const avgFont = fontSizes.length ? fontSizes.reduce((a,b)=>a+b,0)/fontSizes.length : parseFloat(cs.fontSize);
          const avgPad = paddings.length ? paddings.reduce((a,b)=>a+b,0)/paddings.length : 0;
          const avgMargin = margins.length ? margins.reduce((a,b)=>a+b,0)/margins.length : 0;
          return {
            body_font_px: avgFont,
            body_font_family: cs.fontFamily.split(',')[0].replace(/['"]/g,'').trim(),
            unique_fonts: [...fonts].slice(0, 8),
            unique_colors: [...colors].slice(0, 12),
            avg_padding_px: Math.round(avgPad),
            avg_margin_px: Math.round(avgMargin),
            font_size_samples: fontSizes.slice(0, 20),
            line_height: cs.lineHeight,
          };
        }"""
    )


def _evaluate_against_theme(tokens: dict[str, Any], theme_key: str, app_type: str) -> list[dict[str, Any]]:
