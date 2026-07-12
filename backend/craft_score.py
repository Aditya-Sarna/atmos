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
) -> dict[str, Any]:
    """Build the canonical craft score object from a run summary slice."""
    a11y = scores.get("accessibility")
    if accessibility_audit and accessibility_audit.get("score") is not None:
        a11y = accessibility_audit["score"]

    integrity = None
    if dopamine and dopamine.get("dark_pattern_score") is not None:
        integrity = float(dopamine["dark_pattern_score"])
    elif scores.get("integrity") is not None:
        integrity = float(scores["integrity"])

    components: dict[str, Optional[float]] = {
        "accessibility": float(a11y) if a11y is not None else None,
        "personas": _persona_avg(personas or []),
        "ux": float(scores["ux"]) if scores.get("ux") is not None else None,
        "design": _design_score(design_theory or {}),
        "funnel": _funnel_score(funnel or {}),
        "reliability": float(scores["reliability"]) if scores.get("reliability") is not None else None,
        "competitive": _competitive_score(competitive_diffs or []),
        "integrity": integrity,
    }

    # Severity penalty from open issues (incl. dark patterns)
    counts = issue_counts or {}
    severity_penalty = (
        int(counts.get("accessibility") or 0) * 1.5
        + int(counts.get("ux") or 0) * 1.2
        + int(counts.get("functional") or 0) * 2.0
        + int(counts.get("dark_pattern") or counts.get("Dark pattern") or 0) * 2.5
    )

    present = {k: v for k, v in components.items() if v is not None}
    if not present:
        overall = 50
        weight_used = {}
    else:
        # Renormalize weights over available components
        w_sum = sum(WEIGHTS[k] for k in present)
        weight_used = {k: WEIGHTS[k] / w_sum for k in present}
        overall = sum(present[k] * weight_used[k] for k in present)
        overall = _clamp(overall - min(25, severity_penalty))

    tier = (
        "world_class" if overall >= 90
        else "strong" if overall >= 80
        else "competitive" if overall >= 70
        else "needs_work" if overall >= 55
        else "critical"
    )

    return {
        "version": CRAFT_VERSION,
        "overall": overall,
        "tier": tier,
        "components": {k: _clamp(v) if v is not None else None for k, v in components.items()},
        "weights_used": {k: round(v, 3) for k, v in weight_used.items()},
        "severity_penalty": round(min(25, severity_penalty), 1),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def compare_to_baseline(current: dict[str, Any], baseline: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not baseline or baseline.get("overall") is None:
        return {
            "has_baseline": False,
            "delta": None,
            "component_deltas": {},
            "regressions": [],
            "improvements": [],
        }
    delta = int(current["overall"]) - int(baseline["overall"])
    comp_deltas = {}
    regressions = []
    improvements = []
    for key in WEIGHTS:
        cur = (current.get("components") or {}).get(key)
        base = (baseline.get("components") or {}).get(key)
        if cur is None or base is None:
            continue
        d = int(cur) - int(base)
        comp_deltas[key] = d
        if d <= -5:
            regressions.append({"component": key, "delta": d, "from": base, "to": cur})
        elif d >= 5:
            improvements.append({"component": key, "delta": d, "from": base, "to": cur})
    return {
        "has_baseline": True,
        "baseline_overall": baseline["overall"],
        "baseline_run_id": baseline.get("run_id"),
        "delta": delta,
        "component_deltas": comp_deltas,
        "regressions": regressions,
        "improvements": improvements,
        "regressed": delta <= -3 or len(regressions) > 0,
