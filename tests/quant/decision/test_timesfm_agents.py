"""Unit tests for TimesFMScanningAgent and TimesFMPositionAgent."""

import numpy as np
import pytest
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.timesfm_agents import (
    TimesFMForecast,
    TimesFMPositionAgent,
    TimesFMScanningAgent,
)
from quant.decision.timesfm_engine import TimesFMEngine


@pytest.fixture
def base_forecast():
    horizon = 32
    curr_price = 8110.0
    p50 = np.linspace(curr_price, curr_price + 25.0, horizon)
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
        lat_ms=15.0,
    )


def test_scanning_agent_triple_a_long(base_forecast):
    agent = TimesFMScanningAgent(target_horizon=32)
    bar = Bar("2026-09-08T16:00:00", 8105.0, 8115.0, 8105.0, 8110.0, 2000, 400)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=8150.0,
        vah=8190.0,
        val=8109.0,
        cvd_slope=4.5,
        absorption_side="BUY",
        session_phase="PRIMARY",
        position_open=False,
    )
    res = agent.evaluate(ctx, base_forecast)
    assert res["role"] == "SCANNING"
    assert res["action"] == "ENTER_LONG"
    assert res["direction"] == "LONG"
    assert res["setup"] == "TRIPLE_A"
    assert res["confidence"] == "High"
    assert "Triple-A Long" in res["rationale"]
    assert res["activePosition"] is None


def test_scanning_agent_triple_a_short():
    agent = TimesFMScanningAgent(target_horizon=32)
    curr_price = 8190.0
    horizon = 32
    p50 = np.linspace(curr_price, curr_price - 30.0, horizon)
    down_forecast = TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p50 - 5.0,
        p90_path=p50 + 5.0,
        q_spread=10.0,
        mean_forecast=float(p50[-1]),
        pct_change=(p50[-1] - curr_price) / curr_price,
        forecast_steps=["SHORT"] * horizon,
        curr_price=curr_price,
        lat_ms=15.0,
    )
    bar = Bar("2026-09-08T16:00:00", 8185.0, 8195.0, 8185.0, 8190.0, 2000, -500)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=8150.0,
        vah=8190.0,
        val=8109.0,
        cvd_slope=-3.8,
        absorption_side="SELL",
        session_phase="PRIMARY",
        position_open=False,
    )
    res = agent.evaluate(ctx, down_forecast)
    assert res["role"] == "SCANNING"
    assert res["action"] == "ENTER_SHORT"
    assert res["direction"] == "SHORT"
    assert res["setup"] == "TRIPLE_A"
    assert "Triple-A Short" in res["rationale"]


def test_position_agent_hold_trend_intact(base_forecast):
    agent = TimesFMPositionAgent(target_horizon=32)
    bar = Bar("2026-09-08T16:05:00", 8110.0, 8118.0, 8108.0, 8115.0, 1500, 200)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=True,
        position_side="LONG",
        position_entry_price=8108.0,
        position_sl=8095.0,
        position_tp=8150.0,
        position_unrealized_pnl=70.0,
        position_bars_held=2,
        cvd_slope=2.5,
    )
    res = agent.evaluate(ctx, base_forecast)
    assert res["role"] == "POSITION_MANAGEMENT"
    assert res["action"] == "HOLD"
    assert res["reason"] == "TREND_INTACT"
    assert res["confidence"] == "High"
    assert res["activePosition"] is not None
    assert res["activePosition"]["side"] == "LONG"
    assert res["dynamicTrailStop"] is not None


def test_position_agent_tighten_sl_risk_zero(base_forecast):
    agent = TimesFMPositionAgent(target_horizon=32)
    # Entry was 8100, SL was 8090 (risk = 10). Current price 8110 (profit = 10 -> 1.0R achieved)
    bar = Bar("2026-09-08T16:05:00", 8105.0, 8112.0, 8105.0, 8110.0, 1500, 300)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=True,
        position_side="LONG",
        position_entry_price=8100.0,
        position_sl=8090.0,
        position_tp=8140.0,
        position_unrealized_pnl=100.0,
        position_bars_held=2,
        cvd_slope=3.0,
    )
    res = agent.evaluate(ctx, base_forecast)
    assert res["role"] == "POSITION_MANAGEMENT"
    assert res["action"] == "TIGHTEN_SL"
    assert res["reason"] == "RISK_ZERO"
    assert "breakeven" in res["rationale"]
    assert res["dynamicTrailStop"] == 8100.0


