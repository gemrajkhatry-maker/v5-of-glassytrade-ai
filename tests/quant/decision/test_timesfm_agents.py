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


def test_position_agent_short_in_profit_no_false_thesis_flip():
    """Option short in profit with normal option spread dispersion must NOT trigger thesis flip."""
    agent = TimesFMPositionAgent(target_horizon=32)
    # NIFTY 15 SEP 23450 PUT short @ 102.8, curr=99.7, in profit, cvd_slope=0.0
    bar = Bar("2026-09-10T10:20:00+05:30", 101.0, 101.5, 99.5, 99.7, 5000, 0)
    ctx = DecisionContext(
        symbol="NIFTY 15 SEP 23450 PUT",
        bar=bar,
        position_open=True,
        position_side="SHORT",
        position_entry_price=102.8,
        position_sl=107.0,
        position_tp=85.0,
        position_unrealized_pnl=1982.5,
        position_bars_held=0,
        cvd_slope=0.0,
        absorption_side="",
        stacked_imbalance_direction="",
    )
    # Forecast mean 101.64 (favorable for short since < 102.8 entry), q_spread 13.60 (normal for options)
    p50 = np.linspace(99.7, 101.64, 32)
    p10 = p50 - 6.8
    p90 = p50 + 6.8
    option_forecast = TimesFMForecast(
        horizon=32,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=13.60,
        mean_forecast=101.64,
        pct_change=(101.64 - 99.7) / 99.7,
        forecast_steps=["FLAT"] * 32,
        curr_price=99.7,
        lat_ms=12.0,
    )
    res = agent.evaluate(ctx, option_forecast)
    assert res["action"] in ("HOLD", "TIGHTEN_SL")
    assert res["reason"] != "THESIS_FLIP"
    assert "Opposing order flow (0.0)" not in res["rationale"]
    assert "Order flow steady" in res["rationale"] or "holding" in res["rationale"]


def test_position_agent_thesis_flip_opposing_cvd_accurate_rationale():
    """When thesis flip triggers due to opposing CVD, rationale must accurately state the CVD slope."""
    agent = TimesFMPositionAgent(target_horizon=32)
    bar = Bar("2026-09-10T10:20:00+05:30", 100.0, 102.0, 99.0, 101.5, 5000, 2000)
    ctx = DecisionContext(
        symbol="NIFTY 15 SEP 23450 PUT",
        bar=bar,
        position_open=True,
        position_side="SHORT",
        position_entry_price=100.0,
        position_sl=105.0,
        position_tp=85.0,
        position_unrealized_pnl=-150.0,
        position_bars_held=1,
        cvd_slope=3.2,
        stacked_imbalance_direction="BUY",
    )
    p50 = np.linspace(101.5, 104.0, 32)
    forecast = TimesFMForecast(
        horizon=32,
        p50_path=p50,
        p10_path=p50 - 5.0,
        p90_path=p50 + 5.0,
        q_spread=10.0,
        mean_forecast=104.0,
        pct_change=0.02,
        forecast_steps=["LONG"] * 32,
        curr_price=101.5,
        lat_ms=10.0,
    )
    res = agent.evaluate(ctx, forecast)
    assert res["action"] == "EXIT"
    assert res["reason"] == "THESIS_FLIP"
    assert "Opposing order flow (CVD slope +3.2)" in res["rationale"]
    assert "buyer pressure" in res["rationale"]


