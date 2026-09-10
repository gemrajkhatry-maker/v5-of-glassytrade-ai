"""Task 12: failed TimesFM inference must return None, not a synthetic flat forecast."""

from __future__ import annotations

from unittest.mock import patch

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.strategies.timesfm_strategy import TimesFMTradingStrategy


def _make_ctx(symbol: str = "NIFTY") -> DecisionContext:
    bar = Bar(
        time="2026-09-10T10:00:00+05:30",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=2000.0,
        buy_volume=1200.0,
        sell_volume=800.0,
    )
    return DecisionContext(symbol=symbol, bar=bar, session_phase="PRIMARY")


def test_failed_inference_returns_model_unavailable_and_caches_nothing():
    strategy = TimesFMTradingStrategy()
    ctx = _make_ctx()
    with patch(
        "quant.decision.timesfm_engine.get_timesfm_model",
        side_effect=RuntimeError("inference boom"),
    ):
        decision = strategy.should_enter(ctx)
    assert decision.reason == "MODEL_UNAVAILABLE"
    assert strategy.get_latest_forecast("NIFTY") is None


def test_no_phantom_allow_entry_gate():
    import inspect

    from quant.decision import timesfm_agents

    src = inspect.getsource(timesfm_agents)
    assert "allow_entry" not in src


def _make_forecast(asof_bar: int):
    import numpy as np

    from quant.decision.timesfm_agents import TimesFMForecast

    return TimesFMForecast(
        horizon=32,
        p50_path=np.full(32, 101.0, dtype=np.float32),
        p10_path=np.full(32, 100.0, dtype=np.float32),
        p90_path=np.full(32, 102.0, dtype=np.float32),
        q_spread=2.0,
        mean_forecast=101.0,
        pct_change=0.01,
        forecast_steps=["LONG"] * 32,
        curr_price=100.0,
        lat_ms=5.0,
        asof_bar=asof_bar,
    )


def _run_manage_exit_capture(strategy, bar_index: int):
    from unittest.mock import MagicMock

    from quant.runtime import QuantEngine

    eng = QuantEngine(gateway=MagicMock(), symbol="NIFTY", strategy=strategy)
    eng._bar_index = bar_index
    captured: dict = {}
    pm = eng._get_position_manager()

    def fake_manage_exit(**kwargs):
        captured.update(kwargs)
        return None

    pm.manage_exit = fake_manage_exit
    eng._manage_exit(amt_dto={}, bar=_make_ctx().bar)
    return captured


def test_stale_forecast_not_used_for_exits():
    strategy = TimesFMTradingStrategy()
    strategy._latest_forecasts["NIFTY"] = _make_forecast(asof_bar=10)
    captured = _run_manage_exit_capture(strategy, bar_index=13)  # 3 bars stale
    assert captured.get("timesfm_forecast") is None


def test_fresh_forecast_reaches_exits():
    strategy = TimesFMTradingStrategy()
    fresh = _make_forecast(asof_bar=12)
    strategy._latest_forecasts["NIFTY"] = fresh
    captured = _run_manage_exit_capture(strategy, bar_index=13)  # 1 bar old: fresh
    assert captured.get("timesfm_forecast") is fresh


def test_non_int_asof_bar_passes_through_as_fresh():
    """Regression: a forecast whose asof_bar cannot be compared/coerced to an
    int (e.g. a MagicMock from an unstubbed attribute) must not crash the
    freshness check — it is treated as untracked and passes through."""
    from types import SimpleNamespace

    strategy = TimesFMTradingStrategy()
    weird = SimpleNamespace(asof_bar=object())  # int() raises TypeError
    strategy._latest_forecasts["NIFTY"] = weird
    captured = _run_manage_exit_capture(strategy, bar_index=13)
    assert captured.get("timesfm_forecast") is weird
