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
    theme = CONTEXT_THEMES.get(theme_key, CONTEXT_THEMES["generic"])
    issues: list[dict[str, Any]] = []

    min_body = theme["fonts"]["min_body_px"]
    if tokens.get("body_font_px", 16) < min_body:
        issues.append({
            "category": "Typography",
            "severity": "high" if theme_key == "elderly-care" else "medium",
            "title": f"Body font {tokens['body_font_px']:.0f}px below {theme['label']} minimum ({min_body}px)",
            "detail": f"For {app_type} contexts, users expect ≥{min_body}px body text for readability.",
            "fundamental": "typography_scale",
            "recommendation": f"Increase base font-size to {min_body}px; use a clear hierarchy (1.25 ratio).",
        })

    if len(tokens.get("unique_fonts") or []) > 3:
        issues.append({
            "category": "Typography",
            "severity": "medium",
            "title": f"{len(tokens['unique_fonts'])} font families — exceeds 2–3 typeface rule",
            "detail": "Multiple competing fonts reduce visual cohesion.",
            "fundamental": "typography_consistency",
            "recommendation": "Limit to one display + one body font family.",
        })

    min_pad = theme["spacing"]["section_padding_min_px"]
    if tokens.get("avg_padding_px", 0) < min_pad * 0.5 and min_pad >= 24:
        issues.append({
            "category": "Spacing",
            "severity": "medium",
            "title": "Insufficient vertical padding — cramped layout",
            "detail": f"Avg padding {tokens.get('avg_padding_px')}px; {theme['label']} expects ≥{min_pad}px sections.",
            "fundamental": "whitespace",
            "recommendation": f"Use {theme['spacing']['grid_base_px']}px grid; increase section padding to {min_pad}px+.",
        })

    accent_colors = [c for c in (tokens.get("unique_colors") or []) if "rgb" in c.lower() or "#" in c.lower()]
    if len(accent_colors) > theme["colors"]["max_accent_count"] + 4:
        issues.append({
            "category": "Color",
            "severity": "medium",
            "title": "Color palette too fragmented for context",
            "detail": f"{theme['label']}: use ≤{theme['colors']['max_accent_count']} accent colors. Found {len(accent_colors)} distinct colors.",
            "fundamental": "color_discipline",
            "recommendation": theme["description"],
        })

    if theme_key == "finance" and tokens.get("body_font_px", 16) >= 18:
        issues.append({
            "category": "Typography",
            "severity": "low",
            "title": "Large body type may feel consumer-grade for fintech",
            "detail": "Finance apps often use 15–16px dense UI to signal professionalism.",
            "fundamental": "context_fit",
            "recommendation": "Consider tighter type scale matching Stripe/Wise patterns.",
        })

    if theme_key == "elderly-care" and tokens.get("avg_margin_px", 0) < 12:
        issues.append({
            "category": "Spacing",
            "severity": "high",
            "title": "Margins too tight for elderly-care context",
            "detail": "Generous margins reduce mis-taps and cognitive load for older users.",
            "fundamental": "context_fit",
            "recommendation": "Increase block margins to 24–32px; single-column layouts preferred.",
        })

    return issues


async def analyze_design_theory(
    browser: Browser,
    target_url: str,
    run_id: str,
    app_type: str,
    *,
    theme_override: Optional[str] = None,
    on_progress: Optional[ProgressFn] = None,
) -> dict[str, Any]:
    theme_key = theme_override or APP_TYPE_TO_THEME.get(app_type, "generic")
    theme = CONTEXT_THEMES.get(theme_key, CONTEXT_THEMES["generic"])
    vp = VIEWPORTS[-1]
    ctx = await _new_context(browser, vp)
    page = await ctx.new_page()
    all_issues: list[dict[str, Any]] = []

    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        await _settle(page)
        tokens = await _audit_design_tokens(page)
        issues = _evaluate_against_theme(tokens, theme_key, app_type)

        shot_name = f"{run_id}_{_safe_name('design_theory')}.png"
        await page.screenshot(path=str(SCREENSHOTS_DIR / shot_name), full_page=False)

        for iss in issues:
            iss["screenshot_url"] = f"/api/screens/{shot_name}"
            iss["theme"] = theme_key
            all_issues.append(iss)
            if on_progress:
                await on_progress({"type": "design_theory_issue", **iss})

        result = {
            "theme_key": theme_key,
            "theme_label": theme["label"],
            "theme_description": theme["description"],
            "tokens": tokens,
            "issues": all_issues,
            "issue_count": len(all_issues),
            "score": max(35, 100 - len(all_issues) * 12),
        }
        if on_progress:
            await on_progress({"type": "design_theory", **result})
        return result
    finally:
        await ctx.close()