def test_scanner_triple_a_long_fires_on_sell_absorbed_far_from_val():
    """LONG Setup A must fire via the absorption arm alone (price far from VAL)."""
    import numpy as np
    from types import SimpleNamespace
    from quant.decision.timesfm_agents import TimesFMScanningAgent, TimesFMForecast
    px = 100.0
    ctx = SimpleNamespace(
        symbol="NIFTY", bar=SimpleNamespace(close=px), state=None,
        session_phase="MORNING", session_open=True, warmup_complete=True,
        allow_trend=True, allow_reversion=True,
        poc=99.0, vah=101.0, val=90.0, cvd_slope=1.5,
        absorption_side="SELL_ABSORBED", stacked_imbalance_direction="",
        risk_halted=False, cooldown_remaining_sec=0.0,
        market_state=SimpleNamespace(value="BALANCED"))
    fc = TimesFMForecast(
        horizon=32, p50_path=np.full(32, 101.0, dtype=np.float32),
        p10_path=np.full(32, 100.0, dtype=np.float32),
        p90_path=np.full(32, 102.0, dtype=np.float32),
        q_spread=2.0, mean_forecast=101.0, pct_change=0.01,
        forecast_steps=["LONG"] * 32, curr_price=px, lat_ms=5.0)
    res = TimesFMScanningAgent().evaluate(ctx, fc)
    assert res["setup"] == "TRIPLE_A" and res["direction"] == "LONG"


def test_scanner_triple_a_short_fires_on_buy_absorbed_far_from_vah():
    """SHORT Setup B must fire via the absorption arm alone (price far from VAH)."""
    import numpy as np
    from types import SimpleNamespace
    from quant.decision.timesfm_agents import TimesFMScanningAgent, TimesFMForecast
    px = 100.0
    ctx = SimpleNamespace(
        symbol="NIFTY", bar=SimpleNamespace(close=px), state=None,
        session_phase="MORNING", session_open=True, warmup_complete=True,
        allow_trend=True, allow_reversion=True,
        poc=101.0, vah=110.0, val=99.0, cvd_slope=-1.5,
        absorption_side="BUY_ABSORBED", stacked_imbalance_direction="",
        risk_halted=False, cooldown_remaining_sec=0.0,
        market_state=SimpleNamespace(value="BALANCED"))
    fc = TimesFMForecast(
        horizon=32, p50_path=np.full(32, 99.0, dtype=np.float32),
        p10_path=np.full(32, 98.0, dtype=np.float32),
        p90_path=np.full(32, 100.0, dtype=np.float32),
        q_spread=2.0, mean_forecast=99.0, pct_change=-0.01,
        forecast_steps=["SHORT"] * 32, curr_price=px, lat_ms=5.0)
    res = TimesFMScanningAgent().evaluate(ctx, fc)
    assert res["setup"] == "TRIPLE_A" and res["direction"] == "SHORT"


def test_position_agent_thesis_flip_cvd_divergence_isolated(base_forecast):
    """Standalone CVD-divergence arms fire without stacked imbalance or absorption."""
    agent = TimesFMPositionAgent(target_horizon=32)
    # Flat forecast: no trajectory breakdown, no inflection — isolates the CVD arm.
    curr_price = 8105.0
    p50 = np.full(32, curr_price)
    flat_forecast = TimesFMForecast(
        horizon=32,
        p50_path=p50,
        p10_path=p50 - 5.0,
        p90_path=p50 + 5.0,
        q_spread=10.0,
        mean_forecast=curr_price,
        pct_change=0.0,
        forecast_steps=["FLAT"] * 32,
        curr_price=curr_price,
        lat_ms=10.0,
    )
    # LONG with strong negative CVD, no absorption / no stacked imbalance
    bar = Bar("2026-09-08T16:10:00", 8110.0, 8112.0, 8102.0, 8105.0, 2500, -700)
    ctx_long = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=True,
        position_side="LONG",
        position_entry_price=8110.0,
        position_sl=8090.0,
        position_tp=8150.0,
        position_unrealized_pnl=-50.0,
        position_bars_held=2,
        cvd_slope=-3.0,
        absorption_side="",
        stacked_imbalance_direction="",
    )
    res_long = agent.evaluate(ctx_long, flat_forecast)
    assert res_long["action"] == "EXIT"
    assert res_long["reason"] == "THESIS_FLIP"

    # SHORT mirror with strong positive CVD, no absorption / no stacked imbalance
    ctx_short = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        position_open=True,
        position_side="SHORT",
        position_entry_price=8110.0,
        position_sl=8130.0,
        position_tp=8070.0,
        position_unrealized_pnl=-50.0,
        position_bars_held=2,
        cvd_slope=3.0,
        absorption_side="",
        stacked_imbalance_direction="",
    )
    res_short = agent.evaluate(ctx_short, flat_forecast)
    assert res_short["action"] == "EXIT"
    assert res_short["reason"] == "THESIS_FLIP"


