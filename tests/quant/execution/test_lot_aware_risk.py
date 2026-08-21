# tests/quant/execution/test_lot_aware_risk.py
"""Tests for Whole-Lot Aware Risk and Expiry Caps (Task 6)."""

import pytest
from quant.execution.risk import SessionRisk


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

