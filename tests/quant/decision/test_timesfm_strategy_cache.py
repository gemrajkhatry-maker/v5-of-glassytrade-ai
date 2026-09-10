"""Task 4 (STRUCT-8): failed TimesFM inference must return None, not a synthetic flat forecast."""

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