def test_position_agent_take_profit_target_hit(base_forecast):
    agent = TimesFMPositionAgent(target_horizon=32)
    # Target reached
    bar = Bar("2026-09-08T16:15:00", 8140.0, 8152.0, 8140.0, 8150.0, 3000, 600)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=True,
        position_side="LONG",
        position_entry_price=8108.0,
        position_sl=8108.0,
        position_tp=8150.0,
        position_unrealized_pnl=420.0,
        position_bars_held=6,
    )
    res = agent.evaluate(ctx, base_forecast)
    assert res["role"] == "POSITION_MANAGEMENT"
    assert res["action"] == "TAKE_PROFIT"
    assert res["reason"] == "TARGET_HIT"
    assert "target reached" in res["rationale"].lower()


def test_position_agent_exit_thesis_flip(base_forecast):
    agent = TimesFMPositionAgent(target_horizon=32)
    # Long trade but aggressive seller absorption and negative CVD
    bar = Bar("2026-09-08T16:10:00", 8110.0, 8112.0, 8102.0, 8105.0, 2500, -700)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=True,
        position_side="LONG",
        position_entry_price=8110.0,
        position_sl=8090.0,
        position_tp=8150.0,
        position_unrealized_pnl=-50.0,
        position_bars_held=2,
        cvd_slope=-2.8,
        absorption_side="SELL",
    )
    res = agent.evaluate(ctx, base_forecast)
    assert res["role"] == "POSITION_MANAGEMENT"
    assert res["action"] == "EXIT"
    assert res["reason"] == "THESIS_FLIP"
    assert "sellers in control" in res["rationale"] or "Thesis flip" in res["rationale"]


def test_position_agent_exit_stop_loss(base_forecast):
    agent = TimesFMPositionAgent(target_horizon=32)
    # Current price reached/breached SL
    bar = Bar("2026-09-08T16:10:00", 8100.0, 8100.0, 8088.0, 8089.0, 1000, -300)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=True,
        position_side="LONG",
        position_entry_price=8110.0,
        position_sl=8095.0,
        position_tp=8150.0,
        position_unrealized_pnl=-210.0,
        position_bars_held=3,
    )
    res = agent.evaluate(ctx, base_forecast)
    assert res["role"] == "POSITION_MANAGEMENT"
    assert res["action"] == "EXIT"
    assert res["reason"] == "STOP_LOSS"
    assert "Stop loss triggered" in res["rationale"]


def test_timesfm_engine_dynamic_role_switching():
    engine = TimesFMEngine(target_horizon=32)
    bar = Bar("2026-09-08T16:00:00", 8105.0, 8115.0, 8105.0, 8110.0, 2000, 300)

    # 1. Scanning Role: position_open = False
    ctx_scanning = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=False,
        session_phase="PRIMARY",
        poc=8150.0,
        vah=8190.0,
        val=8109.0,
        cvd_slope=3.5,
        absorption_side="BUY",
    )
    res_scanning = engine.analyze(ctx_scanning)
    assert res_scanning["role"] == "SCANNING"
    assert res_scanning["activePosition"] is None

    # 2. Position Management Role: position_open = True
    ctx_pos = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=True,
        position_side="LONG",
        position_entry_price=8105.0,
        position_sl=8090.0,
        position_tp=8150.0,
        position_unrealized_pnl=50.0,
        position_bars_held=1,
        session_phase="PRIMARY",
        poc=8150.0,
        vah=8190.0,
        val=8109.0,
        cvd_slope=3.5,
    )
    res_pos = engine.analyze(ctx_pos)
    assert res_pos["role"] == "POSITION_MANAGEMENT"
    assert res_pos["activePosition"] is not None
    assert res_pos["activePosition"]["side"] == "LONG"
    assert res_pos["action"] in ("HOLD", "TIGHTEN_SL", "TAKE_PROFIT", "EXIT")


def test_scanning_agent_rationale_morning_session(base_forecast):
    """At 09:39 IST (NSE_PRIMARY), rationale must reflect morning session, NOT midday."""
    agent = TimesFMScanningAgent(target_horizon=32)
    bar = Bar("2026-09-09T09:39:00+05:30", 56850.0, 56870.0, 56840.0, 56860.0, 1500, 10)
    ctx = DecisionContext(
        symbol="BANKNIFTY",
        bar=bar,
        poc=56850.0,
        vah=56938.3,
        val=56794.6,
        session_phase="NSE_PRIMARY",
        position_open=False,
        session_open=True,
    )
    # Neutral forecast so NO_EDGE triggers
    flat_forecast = TimesFMForecast(
        horizon=32,
        p50_path=np.full(32, 56860.0),
        p10_path=np.full(32, 56850.0),
        p90_path=np.full(32, 56870.0),
        q_spread=20.0,
        mean_forecast=56860.0,
        pct_change=0.0,
        forecast_steps=["FLAT"] * 32,
        curr_price=56860.0,
        lat_ms=10.0,
    )
    res = agent.evaluate(ctx, flat_forecast)
    assert res["action"] == "FLAT"
    assert res["setup"] == "NO_EDGE"
    assert "Morning session compression inside value area [56794.6 - 56938.3]" in res["rationale"]
    assert "Midday" not in res["rationale"]
    assert res["gateResults"][0]["passed"] is True


