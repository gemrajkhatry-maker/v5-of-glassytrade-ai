"""Unit tests for TimesFMPositionSizer and TimesFM-driven dynamic sizing in SessionRisk."""

import numpy as np
import pytest

from quant.decision.timesfm_agents import TimesFMForecast
from quant.decision.timesfm_sizing import DynamicSizingResult, TimesFMPositionSizer
from quant.execution.risk import SessionRisk


@pytest.fixture
def bullish_forecast():
    horizon = 32
    curr_price = 8000.0
    # Strong upward trend to 8040 peaking at step 10
    steps = np.arange(horizon)
    p50 = curr_price + 40.0 * np.sin(steps / 10.0 * (np.pi / 2.0))
    p10 = p50 - 6.0
    p90 = p50 + 6.0
    return TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=12.0,
        mean_forecast=float(p50[-1]),
        pct_change=(p50[-1] - curr_price) / curr_price,
        forecast_steps=["LONG"] * horizon,
        curr_price=curr_price,
        lat_ms=10.0,
    )


@pytest.fixture
def high_uncertainty_forecast():
    horizon = 32
    curr_price = 8000.0
    p50 = np.full(horizon, curr_price + 5.0)
    p10 = p50 - 45.0  # very wide spread
    p90 = p50 + 45.0
    return TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=90.0,
        mean_forecast=float(p50[-1]),
        pct_change=(p50[-1] - curr_price) / curr_price,
        forecast_steps=["FLAT"] * horizon,
        curr_price=curr_price,
        lat_ms=10.0,
    )


def test_var_stop_calculation_long_and_short(bullish_forecast):
    sizer = TimesFMPositionSizer()
    stop_long = sizer.calculate_var_stop(8000.0, "LONG", bullish_forecast, tick_size=0.05)
    assert stop_long < 8000.0
    # Stop should be pegged near min(p10[:5])
    assert stop_long <= float(np.min(bullish_forecast.p10_path[:5]))

    # Test short stop on inverted forecast
    stop_short = sizer.calculate_var_stop(8000.0, "SHORT", bullish_forecast, tick_size=0.05)
    assert stop_short > 8000.0
    assert stop_short >= float(np.max(bullish_forecast.p90_path[:5]))


def test_expected_target_and_tau_star(bullish_forecast):
    sizer = TimesFMPositionSizer()
    target, tau_star = sizer.calculate_expected_target(8000.0, "LONG", bullish_forecast)
    assert target > 8000.0
    assert tau_star > 0
    assert tau_star <= len(bullish_forecast.p50_path)


def test_compute_size_bullish_conviction(bullish_forecast):
    sizer = TimesFMPositionSizer()
    equity = 100000.0
    entry = 8000.0
    res = sizer.compute_size(
        equity=equity,
        entry=entry,
        side="LONG",
        forecast=bullish_forecast,
        lot_size=10.0,
    )
    assert isinstance(res, DynamicSizingResult)
    assert res.quantity > 0
    assert res.lots > 0
    assert res.quantity == res.lots * 10.0
    assert res.risk_pct >= sizer.min_risk_pct
    assert res.risk_pct <= sizer.max_risk_pct
    assert res.payoff_ratio > 1.0
    assert res.win_prob > 0.5
    assert "TimesFM Sizing" in res.rationale


def test_dispersion_scaling_reduces_size_under_uncertainty(bullish_forecast, high_uncertainty_forecast):
    sizer = TimesFMPositionSizer()
    equity = 100000.0
    entry = 8000.0

    res_bull = sizer.compute_size(equity, entry, "LONG", bullish_forecast, lot_size=1.0)
    res_unc = sizer.compute_size(equity, entry, "LONG", high_uncertainty_forecast, lot_size=1.0)

    # Uncertainty cone width reduces dispersion multiplier and risk pct
    assert res_unc.dispersion_multiplier < res_bull.dispersion_multiplier
    assert res_unc.risk_amount <= res_bull.risk_amount


def test_safety_bounding_box_clamps_extremes(bullish_forecast):
    sizer = TimesFMPositionSizer(min_risk_pct=0.002, max_risk_pct=0.008)
    equity = 100000.0
    entry = 8000.0
    res = sizer.compute_size(equity, entry, "LONG", bullish_forecast, lot_size=1.0)
    assert res.risk_pct <= 0.008
    assert res.risk_pct >= 0.002


