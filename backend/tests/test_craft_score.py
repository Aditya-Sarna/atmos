"""Craft Score unit checks."""

from craft_score import compute_craft_score, compare_to_baseline, evaluate_gate, attach_craft_to_summary


def test_craft_score_basic():
    craft = compute_craft_score(
        scores={"accessibility": 90, "ux": 80, "reliability": 85},
        personas=[{"score": 70}, {"score": 80}],
        design_theory={"score": 88},
        funnel={"your_clicks": 3, "industry_avg": 4},
        competitive_diffs=[{"pattern_annotations": [{"status": "present"}, {"status": "present"}]}],
        issue_counts={"accessibility": 0, "ux": 0, "functional": 0},
        dopamine={"dark_pattern_score": 95},
    )
    assert 70 <= craft["overall"] <= 100
    assert craft["tier"] in {"world_class", "strong", "competitive", "needs_work", "critical"}
    assert craft["components"]["integrity"] == 95
    assert craft["version"] == "1.1"


def test_integrity_lowers_score():
    clean = compute_craft_score(
        scores={"accessibility": 90, "ux": 90, "reliability": 90},
        dopamine={"dark_pattern_score": 100},
    )
    dirty = compute_craft_score(
        scores={"accessibility": 90, "ux": 90, "reliability": 90},
        dopamine={"dark_pattern_score": 40},
        issue_counts={"dark_pattern": 3},
    )
    assert dirty["overall"] < clean["overall"]
    assert dirty["components"]["integrity"] == 40


def test_gate_and_baseline():
    current = compute_craft_score(scores={"accessibility": 60, "ux": 60, "reliability": 60})
    baseline = {**compute_craft_score(scores={"accessibility": 80, "ux": 80, "reliability": 80}), "run_id": "old"}
    cmp_ = compare_to_baseline(current, baseline)
    assert cmp_["has_baseline"] is True
    assert cmp_["delta"] < 0
    gate = evaluate_gate(current, threshold=70, baseline_comparison=cmp_)
    assert gate["passed"] is False


def test_attach():
    summary = {
        "scores": {"accessibility": 88, "ux": 84, "reliability": 90},
        "personas": [],
        "counts": {},
        "dopamine": {"dark_pattern_score": 92},
        "issues": [{"category": "Dark pattern"}],
    }
    attach_craft_to_summary(summary, gate_threshold=70, run_id="r1")
    assert "craft_score" in summary
    assert summary["craft_score"]["components"]["integrity"] == 92
    assert summary["craft_gate"]["passed"] is True
