"""Dopamine / dark-pattern suggestion unit checks."""

from dopamine_engine import (
    DARK_PATTERN_CATALOG,
    DARK_PATTERN_DISCLAIMER,
    _dark_pattern_score,
    _suggest_missing_dark_patterns,
)


def test_disclaimer_present():
    assert "DISCLAIMER" in DARK_PATTERN_DISCLAIMER
    assert "does not recommend" in DARK_PATTERN_DISCLAIMER.lower()


def test_score_penalizes_findings():
    clean = _dark_pattern_score([])
    dirty = _dark_pattern_score([
        {"severity": "high", "pattern": "fake_urgency"},
        {"severity": "medium", "pattern": "confirmshaming"},
    ])
    assert clean == 100
    assert dirty < clean


def test_suggest_missing_includes_disclaimer_and_unseen():
    detected = [{"id": "fake_urgency", "category": "urgency"}]
    suggestions = _suggest_missing_dark_patterns(detected, "e-commerce", signals={"formCount": 2})
    assert suggestions
    ids = {s.get("pattern_id") for s in suggestions}
    assert "fake_urgency" not in ids
    assert all(s.get("disclaimer") for s in suggestions)
    assert len(DARK_PATTERN_CATALOG) > 1
