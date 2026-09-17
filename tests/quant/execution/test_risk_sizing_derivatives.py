"""Derivative sizing must not zero out when stop-loss risk fits budget."""
import pytest
from quant.execution.risk import SessionRisk


def test_futures_sizing_does_not_zero_when_risk_fits_budget():
    """BANKNIFTY @ 56430, lot=30, equity=10L, deployment=50%.

    Notional = 56430 * 30 = 16.93L (exceeds 5L deployment capital).
    But stop-loss risk = (56430 - 56300) * 30 = 3900 (fits 5000 risk budget).
    System must allocate at least 1 lot.
    """
    risk = SessionRisk(
        starting_equity=1_000_000,
        base_risk_pct=0.005,  # 0.5% = 5000
        capital_deployment_pct=0.50,  # 50% = 500000
    )
    qty = risk.position_size(
        entry=56430.0,
        sl=56300.0,  # 130 points risk
        lot_size=30,
    )
    assert qty >= 30.0, f"Expected >= 1 lot (30), got {qty}"


def test_futures_sizing_respects_risk_budget_cap():
    """Even with margin awareness, total risk must not exceed risk budget."""
    risk = SessionRisk(
        starting_equity=1_000_000,
        base_risk_pct=0.005,
        capital_deployment_pct=0.50,
    )
    qty = risk.position_size(
        entry=56430.0,
        sl=56000.0,  # 430 points = 12900 risk per lot (exceeds 5000 budget)
        lot_size=30,
    )
    # 1 lot risk = 430 * 30 = 12900 > 5000 budget -> should be 0
    assert qty == 0.0


def test_futures_sizing_allows_multiple_lots_when_affordable():
    """When deployment capital covers margin for multiple lots, allow it."""
    risk = SessionRisk(
        starting_equity=10_000_000,  # 1Cr
        base_risk_pct=0.01,  # 1% = 100000
        capital_deployment_pct=0.50,  # 50L
    )
    qty = risk.position_size(
        entry=2400.0,
        sl=2350.0,  # 50 points risk
        lot_size=75,
    )
    assert qty > 0
    assert qty >= 75.0  # at least 1 lot


def test_lot_snapping_respects_rupee_risk_cap_after_rounding():
    """Nearest-lot snapping must not push realized rupee risk above the cap.

    risk_amount is pre-capped to ₹1,000, but snap_to_lot rounds 1000/105=9.52
    up to 10 lots = ₹1,050 realized risk. The post-snap re-cap must clamp to 9
    lots (₹945) so the hard cap is never breached by rounding.
    """
    risk = SessionRisk(
        starting_equity=1_000_000,
        base_risk_pct=0.005,
        day_of_week=1,  # mid-week: no defensive halving
    )
    qty = risk.position_size(
        entry=100.0,
        sl=93.0,  # 7 points = 105 risk per 15-lot
        lot_size=15.0,
        max_rupee_risk_cap=1_000.0,
    )
    realized = abs(100.0 - 93.0) * qty
    assert qty == 9 * 15
    assert realized <= 1_000.0


def test_equity_stocks_unchanged_behavior():
    """Non-derivative (lot_size=1) sizing should not change."""
    risk = SessionRisk(
        starting_equity=1_000_000,
        base_risk_pct=0.01,
        capital_deployment_pct=0.50,
    )
    qty = risk.position_size(
        entry=150.0,
        sl=145.0,
        lot_size=1,
    )
    assert qty > 0
