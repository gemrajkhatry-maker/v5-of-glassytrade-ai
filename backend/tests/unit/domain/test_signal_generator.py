"""Unit tests for Signal Generator domain service."""

import pytest
from app.domain.trading.models.enums import Sentiment, SignalType, Source, SetupType
from app.domain.trading.models.value_objects import (
    OHLC, AMTResult,
)
from app.domain.fabio_ai.models.predictions import AIAnalysisResult, FactorBreakdown
from app.domain.trading.models.entities import Signal
from app.domain.trading.services.signal_generator import SignalGenerator


class TestSignalGeneratorAMT:
    def test_no_signal_when_none(self):
        sg = SignalGenerator()
        result = AMTResult(
            market_state="BALANCED", poc=100,
            value_area_high=110, value_area_low=90,
        )
        assert sg.evaluate_amt(result) is None

    def test_extracts_signal(self):
        sg = SignalGenerator()
        signal = Signal(
            type=SignalType.BUY, price=100, reason="test",
            stop_loss=95, take_profit=110, timestamp="t",
            setup=SetupType.TREND_MODEL, source=Source.AMT,
        )
        result = AMTResult(
            market_state="IMBALANCED", poc=100,
            value_area_high=110, value_area_low=90,
            signal=signal,
        )
        extracted = sg.evaluate_amt(result)
        assert extracted == signal


class TestSignalGeneratorPrediction:
    def test_no_signal_low_confidence(self):
        sg = SignalGenerator()
        analysis = AIAnalysisResult(
            sentiment="BULLISH", confidence=40,
            long_term_trend="UP", volatility_score=0.02,
            quant_score=30, projected_price=105,
        )
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100)
        assert sg.evaluate_prediction(analysis, tick, 1) is None

    def test_no_signal_neutral(self):
        sg = SignalGenerator()
        analysis = AIAnalysisResult(
            sentiment="NEUTRAL", confidence=80,
            long_term_trend="SIDEWAYS", volatility_score=0.02,
            quant_score=10, projected_price=100,
        )
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100)
        assert sg.evaluate_prediction(analysis, tick, 1) is None

    def test_bullish_signal(self):
        sg = SignalGenerator()
        analysis = AIAnalysisResult(
            sentiment="BULLISH", confidence=80,
            long_term_trend="UP", volatility_score=0.02,
            quant_score=75, projected_price=110,
            factor_breakdown=FactorBreakdown(trend=30, momentum=20, delta=10, order_book=5),
        )
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100)
        signal = sg.evaluate_prediction(analysis, tick, 1)
        assert signal is not None
        assert signal.type == SignalType.BUY
        assert signal.source == Source.PREDICTION

    def test_bearish_signal(self):
        sg = SignalGenerator()
        analysis = AIAnalysisResult(
            sentiment="BEARISH", confidence=80,
            long_term_trend="DOWN", volatility_score=0.02,
            quant_score=-75, projected_price=90,
            factor_breakdown=FactorBreakdown(trend=-30, momentum=-20, delta=-10, order_book=-5),
        )
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100)
        signal = sg.evaluate_prediction(analysis, tick, 1)
        assert signal is not None
        assert signal.type == SignalType.SELL

    def test_metadata_includes_generation(self):
        sg = SignalGenerator()
        analysis = AIAnalysisResult(
            sentiment="BULLISH", confidence=90,
            long_term_trend="UP", volatility_score=0.02,
            quant_score=80, projected_price=110,
            factor_breakdown=FactorBreakdown(trend=30),
        )
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100)
        signal = sg.evaluate_prediction(analysis, tick, 5)
        assert signal.metadata["generation"] == 5
