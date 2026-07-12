"""Craft Score — the category object Atmos owns.

A single 0–100 score composed from measured run evidence, with baseline
delta and merge-gate semantics. This is the system of record for product
judgment (not a vanity dashboard metric).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


CRAFT_VERSION = "1.1"

# Weights must sum to 1.0
WEIGHTS = {
    "accessibility": 0.18,
    "personas": 0.14,
    "ux": 0.14,
    "design": 0.10,
    "funnel": 0.10,
    "reliability": 0.10,
    "competitive": 0.10,
    "integrity": 0.14,  # dark-pattern cleanliness (higher = cleaner)
}

DEFAULT_GATE_THRESHOLD = 70


def _clamp(n: float, lo: float = 0, hi: float = 100) -> int:
    return int(max(lo, min(hi, round(n))))


def _persona_avg(personas: list[dict[str, Any]]) -> Optional[float]:
    if not personas:
        return None
    vals = [float(p.get("score") or 0) for p in personas if p.get("score") is not None]
    return sum(vals) / len(vals) if vals else None


def _funnel_score(funnel: dict[str, Any]) -> Optional[float]:
    if not funnel:
        return None
    yours = funnel.get("your_clicks")
    avg = funnel.get("industry_avg")
    verdict = (funnel.get("verdict") or "").lower()
    if yours is None and not verdict:
        return None
    if isinstance(yours, (int, float)) and isinstance(avg, (int, float)) and avg > 0:
        # Fewer clicks than industry → higher score
        ratio = float(yours) / float(avg)
        return _clamp(100 - (ratio - 1) * 40)
    if "better" in verdict or "ahead" in verdict:
        return 82
    if "worse" in verdict or "behind" in verdict:
        return 55
    return 70


def _design_score(design: dict[str, Any]) -> Optional[float]:
    if not design:
        return None
    if design.get("score") is not None:
        return float(design["score"])
    return None


def _competitive_score(diffs: list[dict[str, Any]]) -> Optional[float]:
    if not diffs:
        return None
    statuses = []
    for d in diffs:
        for a in d.get("pattern_annotations") or []:
            st = (a.get("status") or "review").lower()
            statuses.append(st)
    if not statuses:
        return 72  # captured peers but no annotations yet
    present = sum(1 for s in statuses if s in {"present", "pass", "matched", "ok"})
    missing = sum(1 for s in statuses if s in {"missing", "fail", "gap"})
    review = len(statuses) - present - missing
    raw = 55 + present * 8 - missing * 12 + review * 2
    return _clamp(raw)


def compute_craft_score(
    *,
    scores: dict[str, Any],
    personas: Optional[list[dict[str, Any]]] = None,
    design_theory: Optional[dict[str, Any]] = None,
    funnel: Optional[dict[str, Any]] = None,
    competitive_diffs: Optional[list[dict[str, Any]]] = None,
    accessibility_audit: Optional[dict[str, Any]] = None,
    issue_counts: Optional[dict[str, Any]] = None,
    dopamine: Optional[dict[str, Any]] = None,
