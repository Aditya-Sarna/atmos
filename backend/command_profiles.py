"""Per-command run profiles — each slash command specializes the pipeline."""

from __future__ import annotations

from typing import Any

# Phase keys used by _execute_run
ALL_PHASES = [
    "github_boot", "analyze", "explore", "design_theory", "competitive",
    "per_page", "accessibility", "personas", "issues", "fuzz", "screen_tests",
    "architecture", "test_cases", "custom_tests", "benchmark", "dopamine",
    "copywriting", "demand", "report",
]

_PROFILES: dict[str, dict[str, Any]] = {
    "/atmos analyze": {
        "label": "Deep product analysis",
        "phases": {
            "github_boot", "analyze", "explore", "design_theory", "competitive",
            "per_page", "accessibility", "dopamine", "issues", "architecture", "report",
        },
        "persona_ids": ["first_time", "power_user"],
        "mobile_viewports_only": False,
        "explore_max_secs": 60,
        "max_pages_analyze": 8,
    },
    "/atmos explore": {
        "label": "Journey discovery",
        "phases": {
            "github_boot", "analyze", "explore", "screen_tests", "test_cases",
            "custom_tests", "benchmark", "report",
        },
        "persona_ids": None,
        "explore_max_secs": 120,
        "max_pages_analyze": 4,
    },
    "/atmos test": {
        "label": "Full suite",
        "phases": set(ALL_PHASES),
        "persona_ids": None,
        "explore_max_secs": 90,
        "max_pages_analyze": 12,
    },
    "/atmos regress": {
        "label": "Regression focus",
        "phases": {
            "github_boot", "analyze", "explore", "per_page", "fuzz",
            "screen_tests", "test_cases", "custom_tests", "architecture", "report",
        },
        "persona_ids": ["power_user"],
        "explore_max_secs": 45,
        "max_pages_analyze": 6,
    },
    "/atmos mobile": {
        "label": "Mobile / responsive",
        "phases": {
            "github_boot", "analyze", "explore", "per_page", "accessibility",
            "personas", "issues", "test_cases", "custom_tests", "report",
        },
        "persona_ids": ["elderly", "child"],
        "mobile_viewports_only": True,
        "explore_max_secs": 75,
        "max_pages_analyze": 8,
    },
    "/atmos benchmark": {
        "label": "Competitive & conversion",
        "phases": {
            "github_boot", "analyze", "explore", "competitive", "design_theory",
            "benchmark", "demand", "copywriting", "report",
        },
        "persona_ids": None,
        "explore_max_secs": 50,
        "max_pages_analyze": 5,
    },
    "/atmos accessibility": {
        "label": "Accessibility deep audit",
        "phases": {
            "github_boot", "analyze", "explore", "accessibility", "personas",
            "dopamine", "issues", "test_cases", "report",
        },
        "persona_ids": ["blind", "elderly", "low_vision", "color_blind"],
        "explore_max_secs": 60,
        "max_pages_analyze": 10,
        "a11y_deep": True,
    },
    "/atmos personas": {
        "label": "Human persona simulation",
        "phases": {
            "github_boot", "analyze", "explore", "accessibility", "personas",
            "issues", "report",
        },
        "persona_ids": "all",
        "explore_max_secs": 70,
        "max_pages_analyze": 6,
    },
    "/atmos record": {
        "label": "Narrated capture",
        "phases": {
            "github_boot", "analyze", "explore", "personas", "screen_tests",
            "test_cases", "custom_tests", "benchmark", "report",
        },
        "persona_ids": ["first_time", "elderly"],
        "explore_max_secs": 100,
        "max_pages_analyze": 5,
        "record_heavy": True,
    },
    "/atmos report": {
        "label": "Executive intelligence",
        "phases": {
            "github_boot", "analyze", "explore", "design_theory", "competitive",
            "per_page", "accessibility", "dopamine", "architecture", "benchmark",
            "copywriting", "demand", "report",
        },
        "persona_ids": ["first_time"],
        "explore_max_secs": 55,
        "max_pages_analyze": 8,
    },
}


def get_command_profile(command: str) -> dict[str, Any]:
    base = _PROFILES.get(command) or _PROFILES["/atmos test"]
    phases = set(base["phases"])
    return {
        **base,
        "command": command,
        "phases": phases,
        "includes": lambda phase: phase in phases,
    }
