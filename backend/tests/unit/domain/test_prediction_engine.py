"""Unit tests for Prediction Engine domain service."""

import pytest
from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel
pytestmark = pytest.mark.skip(reason="Requires additional stubbed infrastructure — planned")
from app.domain.fabio_ai.models.predictions import ModelWeights
from app.domain.fabio_ai.services.prediction_engine import PredictionEngine
from app.infrastructure.adapters.data_generator import generate_market_data


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
