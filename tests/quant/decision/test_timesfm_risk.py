"""Unit tests for TimesFMRiskAuthority dynamic exits and ExitEngine integration."""

import numpy as np
import pytest

from quant.contracts.enums import MarketState
from quant.decision.timesfm_agents import TimesFMForecast
from quant.decision.timesfm_risk import TimesFMRiskAuthority
from quant.execution.exits import ExitDecision, ExitEngine
from quant.execution.order import Order, Position, Signal


@pytest.fixture
def trending_forecast():
    horizon = 32
    curr_price = 8010.0
    p50 = np.linspace(curr_price, curr_price + 30.0, horizon)
    p10 = p50 - 5.0
    p90 = p50 + 5.0
    return TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=10.0,
        mean_forecast=float(p50[-1]),
        pct_change=(p50[-1] - curr_price) / curr_price,
        forecast_steps=["LONG"] * horizon,
        curr_price=curr_price,
        lat_ms=12.0,
    )


@pytest.fixture
def inflecting_forecast():
    horizon = 32
    curr_price = 8030.0
    # Peaked at step 3, then falls
    p50 = np.array([8030.0, 8035.0, 8038.0, 8039.0] + list(np.linspace(8035.0, 8015.0, 28)))
    p10 = p50 - 5.0
    p90 = p50 + 5.0
    return TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=10.0,
        mean_forecast=float(p50[-1]),
        pct_change=(p50[-1] - curr_price) / curr_price,
        forecast_steps=["SHORT"] * horizon,
        curr_price=curr_price,
        lat_ms=12.0,
    )


def _make_dummy_position(entry=8000.0, sl=7980.0, size=10.0):
    sig = Signal(
        type="LONG",
        reason="TEST",
        entry=entry,
        sl=sl,
        tp=8050.0,
        rr=2.5,
        model_label="TimesFM",
        symbol="CRUDEOIL",
        timestamp="2026-09-08T16:00:00",
    )
    order = Order(
        signal=sig,
        quantity=size,
    )
    pos = Position(
        order=order,
        open_price=entry,
        open_time="2026-09-08T16:00:00",
        size=size,
    )
    return pos


def test_monotonic_trailing_stop_ratchet(trending_forecast):
    authority = TimesFMRiskAuthority()
    pos_id = "test_pos_1"
    entry = 8000.0
    initial_sl = 7980.0

    # First update: p10[0] is approx 8005.0 -> stop should ratchet up
    stop_1, risk_free_1 = authority.update_trailing_stop(pos_id, "LONG", entry, initial_sl, trending_forecast)
    assert stop_1 > initial_sl
    assert stop_1 >= entry
    assert risk_free_1 is True

    # If subsequent forecast has lower p10 (e.g. temporary pullback), stop must NOT loosen (monotonic)
    pullback_fc = TimesFMForecast(
        horizon=32,
        p50_path=np.full(32, 7990.0),
        p10_path=np.full(32, 7970.0),
        p90_path=np.full(32, 8010.0),
        q_spread=40.0,
        mean_forecast=7990.0,
        pct_change=-0.001,
        forecast_steps=["SHORT"] * 32,
        curr_price=7990.0,
        lat_ms=10.0,
    )
    stop_2, _ = authority.update_trailing_stop(pos_id, "LONG", entry, stop_1, pullback_fc)
    assert stop_2 >= stop_1  # Stop never moves backwards


def test_trajectory_inflection_take_profit(inflecting_forecast):
    authority = TimesFMRiskAuthority()
    pos_id = "test_pos_2"
    entry = 8000.0
    curr_price = 8030.0  # +30 pts (1.5R achieved)
    sl = 7980.0

    eval_res = authority.evaluate_exit(
        position_id=pos_id,
        side="LONG",
        entry=entry,
        current_price=curr_price,
        bars_held=6,
        forecast=inflecting_forecast,
        active_sl=sl,
    )
    assert eval_res.should_exit is True
    assert eval_res.reason == "TRAJECTORY_INFLECTION"
    assert eval_res.action == "TAKE_PROFIT"
    assert "inflects" in eval_res.rationale


def test_forecast_outcome_calibration_throttling():
    authority = TimesFMRiskAuthority()
    # High accuracy predictions
    for _ in range(6):
        authority.record_forecast_outcome(predicted_p50_terminal=8020.0, actual_price=8021.0, initial_price=8000.0)
    mult_good = authority.get_session_budget_multiplier()
    assert mult_good >= 1.0

    # Severe forecast errors (market regime shock)
    for _ in range(15):
        authority.record_forecast_outcome(predicted_p50_terminal=8100.0, actual_price=7800.0, initial_price=8000.0)
    mult_bad = authority.get_session_budget_multiplier()
    assert mult_bad < 1.0
    assert mult_bad >= 0.40  # floor at 0.4x


def test_var_stop_records_forecast_calibration(trending_forecast):
    authority = TimesFMRiskAuthority()
    assert len(authority._forecast_errors) == 0
    eval_res = authority.evaluate_exit(
        position_id="test_calib_1",
        side="LONG",
        entry=8000.0,
        current_price=7990.0,
        bars_held=6,
        forecast=trending_forecast,
        active_sl=7980.0,
    )
    assert eval_res.should_exit is True
    assert eval_res.reason == "VAR_STOP"
    assert len(authority._forecast_errors) == 1


def test_exit_engine_incorporates_timesfm_forecast(inflecting_forecast):
    engine = ExitEngine()
    pos = _make_dummy_position(entry=8000.0, sl=7980.0)

    decision = engine.evaluate(
        pos,
        bar_close=8030.0,
        timesfm_forecast=inflecting_forecast,
    )
    assert isinstance(decision, ExitDecision)
    assert decision.should_exit is True
    assert decision.reason == "TRAJECTORY_INFLECTION"
