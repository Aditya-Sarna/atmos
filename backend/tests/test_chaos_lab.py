"""Chaos Lab pure helpers (no browser)."""

from chaos_lab import _normalize_pages, _pct, build_architecture_graph


def test_pct():
    assert _pct([], 95) == 0.0
    assert _pct([10, 20, 30, 40, 50], 50) == 30.0


def test_normalize_pages():
    pages = _normalize_pages("https://example.com", ["/a", "https://example.com/b", "/a"])
    assert pages[0].startswith("https://example.com")
    assert len(pages) == 2


def test_architecture_graph_includes_payment():
    g = build_architecture_graph(
        base_url="https://shop.test",
        pages=["https://shop.test/checkout"],
        include_payments=True,
        ide_files=[{"path": "src/api/stripe.ts"}],
    )
    kinds = {n["kind"] for n in g["nodes"]}
    assert "payment" in kinds
    assert "route" in kinds
    assert g["layers"].get("payment", 0) >= 1
