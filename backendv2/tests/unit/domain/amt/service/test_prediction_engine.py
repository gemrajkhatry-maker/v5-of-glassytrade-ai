"""Tests for PredictionEngine — Deterministic prediction candles and AI analysis."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.amt.service.prediction_engine import PredictionEngine, _calculate_trend
from app.domain.trading.model.value_objects import OHLC, ModelWeights


def _make_ohlc(close, time_idx=0):
    total_minutes = 15 + time_idx * 5
    hour = 9 + total_minutes // 60
    minute = total_minutes % 60
    ts = datetime(2024, 1, 1, hour, minute, tzinfo=timezone.utc).isoformat()
    return OHLC.create(
        time=ts, open=close - 0.5, high=close + 1.0, low=close - 1.0,
        close=close, volume=1000.0, delta=10.0,
    )


def _make_weights(trend=0.40, momentum=0.25, delta=0.15, order_book=0.15):
    return ModelWeights(trend=trend, momentum=momentum, delta=delta, order_book=order_book)


class TestInsufficientData:
    """Tests for insufficient data handling."""

    def test_less_than_50_candles_returns_insufficient(self):
        """Less than 50 candles returns 'Insufficient Data' reasoning."""
        engine = PredictionEngine()
        data = [_make_ohlc(close=100.0 + i, time_idx=i) for i in range(30)]
        result = engine.predict(data, _make_weights())
        assert len(result.predictions) == 0
        assert result.analysis is not None
        assert "Insufficient Data" in result.analysis.reasoning

    def test_exactly_50_candles_succeeds(self):
        """50 candles is enough for prediction."""
        engine = PredictionEngine()
        data = [_make_ohlc(close=100.0 + i * 0.1, time_idx=i) for i in range(50)]
        result = engine.predict(data, _make_weights())
        assert len(result.predictions) > 0
        assert result.analysis is not None
        assert "Insufficient Data" not in result.analysis.reasoning


class TestTrendDirection:
    """Tests for trend direction calculation."""

    def test_upward_trend(self):
        """Consistent upward closes => UP trend."""
        data = [_make_ohlc(close=100.0 + i * 0.5, time_idx=i) for i in range(55)]
        from app.domain.trading.model.enums import TrendDirection
        direction, slope = _calculate_trend(data, period=50)
        assert direction == TrendDirection.UP

    def test_downward_trend(self):
        """Consistent downward closes => DOWN trend."""
        data = [_make_ohlc(close=110.0 - i * 0.5, time_idx=i) for i in range(55)]
        from app.domain.trading.model.enums import TrendDirection
        direction, slope = _calculate_trend(data, period=50)
        assert direction == TrendDirection.DOWN

    def test_sideways_trend(self):
        """Flat closes => SIDEWAYS trend."""
        data = [_make_ohlc(close=100.0, time_idx=i) for i in range(55)]
        from app.domain.trading.model.enums import TrendDirection
        direction, slope = _calculate_trend(data, period=50)
        assert direction == TrendDirection.SIDEWAYS

    def test_insufficient_data_for_trend(self):
        """Less than period candles => SIDEWAYS."""
        data = [_make_ohlc(close=100.0 + i, time_idx=i) for i in range(10)]
        from app.domain.trading.model.enums import TrendDirection
        direction, slope = _calculate_trend(data, period=50)
        assert direction == TrendDirection.SIDEWAYS


class TestPredictionGeneration:
    """Tests for prediction generation with known seed."""

    def test_prediction_count_matches_request(self):
        """Requested count of predictions is returned."""
        engine = PredictionEngine()
        data = [_make_ohlc(close=100.0 + i * 0.1, time_idx=i) for i in range(55)]
        result = engine.predict(data, _make_weights(), count=10)
        assert len(result.predictions) == 10

    def test_predictions_have_valid_ohlcv(self):
        """Each prediction candle has valid OHLCV fields."""
        engine = PredictionEngine()
        data = [_make_ohlc(close=100.0 + i * 0.1, time_idx=i) for i in range(55)]
        result = engine.predict(data, _make_weights(), count=5)
        for candle in result.predictions:
            assert float(candle.high) >= float(candle.low)
            assert float(candle.volume) > 0

    def test_deterministic_with_same_seed(self):
        """Same data produces same predictions (deterministic)."""
        engine = PredictionEngine()
        data = [_make_ohlc(close=100.0 + i * 0.1, time_idx=i) for i in range(55)]
        result1 = engine.predict(data, _make_weights(), count=5)
        result2 = engine.predict(data, _make_weights(), count=5)
        assert len(result1.predictions) == len(result2.predictions)
        for c1, c2 in zip(result1.predictions, result2.predictions):
            assert float(c1.close) == pytest.approx(float(c2.close))
            assert float(c1.high) == pytest.approx(float(c2.high))
            assert float(c1.low) == pytest.approx(float(c2.low))


class TestAIAnalysis:
    """Tests for AI analysis result."""

    def test_analysis_has_quant_score(self):
        """Analysis includes quant_score."""
        engine = PredictionEngine()
        data = [_make_ohlc(close=100.0 + i * 0.1, time_idx=i) for i in range(55)]
        result = engine.predict(data, _make_weights())
        assert result.analysis.quant_score is not None
        assert -100.0 <= result.analysis.quant_score <= 100.0

    def test_analysis_has_factor_breakdown(self):
        """Analysis includes factor breakdown."""
        engine = PredictionEngine()
        data = [_make_ohlc(close=100.0 + i * 0.1, time_idx=i) for i in range(55)]
        result = engine.predict(data, _make_weights())
        breakdown = result.analysis.factor_breakdown
        assert breakdown is not None
        assert hasattr(breakdown, "trend")
        assert hasattr(breakdown, "momentum")
        assert hasattr(breakdown, "delta")
