"""Parity: NPOCTracker moved module vs legacy shim on fixed in-memory inputs.

Only in-memory lifecycle methods are compared (add_session_poc / get_active_npocs);
check_and_fill and load_from_storage call storage adapters via
ensure_sync_adapter_result, which is exercised by the ported unit tests with a
mock storage port.
"""

from __future__ import annotations

from app.domain.fabio_ai.services.npoc_tracker import NPOCTracker as LegacyNPOCTracker
from quant.amt.session.npoc import NPOCTracker
from tests.quant.parity import assert_parity


class _NoopStorage:
    """Storage that records nothing; sync calls only (never awaited)."""

    def __init__(self):
        self.saved = []

    def save_npoc(self, underlying, session_date, poc_price):
        self.saved.append((underlying, session_date, poc_price))

    def mark_npoc_filled(self, underlying, session_date, filled_at):
        pass

    def get_active_npocs(self, underlying):
        return []


def _run(factory):
    t = factory()
    t.add_session_poc("NIFTY", "2026-03-17", 24300.0)
    t.add_session_poc("NIFTY", "2026-03-18", 24400.0)
    t.add_session_poc("NIFTY", "2026-03-19", 24600.0)
    t.add_session_poc("BANKNIFTY", "2026-03-19", 51000.0)
    return t


def test_npoc_parity_active_after_adds():
    legacy = _run(lambda: LegacyNPOCTracker(_NoopStorage()))
    new = _run(lambda: NPOCTracker(_NoopStorage()))
    assert_parity(
        lambda: legacy.active_npocs["NIFTY"],
        lambda: new.active_npocs["NIFTY"],
    )
    assert_parity(
        lambda: legacy.active_npocs["BANKNIFTY"],
        lambda: new.active_npocs["BANKNIFTY"],
    )
    assert_parity(
        lambda: legacy.get_active_npocs("NIFTY", 24500.0),
        lambda: new.get_active_npocs("NIFTY", 24500.0),
    )
    assert_parity(
        lambda: legacy.get_active_npocs("NIFTY", 24350.0, lookback_days=2),
        lambda: new.get_active_npocs("NIFTY", 24350.0, lookback_days=2),
    )


def test_npoc_parity_duplicate_skipped():
    def run(factory):
        t = factory()
        t.add_session_poc("NIFTY", "2026-03-19", 24500.0)
        t.add_session_poc("NIFTY", "2026-03-19", 24600.0)
        return t

    legacy = run(lambda: LegacyNPOCTracker(_NoopStorage()))
    new = run(lambda: NPOCTracker(_NoopStorage()))
    assert_parity(lambda: legacy.active_npocs, lambda: new.active_npocs)
