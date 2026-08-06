"""Unit tests for Prediction Engine domain service.

Ported from backend/tests/unit/domain/test_prediction_engine.py. The original
is a pre-existing module-level skip (needs stubbed infra); the data generator
was swapped for a local OHLC helper to keep the port self-contained.
"""

import pytest
from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel
pytestmark = pytest.mark.skip(reason="Requires additional stubbed infrastructure — planned")
from quant.inference.models import ModelWeights
from quant.inference.prediction import PredictionEngine


def generate_market_data(count: int, start: float, bias: str) -> list[OHLC]:
    """Deterministic synthetic OHLC list with an optional price bias."""
    candles: list[OHLC] = []
    price = start
    for i in range(count):
        drift = {"bullish": 0.2, "bearish": -0.2}.get(bias, 0.0)
        price = start + i * drift
        candles.append(
            OHLC(
                time=f"2025-01-01T{9 + i // 60:02d}:{i % 60:02d}:00+00:00",
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
                volume=1000.0,
                vwap=price,
                taker_buy_volume=550.0,
                delta=10.0,
            )
        )
    return candles


class TestPredictionEngine:
    def setup_method(self):
        self.engine = PredictionEngine()
        self.weights = ModelWeights()

    def test_insufficient_data(self):
        data = [
            OHLC(time="t", open=100, high=101, low=99, close=100,
                 volume=1000, vwap=100)
            for _ in range(10)
        ]
        result = self.engine.predict(data, self.weights)
        assert result.analysis.sentiment == "NEUTRAL"
        assert result.analysis.confidence == 0

    def test_basic_prediction(self):
        data = generate_market_data(100, 100, "bullish")
        result = self.engine.predict(data, self.weights, 10)
        assert result.analysis is not None
        assert len(result.predictions) == 10
        assert result.analysis.projected_price > 0

    def test_bearish_data(self):
        data = generate_market_data(100, 100, "bearish")
        result = self.engine.predict(data, self.weights, 5)
        assert result.analysis is not None
        assert len(result.predictions) == 5

    def test_with_order_book(self):
        data = generate_market_data(100, 100, "sideways")
        ob = OrderBook(
            bids=(OrderBookLevel(price=100, quantity=5000),),
            asks=(OrderBookLevel(price=101, quantity=500),),
        )
        result = self.engine.predict(data, self.weights, 5, ob)
        assert result.analysis is not None

    def test_custom_weights(self):
        data = generate_market_data(100, 100, "bullish")
        w = ModelWeights(trend=0.8, momentum=0.05, delta=0.05,
                        order_book=0.05, volatility=0.05)
        result = self.engine.predict(data, w, 5)
        assert result.analysis is not None

    def test_ghost_candles_are_valid(self):
        data = generate_market_data(100, 100, "sideways")
        result = self.engine.predict(data, self.weights, 10)
        for gc in result.predictions:
            assert gc.high >= gc.low
            assert gc.volume > 0

    def test_reasoning_present(self):
        data = generate_market_data(100, 100, "bullish")
        result = self.engine.predict(data, self.weights, 5)
        assert len(result.analysis.reasoning) > 0
