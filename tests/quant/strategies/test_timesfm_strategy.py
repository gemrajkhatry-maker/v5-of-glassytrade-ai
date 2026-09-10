"""Unit tests for TimesFMTradingStrategy end-to-end trade management."""

import numpy as np
import pytest
from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.decision_service import QuantDecision
from quant.decision.timesfm_agents import TimesFMForecast
from quant.execution.exits import ExitEngine
from quant.strategies.timesfm_strategy import TimesFMTradingStrategy
from quant.runtime import QuantEngine


@pytest.fixture
def bullish_forecast():
    horizon = 32
    curr_price = 8110.0
    p50 = np.linspace(curr_price, curr_price + 35.0, horizon)
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
        lat_ms=10.0,
    )


def test_should_enter_approves_triple_a_long(bullish_forecast):
    strategy = TimesFMTradingStrategy(target_horizon=32)
    # Mock _compute_forecast to return bullish_forecast
    strategy._compute_forecast = MagicMock(return_value=bullish_forecast)

    bar = Bar("2026-09-08T16:00:00", 8105.0, 8115.0, 8105.0, 8110.0, 2000, 400)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=8150.0,
        vah=8190.0,
        val=8109.0,
        cvd_slope=4.5,
        absorption_side="SELL_ABSORBED",
        agent_direction="LONG",
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        session_phase="PRIMARY",
        position_open=False,
    )

    decision = strategy.should_enter(ctx)
    assert isinstance(decision, QuantDecision)
    assert decision.approved is True
    assert decision.signal is not None
    assert decision.signal.type == "LONG"
    assert decision.signal.entry == 8110.0
    assert decision.signal.sl < 8110.0
    assert decision.signal.tp > 8110.0
    assert decision.signal.rr >= 1.0
    assert "TimesFM" in decision.model_label
    assert decision.signal.sl == decision.signal.sl
    assert strategy.get_latest_forecast("CRUDEOIL") == bullish_forecast


def test_should_enter_rejects_flat_market():
    strategy = TimesFMTradingStrategy(target_horizon=32)
    flat_forecast = TimesFMForecast(
        horizon=32,
        p50_path=np.full(32, 8110.0),
        p10_path=np.full(32, 8105.0),
        p90_path=np.full(32, 8115.0),
        q_spread=10.0,
        mean_forecast=8110.0,
        pct_change=0.0,
        forecast_steps=["FLAT"] * 32,
        curr_price=8110.0,
        lat_ms=5.0,
    )
    strategy._compute_forecast = MagicMock(return_value=flat_forecast)

    bar = Bar("2026-09-08T16:00:00", 8108.0, 8112.0, 8108.0, 8110.0, 500, 0)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=8110.0,
        vah=8140.0,
        val=8080.0,
        cvd_slope=0.0,
        session_phase="PRIMARY",
        position_open=False,
    )

    decision = strategy.should_enter(ctx)
    assert decision.approved is False
    assert decision.signal is None
    assert decision.reason in ("NO_EDGE", "FLAT")


def test_should_enter_blocks_on_risk_halt(bullish_forecast):
    strategy = TimesFMTradingStrategy(target_horizon=32)
    bar = Bar("2026-09-08T16:00:00", 8105.0, 8115.0, 8105.0, 8110.0, 2000, 400)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        risk_halted=True,
        position_open=False,
    )
    decision = strategy.should_enter(ctx)
    assert decision.approved is False
    assert decision.reason == "HALTED"


def test_quant_engine_initializes_timesfm_strategy(monkeypatch):
    monkeypatch.setenv("TIMESFM_END_TO_END", "true")
    engine = QuantEngine(gateway=MagicMock(), symbol="CRUDEOIL")
    assert isinstance(engine._strategy, TimesFMTradingStrategy)


def test_timesfm_strategy_reuses_runtime_exit_engine():
    from quant.execution.exits import ExitEngine

    shared_exit_engine = ExitEngine(time_stop_bars=7)
    strategy = TimesFMTradingStrategy(target_horizon=32, exit_engine=shared_exit_engine)
    assert strategy.exit_engine is shared_exit_engine


def test_timesfm_strategy_defaults_to_its_own_exit_engine():
    strategy = TimesFMTradingStrategy(target_horizon=32)
    exit_engine = strategy.exit_engine
    assert isinstance(exit_engine, ExitEngine)
    assert exit_engine.time_stop_bars == 32
    # Second access returns the same cached default, not a new object.
    assert strategy.exit_engine is exit_engine


def test_strategy_and_advisor_share_one_inference_per_bar(monkeypatch):
    """D-11: the advisor engine and the strategy each ran model.predict for the
    same bar, doubling latency and allowing the two payloads to disagree."""
    import numpy as np
    from unittest.mock import Mock

    import quant.decision.timesfm_engine as eng_mod
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.timesfm_engine import TimesFMEngine
    from quant.strategies.timesfm_strategy import TimesFMTradingStrategy

    horizon = 8
    p50 = np.linspace(100.0, 103.0, horizon, dtype=np.float32)
    q = np.zeros((horizon, 9), dtype=np.float32)
    q[:, 0] = p50 - 0.5
    q[:, 4] = p50
    q[:, 8] = p50 + 0.5
    fake = Mock()
    fake.predict.return_value = Mock(quantiles=q)

    engine = TimesFMEngine(target_horizon=horizon)
    original = eng_mod.get_timesfm_model
    eng_mod.get_timesfm_model = lambda *a, **k: fake
    try:
        strategy = TimesFMTradingStrategy(target_horizon=horizon, engine=engine)
        bar = Bar("2026-09-10T10:00:00+05:30", 100.0, 101.0, 99.0, 100.0, 100, 100)
        ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=7,
                              session_open=True, warmup_complete=True,
                              session_phase="PRIMARY", poc=101.0, vah=101.5,
                              val=99.0, cvd_slope=1.0)
        engine.analyze(ctx)            # advisor consumer
        strategy.should_enter(ctx)     # decision consumer, same bar
    finally:
        eng_mod.get_timesfm_model = original

    assert fake.predict.call_count == 1, (
        f"expected one inference per bar, got {fake.predict.call_count}"
    )
