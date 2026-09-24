from pathlib import Path


def test_baseline_ledger_covers_all_currently_failing_surfaces():
    ledger = Path("docs/superpowers/plans/2026-09-24-baseline-failure-ledger.md")
    text = ledger.read_text(encoding="utf-8")
    for surface in ("backend", "quant", "broker", "frontend"):
        assert f"## {surface}" in text
    assert "SAFETY_INVARIANT" in text
    assert "OBSOLETE_IMPLEMENTATION_TEST" in text
    assert "INTENTIONAL_REWRITE_CHANGE" in text