def test_scanning_agent_rationale_midday_session():
    """During 11:30-14:00 (NSE_MIDDAY), rationale accurately identifies Midday compression."""
    agent = TimesFMScanningAgent(target_horizon=32)
    bar = Bar("2026-09-09T12:45:00+05:30", 56850.0, 56870.0, 56840.0, 56860.0, 1500, 10)
    ctx = DecisionContext(
        symbol="BANKNIFTY",
        bar=bar,
        poc=56850.0,
        vah=56938.3,
        val=56794.6,
        session_phase="NSE_MIDDAY",
        position_open=False,
        session_open=True,
    )
    flat_forecast = TimesFMForecast(
        horizon=32,
        p50_path=np.full(32, 56860.0),
        p10_path=np.full(32, 56850.0),
        p90_path=np.full(32, 56870.0),
        q_spread=20.0,
        mean_forecast=56860.0,
        pct_change=0.0,
        forecast_steps=["FLAT"] * 32,
        curr_price=56860.0,
        lat_ms=10.0,
    )
    res = agent.evaluate(ctx, flat_forecast)
    assert "Midday compression inside value area [56794.6 - 56938.3]" in res["rationale"]


def test_scanning_agent_rationale_mcx_evening():
    """During evening MCX session, rationale identifies Evening session compression."""
    agent = TimesFMScanningAgent(target_horizon=32)
    bar = Bar("2026-09-09T19:30:00+05:30", 6450.0, 6460.0, 6440.0, 6450.0, 1500, 10)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6450.0,
        vah=6480.0,
        val=6420.0,
        session_phase="MCX_EVENING",
        position_open=False,
        session_open=True,
    )
    flat_forecast = TimesFMForecast(
        horizon=32,
        p50_path=np.full(32, 6450.0),
        p10_path=np.full(32, 6440.0),
        p90_path=np.full(32, 6460.0),
        q_spread=20.0,
        mean_forecast=6450.0,
        pct_change=0.0,
        forecast_steps=["FLAT"] * 32,
        curr_price=6450.0,
        lat_ms=10.0,
    )
    res = agent.evaluate(ctx, flat_forecast)
    assert "Evening session compression inside value area [6420.0 - 6480.0]" in res["rationale"]


def test_scanning_agent_midday_blocks_trend_continuation(base_forecast):
    """In Midday (allow_trend=False), Triple-A trend setup must be suppressed per Fabio AMT rules."""
    agent = TimesFMScanningAgent(target_horizon=32)
    bar = Bar("2026-09-09T12:45:00+05:30", 8105.0, 8115.0, 8105.0, 8110.0, 2000, 400)
    ctx_midday = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=8150.0,
        vah=8190.0,
        val=8109.0,
        cvd_slope=4.5,
        absorption_side="BUY",
        session_phase="NSE_MIDDAY",
        allow_trend=False,  # Trend continuation disabled in midday chop
        allow_reversion=True,
        position_open=False,
        session_open=True,
    )
    res = agent.evaluate(ctx_midday, base_forecast)
    # Trend setup must NOT trigger
    assert res["action"] == "FLAT"
    assert res["setup"] == "NO_EDGE"
    assert "Midday compression" in res["rationale"]


def test_scanning_agent_gate1_opening_noise_fails():
    """Gate 1 fails during NSE_OPENING / opening noise."""
    agent = TimesFMScanningAgent(target_horizon=32)
    bar = Bar("2026-09-09T09:20:00+05:30", 56850.0, 56870.0, 56840.0, 56860.0, 1500, 10)
    ctx = DecisionContext(
        symbol="BANKNIFTY",
        bar=bar,
        session_phase="NSE_OPENING",
        position_open=False,
        session_open=True,
    )
    flat_forecast = TimesFMForecast(
        horizon=32,
        p50_path=np.full(32, 56860.0),
        p10_path=np.full(32, 56850.0),
        p90_path=np.full(32, 56870.0),
        q_spread=20.0,
        mean_forecast=56860.0,
        pct_change=0.0,
        forecast_steps=["FLAT"] * 32,
        curr_price=56860.0,
        lat_ms=10.0,
    )
    res = agent.evaluate(ctx, flat_forecast)
    g1 = res["gateResults"][0]
    assert g1["gate_name"] == "SESSION_PHASE"
    assert g1["passed"] is False
    assert "Opening noise" in g1["message"]