def test_scanner_dynamic_sizing_scales_with_equity():
    """Scanner dynamicSizing.riskAmount must scale with account equity (not hardcoded 100k)."""
    import numpy as np
    from types import SimpleNamespace
    from quant.decision.timesfm_agents import TimesFMScanningAgent, TimesFMForecast
    px = 100.0

    def make_ctx(equity):
        return SimpleNamespace(
            symbol="NIFTY", bar=SimpleNamespace(close=px), state=None,
            session_phase="MORNING", session_open=True, warmup_complete=True,
            allow_trend=True, allow_reversion=True,
            poc=99.0, vah=101.0, val=90.0, cvd_slope=1.5,
            absorption_side="SELL_ABSORBED", stacked_imbalance_direction="",
            risk_halted=False, cooldown_remaining_sec=0.0,
            market_state=SimpleNamespace(value="BALANCED"),
            equity=equity)

    fc = TimesFMForecast(
        horizon=32, p50_path=np.full(32, 101.0, dtype=np.float32),
        p10_path=np.full(32, 100.0, dtype=np.float32),
        p90_path=np.full(32, 102.0, dtype=np.float32),
        q_spread=2.0, mean_forecast=101.0, pct_change=0.01,
        forecast_steps=["LONG"] * 32, curr_price=px, lat_ms=5.0)
    agent = TimesFMScanningAgent()
    res_lo = agent.evaluate(make_ctx(100_000), fc)
    res_hi = agent.evaluate(make_ctx(500_000), fc)
    assert res_lo["dynamicSizing"] is not None and res_hi["dynamicSizing"] is not None
    assert res_lo["dynamicSizing"]["riskAmount"] != res_hi["dynamicSizing"]["riskAmount"]


def test_scanner_option_short_blocked_for_option_symbol():
    """Options are buyers-only in advisory: scanner-B SHORT conditions must not emit ENTER_SHORT."""
    import numpy as np
    from types import SimpleNamespace
    from quant.decision.timesfm_agents import TimesFMScanningAgent, TimesFMForecast
    px = 100.0
    ctx = SimpleNamespace(
        symbol="NIFTY 15 SEP 23450 PUT", bar=SimpleNamespace(close=px), state=None,
        session_phase="MORNING", session_open=True, warmup_complete=True,
        allow_trend=True, allow_reversion=True,
        poc=101.0, vah=110.0, val=99.0, cvd_slope=-1.5,
        absorption_side="BUY_ABSORBED", stacked_imbalance_direction="",
        risk_halted=False, cooldown_remaining_sec=0.0,
        market_state=SimpleNamespace(value="BALANCED"))
    fc = TimesFMForecast(
        horizon=32, p50_path=np.full(32, 99.0, dtype=np.float32),
        p10_path=np.full(32, 98.0, dtype=np.float32),
        p90_path=np.full(32, 100.0, dtype=np.float32),
        q_spread=2.0, mean_forecast=99.0, pct_change=-0.01,
        forecast_steps=["SHORT"] * 32, curr_price=px, lat_ms=5.0)
    res = TimesFMScanningAgent().evaluate(ctx, fc)
    assert res["direction"] != "SHORT"




def test_absent_volume_profile_never_fabricates_a_setup():
    """D-4: poc/vah/val == 0 means 'no profile yet'. The scanner must stay FLAT
    instead of collapsing the VA to curr_price and trivially satisfying the
    fade conditions."""
    import numpy as np

    horizon = 32
    curr = 100.0
    p50 = np.linspace(curr, curr + 1.5, horizon)
    fc = TimesFMForecast(
        horizon=horizon, p50_path=p50, p10_path=p50 - 0.5, p90_path=p50 + 0.5,
        q_spread=1.0, mean_forecast=float(p50[-1]),
        pct_change=0.015, forecast_steps=["LONG"] * horizon,
        curr_price=curr, lat_ms=1.0,
    )
    bar = Bar("2026-09-10T10:00:00", 100.0, 101.0, 99.0, 100.0, 100, 100)
    ctx = DecisionContext(
        symbol="NIFTY", bar=bar, bar_index=20, session_open=True,
        warmup_complete=True, session_phase="PRIMARY",
        poc=0.0, vah=0.0, val=0.0, cvd_slope=1.0, allow_reversion=True,
    )
    res = TimesFMScanningAgent(target_horizon=horizon).evaluate(ctx, fc)
    assert res["action"] == "FLAT", res
    assert res["setup"] == "NO_EDGE", res
    assert res["reason"] == "NO_PROFILE", res


