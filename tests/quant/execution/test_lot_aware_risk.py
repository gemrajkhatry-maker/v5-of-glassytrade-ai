# tests/quant/execution/test_lot_aware_risk.py
"""Tests for Whole-Lot Aware Risk and Expiry Caps (Task 6)."""

import pytest
from datetime import datetime

from quant.bars import Bar
from quant.contracts.timezones import IST
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.execution.risk import SessionRisk
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def test_position_size_rounds_to_whole_lots():
    # CONSERVATIVE tier uses 0.25% risk = ₹2,500
    risk = SessionRisk(starting_equity=1_000_000.0)
    qty = risk.position_size(
        entry=100.0,
        sl=93.0,       # loss per unit = 7.0
        lot_size=15,   # loss per lot = 105.0 -> lots = floor(2500 / 105) = 23 lots
    )
    assert qty % 15 == 0
    assert qty == 23 * 15


def test_lot_rounding_never_exceeds_rupee_risk_cap():
    risk = SessionRisk(starting_equity=1_000_000.0, base_risk_pct=0.005)
    qty = risk.position_size(
        entry=100.0,
        sl=93.0,
        lot_size=15,
        max_rupee_risk_cap=1_000.0,  # ₹1,000 cap
    )
    # loss per lot = 105.0 -> lots = floor(1000 / 105) = 9 lots
    assert qty == 9 * 15
    loss = (qty / 15) * 105.0
    assert loss <= 1000.0


def test_expiry_day_uses_reduced_risk():
    risk = SessionRisk(starting_equity=1_000_000.0, base_risk_pct=0.005)
    normal_qty = risk.position_size(entry=100.0, sl=90.0, lot_size=25, is_expiry=False)
    expiry_qty = risk.position_size(entry=100.0, sl=90.0, lot_size=25, is_expiry=True)
    assert expiry_qty < normal_qty
    assert expiry_qty == normal_qty // 2


def _approved(symbol="SYM"):
    sig = Signal(type="LONG", reason="r", entry=100.0, sl=98.0, tp=102.0,
                 rr=2.0, model_label="Triple-A", symbol=symbol, timestamp="t0")
    return QuantDecision(approved=True, signal=sig, reason="Triple-A",
                         phase="", gate_results=(), block_reasons=(), model_label="Triple-A")


def _expiry_symbol(today):
    return f"SYM {today.day:02d} {today.strftime('%b').upper()} 100 CALL"


def test_position_size_honors_is_expiry_at_call_site():
    """Entry sizing is reachable only through the private _decide, so drive it
    directly and capture the is_expiry flag actually handed to SessionRisk."""
    today = datetime.now(IST).date()
    bar = Bar(time=f"{today.isoformat()}T12:00:00+05:30",
              open=100.0, high=100.0, low=100.0, close=100.0, volume=10)

    seen = []
    eng = QuantEngine(SyntheticGateway([]), _expiry_symbol(today), interval_seconds=1)
    eng._risk.position_size = lambda *a, **kw: seen.append(kw.get("is_expiry")) or 25.0
    eng._strategy.should_enter = lambda ctx: _approved(_expiry_symbol(today))
    eng._decide({}, bar)
    assert seen == [True], "expiry-day contract must pass is_expiry=True into sizing"

    seen2 = []
    eng2 = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    eng2._risk.position_size = lambda *a, **kw: seen2.append(kw.get("is_expiry")) or 25.0
    eng2._strategy.should_enter = lambda ctx: _approved("SYM")
    eng2._decide({}, Bar(time=f"{today.isoformat()}T12:00:00+05:30",
                         open=100.0, high=100.0, low=100.0, close=100.0, volume=10))
    assert seen2 == [False], "non-expiring contract must pass is_expiry=False into sizing"


def test_max_lots_cap_enforced():
    risk = SessionRisk(starting_equity=1_000_000.0)
    # Without cap: lots = 23
    uncapped = risk.position_size(entry=100.0, sl=93.0, lot_size=15)
    assert uncapped == 23 * 15
    # With cap: max 5 lots
    capped = risk.position_size(entry=100.0, sl=93.0, lot_size=15, max_lots=5)
    assert capped == 5 * 15


def test_pyramid_position_size_is_half_risk():
    risk = SessionRisk(starting_equity=1_000_000.0)
    base_qty = risk.position_size(entry=100.0, sl=90.0, lot_size=25)
    pyr_qty = risk.pyramid_position_size(entry=100.0, sl=90.0, lot_size=25)
    assert pyr_qty <= base_qty // 2
    assert pyr_qty % 25 == 0


def test_rupee_risk_for_quantity_calculation():
    risk = SessionRisk()
    rupees = risk.rupee_risk_for_quantity(entry=100.0, sl=95.0, quantity=50.0)
    assert rupees == 250.0


def test_reset_session_restores_clean_state():
    risk = SessionRisk(starting_equity=500_000.0)
    risk.record_trade(-5000.0)
    assert risk.state().daily_pnl == -5000.0
    state = risk.reset_session(date="2026-08-21")
    assert state.daily_pnl == 0.0
    assert state.consecutive_losses == 0
    assert state.trades_today == 0
    assert state.halted is False
    assert state.equity == 500_000.0

