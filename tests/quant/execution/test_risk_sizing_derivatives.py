"""Derivative sizing must not zero out when stop-loss risk fits budget."""
import pytest

from quant.execution.risk import SessionRisk


@pytest.mark.parametrize("day_of_week", [0, 4])
def test_monday_friday_halving_preserves_viable_one_lot_without_cap(day_of_week):
    """Regression: with no deployment cap configured, Mon/Fri defensive
    halving must not zero a stop-distance-viable 1-lot setup.

    HEAD behavior: the post-halving floor rescue was unconditional. The
    one_lot_allowed gate must default to that rescue when no capital
    deployment cap was consulted; it only tightens when a cap branch ran.
    """
    risk = SessionRisk(
        starting_equity=1_000_000,
        day_of_week=day_of_week,  # Monday/Friday: 0.5x defensive sizing
    )
    qty = risk.position_size(
        entry=56430.0,
        sl=56350.0,  # 80 points → ₹2400/lot, fits the ₹2500 HMP budget
        lot_size=30,
    )
    assert qty >= 30.0, f"Expected >= 1 lot (30) on weekday {day_of_week}, got {qty}"


def test_futures_sizing_does_not_zero_when_risk_fits_budget():
    """BANKNIFTY-like futures: HMP stop-distance sizing + optional deployment cap.

    Conservative HMP (0.25% of 10L = ₹2500) with an 80pt stop and lot=30
    risks ₹2400/lot — fits the budget. Deployment cap must not zero a
    stop-distance-viable 1-lot setup.
    """
    risk = SessionRisk(
        starting_equity=1_000_000,
        capital_deployment_pct=0.50,
        day_of_week=1,  # mid-week: no defensive halving
    )
    qty = risk.position_size(
        entry=56430.0,
        sl=56350.0,  # 80 points → ₹2400/lot under ₹2500 HMP budget
        lot_size=30,
    )
    assert qty >= 30.0, f"Expected >= 1 lot (30), got {qty}"


def test_configured_capital_funds_wide_initiative_stop():
    """YAML capital (₹50L) must fund a typical BANKNIFTY Initiative stop.

    Reproduction: SHORT @ 56275 / SL 56652 ≈ 377pts × lot 30 = ₹11.3k risk.
    At ₹10L HMP (₹2.5k) this sized to 0 and the UI still said Approved.
    At ₹50L HMP (₹12.5k) it must clear 1 lot.
    """
    risk = SessionRisk(
        starting_equity=5_000_000.0,
        capital_deployment_pct=0.95,
        day_of_week=1,
    )
    qty = risk.position_size(
        entry=56275.0,
        sl=56651.94,
        lot_size=30.0,
        max_lots=10,
    )
    assert qty >= 30.0, f"Expected >= 1 lot, got {qty}"


def test_futures_sizing_respects_risk_budget_cap():
    """Even with margin awareness, total risk must not exceed risk budget."""
    risk = SessionRisk(
        starting_equity=1_000_000,
        base_risk_pct=0.005,
        capital_deployment_pct=0.50,
        day_of_week=1,
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
        day_of_week=1,
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


@pytest.mark.parametrize("day_of_week", [0, 4])
def test_cap_set_monday_friday_preserves_viable_one_lot(day_of_week):
    """A configured deployment cap must floor at 1 lot when stop risk fits.

    Deployment capital may mathematically allow 0 lots after the defensive
    halving, but the stop-loss risk (₹2400) still fits the budget (₹2500).
    In that case the 1-lot rescue remains valid even with a cap set.
    """
    risk = SessionRisk(
        starting_equity=1_000_000,
        capital_deployment_pct=0.10,
        day_of_week=day_of_week,
    )
    qty = risk.position_size(
        entry=56430.0,
        sl=56350.0,
        lot_size=30,
    )
    assert qty >= 30.0, f"Expected >= 1 lot (30) on weekday {day_of_week}, got {qty}"