def test_zero_risk_on_invalid_inputs(bullish_forecast):
    sizer = TimesFMPositionSizer()
    # Zero equity
    res_zero_eq = sizer.compute_size(0.0, 8000.0, "LONG", bullish_forecast)
    assert res_zero_eq.quantity == 0.0
    assert res_zero_eq.lots == 0

    # Negative entry
    res_neg_entry = sizer.compute_size(100000.0, -100.0, "LONG", bullish_forecast)
    assert res_neg_entry.quantity == 0.0


def test_session_risk_sizing_is_deterministic():
    # Sizing is the deterministic House Money Protocol: SessionRisk is the single
    # authority and TimesFM forecasts feed exits/UI only. The former
    # forecast=parameter was never read and was deleted (2026-09-17 convergence).
    # Pin a mid-week day: DAY_OF_WEEK_MULTIPLIER halves risk on Mon/Fri, so an
    # unpinned day makes this assertion calendar-dependent.
    risk = SessionRisk(starting_equity=100000.0, day_of_week=1)
    qty_rule = risk.position_size(entry=8000.0, sl=7980.0, lot_size=10.0, side="LONG")
    assert qty_rule > 0
    assert qty_rule % 10.0 == 0  # snapped to lot_size


def test_structural_target_and_minimum_rr(bullish_forecast):
    sizer = TimesFMPositionSizer()
    entry = 9064.0
    sl = 9130.0  # 66 pts risk
    side = "SHORT"

    # With structural target at POC 8950.0 (114 pts profit, > 1.7R)
    res_struct = sizer.compute_size(
        equity=100000.0,
        entry=entry,
        side=side,
        forecast=bullish_forecast,
        override_sl=sl,
        override_tp=8950.0,
    )
    assert res_struct.target_price == 8950.0
    assert res_struct.payoff_ratio >= 1.5

    # With no structural target or tiny forecast wiggle, ensures at least 1.5R minimum
    res_min_rr = sizer.compute_size(
        equity=100000.0,
        entry=entry,
        side=side,
        forecast=bullish_forecast,
        override_sl=sl,
    )
    assert res_min_rr.payoff_ratio >= 1.5
    assert res_min_rr.target_price <= entry - (abs(entry - sl) * 1.5 * 0.8)


def test_aggressive_mode_sizing(bullish_forecast):
    sizer = TimesFMPositionSizer()
    equity = 100000.0
    entry = 9064.0
    sl = 9130.0

    res_std = sizer.compute_size(equity, entry, "SHORT", bullish_forecast, override_sl=sl, is_aggressive=False)
    res_agg = sizer.compute_size(equity, entry, "SHORT", bullish_forecast, override_sl=sl, is_aggressive=True)

    # Aggressive mode deploys significantly more budget and quantity
    assert res_agg.risk_pct > res_std.risk_pct
    assert res_agg.quantity > res_std.quantity
    assert res_agg.risk_amount > res_std.risk_amount


def test_goldm_and_crudeoil_sizing_safe_bounds(bullish_forecast):
    sizer = TimesFMPositionSizer()
    equity = 1_000_000.0

    # GOLDM OCT FUT: 153490 entry, 71.92 pts stop, 10 lot_size (100g contract / 10g quote)
    res_goldm = sizer.compute_size(
        equity=equity,
        entry=153490.0,
        side="SHORT",
        forecast=bullish_forecast,
        lot_size=10.0,
        override_sl=153561.92,
        is_aggressive=True,
        max_lots=2,
    )
    # Must size exactly 1 or 2 lots (10 or 20 qty), never 695 lots!
    assert res_goldm.lots in (1, 2)
    assert res_goldm.quantity in (10.0, 20.0)
    assert res_goldm.risk_amount <= 5000.0

    # CRUDEOIL SEP FUT: 9020 entry, 50 pts stop, 100 lot_size
    res_crude = sizer.compute_size(
        equity=equity,
        entry=9020.0,
        side="LONG",
        forecast=bullish_forecast,
        lot_size=100.0,
        override_sl=8970.0,
        is_aggressive=True,
        max_lots=2,
    )
    assert res_crude.lots in (1, 2)
    assert res_crude.quantity in (100.0, 200.0)
    assert res_crude.risk_amount <= 15000.0