def test_valid_profile_still_trades():
    """Guard against over-correcting: a real profile must still fire."""
    import numpy as np

    horizon = 32
    curr = 100.0
    p50 = np.linspace(curr, curr + 1.2, horizon)
    fc = TimesFMForecast(
        horizon=horizon, p50_path=p50, p10_path=p50 - 0.5, p90_path=p50 + 0.5,
        q_spread=1.0, mean_forecast=float(p50[-1]),
        pct_change=0.012, forecast_steps=["LONG"] * horizon,
        curr_price=curr, lat_ms=1.0,
    )
    bar = Bar("2026-09-10T10:00:00", 100.0, 101.0, 99.0, 100.0, 100, 100)
    ctx = DecisionContext(
        symbol="NIFTY", bar=bar, bar_index=20, session_open=True,
        warmup_complete=True, session_phase="PRIMARY",
        poc=101.0, vah=101.5, val=99.0, cvd_slope=1.0, allow_reversion=True,
    )
    res = TimesFMScanningAgent(target_horizon=horizon).evaluate(ctx, fc)
    assert res["action"] != "FLAT", res


def test_valid_profile_va_fade_short_is_pinned():
    """A real profile whose only matching setup is VA_FADE must emit the fade."""
    horizon = 32
    curr = 100.0
    p50 = np.linspace(curr, curr - 0.5, horizon)
    fc = TimesFMForecast(
        horizon=horizon, p50_path=p50, p10_path=p50 - 0.5, p90_path=p50 + 0.5,
        q_spread=1.0, mean_forecast=float(p50[-1]),
        pct_change=-0.0005, forecast_steps=["SHORT"] * horizon,
        curr_price=curr, lat_ms=1.0,
    )
    bar = Bar("2026-09-10T10:00:00", 100.0, 101.0, 99.0, 100.0, 100, 100)
    ctx = DecisionContext(
        symbol="NIFTY", bar=bar, bar_index=20, session_open=True,
        warmup_complete=True, session_phase="PRIMARY",
        poc=99.0, vah=100.0, val=99.0, cvd_slope=0.0, allow_reversion=True,
    )
    res = TimesFMScanningAgent(target_horizon=horizon).evaluate(ctx, fc)
    assert res["setup"] == "VA_FADE", res
    assert res["action"] == "ENTER_SHORT", res


def test_vah_equals_val_is_not_a_profile():
    """vah == val is a degenerate value area, not a real profile."""
    horizon = 32
    curr = 100.0
    p50 = np.linspace(curr, curr - 0.5, horizon)
    fc = TimesFMForecast(
        horizon=horizon, p50_path=p50, p10_path=p50 - 0.5, p90_path=p50 + 0.5,
        q_spread=1.0, mean_forecast=float(p50[-1]),
        pct_change=-0.0005, forecast_steps=["SHORT"] * horizon,
        curr_price=curr, lat_ms=1.0,
    )
    bar = Bar("2026-09-10T10:00:00", 100.0, 101.0, 99.0, 100.0, 100, 100)
    ctx = DecisionContext(
        symbol="NIFTY", bar=bar, bar_index=20, session_open=True,
        warmup_complete=True, session_phase="PRIMARY",
        poc=100.0, vah=100.0, val=100.0, cvd_slope=0.0, allow_reversion=True,
    )
    res = TimesFMScanningAgent(target_horizon=horizon).evaluate(ctx, fc)
    assert res["action"] == "FLAT", res
    assert res["reason"] == "NO_PROFILE", res
