"""Tests for Multi-Timeframe AMT Analyzer — P0-2 implementation."""

from __future__ import annotations

import pytest
from dataclasses import dataclass

from app.domain.fabio_ai.services.multi_timeframe_amt import (
    MultiTimeframeAMTAnalyzer,
    AlignmentState,
    _derive_bias,
    _compute_alignment,
    _position_size_multiplier,
    _aggregate_chunk,
)


@dataclass
class MockAMTResult:
    """Mock AMTResult for testing."""

    market_state: str = "BALANCED"
    poc: float = 24800.0
    value_area_high: float = 24900.0
    value_area_low: float = 24700.0
    cvd_slope: float = 0.0
    aggression: float = 0.0
    poc_signal: str = ""


@dataclass
class MockOHLC:
    """Mock OHLC candle."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    taker_buy_volume: float = 0.0
    delta: float = 0.0


class TestDeriveBias:
    """Tests for directional bias derivation from AMTResult."""

    def test_bullish_bias(self):
        """Strong bullish signals = BULLISH bias."""
        result = MockAMTResult(
            market_state="IMBALANCED",
            cvd_slope=50.0,
            aggression=3.0,
            poc_signal="POC_RISING_BULLISH",
        )
        assert _derive_bias(result) == "BULLISH"

    def test_bearish_bias(self):
        """Strong bearish signals = BEARISH bias."""
        result = MockAMTResult(
            market_state="IMBALANCED",
            cvd_slope=-50.0,
            aggression=-3.0,
            poc_signal="POC_FALLING_BEARISH",
        )
        bias = _derive_bias(result)
        assert "BEARISH" in bias

    def test_strong_bearish_bias(self):
        """Very strong bearish signals = BEARISH bias (score <= -3)."""
        result = MockAMTResult(
            market_state="PROBING",
            cvd_slope=-50.0,
            aggression=-3.0,
            poc_signal="POC_FALLING_BEARISH",
        )
        # PROBING=+1, cvd=-2, aggression=-1, poc_signal=-1 = -3
        assert _derive_bias(result) == "BEARISH"

    def test_neutral_bias(self):
        """Mixed signals = NEUTRAL bias."""
        result = MockAMTResult(
            market_state="BALANCED",
            cvd_slope=0.0,
            aggression=0.0,
        )
        assert _derive_bias(result) == "NEUTRAL"

    def test_slightly_bullish(self):
        """Weak bullish signals = SLIGHTLY_BULLISH."""
        result = MockAMTResult(
            market_state="BALANCED",
            cvd_slope=5.0,
            aggression=0.5,
        )
        assert _derive_bias(result) == "SLIGHTLY_BULLISH"

    def test_invalid_result(self):
        """Invalid AMTResult = NEUTRAL."""
        result = MockAMTResult(poc=0.0)
        assert _derive_bias(result) == "NEUTRAL"


class TestComputeAlignment:
    """Tests for three-timeframe alignment computation."""

    def test_all_aligned_long(self):
        """All three timeframes bullish = ALIGNED_LONG."""
        state, strength = _compute_alignment("BULLISH", "BULLISH", "BULLISH")
        assert state == AlignmentState.ALIGNED_LONG
        assert strength == 1.0

    def test_all_aligned_short(self):
        """All three timeframes bearish = ALIGNED_SHORT."""
        state, strength = _compute_alignment("BEARISH", "BEARISH", "BEARISH")
        assert state == AlignmentState.ALIGNED_SHORT
        assert strength == 1.0

    def test_two_bullish_one_neutral(self):
        """Two bullish + one neutral = ALIGNED_LONG with reduced strength."""
        state, strength = _compute_alignment("BULLISH", "BULLISH", "NEUTRAL")
        assert state == AlignmentState.ALIGNED_LONG
        assert strength == 0.7

    def test_two_bearish_one_neutral(self):
        """Two bearish + one neutral = ALIGNED_SHORT with reduced strength."""
        state, strength = _compute_alignment("BEARISH", "NEUTRAL", "BEARISH")
        assert state == AlignmentState.ALIGNED_SHORT
        assert strength == 0.7

    def test_conflicted_higher_bearish(self):
        """Higher bearish, others bullish = CONFLICTED."""
        state, strength = _compute_alignment("BEARISH", "BULLISH", "BULLISH")
        assert state == AlignmentState.CONFLICTED
        assert strength == 0.3

    def test_higher_bullish_dominant(self):
        """Higher bullish, others neutral = HIGHER_BULLISH."""
        state, strength = _compute_alignment("BULLISH", "NEUTRAL", "NEUTRAL")
        assert state == AlignmentState.HIGHER_BULLISH
        assert strength == 0.4

    def test_all_neutral(self):
        """All neutral = NEUTRAL."""
        state, strength = _compute_alignment("NEUTRAL", "NEUTRAL", "NEUTRAL")
        assert state == AlignmentState.NEUTRAL
        assert strength == 0.0


class TestPositionSizeMultiplier:
    """Tests for position size calculation based on alignment."""

    def test_full_alignment(self):
        assert _position_size_multiplier(AlignmentState.ALIGNED_LONG, 1.0) == 1.0
        assert _position_size_multiplier(AlignmentState.ALIGNED_SHORT, 1.0) == 1.0

    def test_partial_alignment(self):
        assert _position_size_multiplier(AlignmentState.ALIGNED_LONG, 0.7) == 0.7

    def test_higher_tf_only(self):
        assert _position_size_multiplier(AlignmentState.HIGHER_BULLISH, 0.4) == 0.5

    def test_conflicted(self):
        assert _position_size_multiplier(AlignmentState.CONFLICTED, 0.3) == 0.0

    def test_neutral(self):
        assert _position_size_multiplier(AlignmentState.NEUTRAL, 0.0) == 0.0


class TestMultiTimeframeAMTAnalyzer:
    """Tests for the full analyzer."""

    def test_compute_alignment_with_session_result(self):
        """Full analysis with session result and biases."""
        analyzer = MultiTimeframeAMTAnalyzer()
        session_result = MockAMTResult(
            market_state="IMBALANCED",
            cvd_slope=30.0,
            aggression=2.5,
        )
        result = analyzer.compute_alignment(
            session_tf_result=session_result,
            higher_tf_bias="BULLISH",
            entry_tf_bias="BULLISH",
        )
        assert "ALIGNED_LONG" in result.alignment
        assert result.allow_entries is True
        assert result.position_size_multiplier >= 0.7
        assert len(result.thesis) > 0

    def test_conflicted_blocks_entries(self):
        """Conflicted alignment blocks entries."""
        # 2 bullish + 1 bearish with higher TF bearish = CONFLICTED
        alignment, strength = _compute_alignment("BEARISH", "BULLISH", "BULLISH")
        assert alignment == AlignmentState.CONFLICTED
        assert _position_size_multiplier(alignment, strength) == 0.0

    def test_thesis_generated(self):
        """Thesis is always generated."""
        analyzer = MultiTimeframeAMTAnalyzer()
        session_result = MockAMTResult()
        result = analyzer.compute_alignment(
            session_tf_result=session_result,
            higher_tf_bias="NEUTRAL",
            entry_tf_bias="NEUTRAL",
        )
        assert len(result.thesis) > 10


class TestCandleAggregation:
    """Tests for candle aggregation to higher timeframes."""

    def test_aggregates_chunk(self):
        """Multiple candles aggregate into one with correct OHLC."""
        candles = [
            MockOHLC("09:00", 100, 110, 95, 105, 100, delta=10),
            MockOHLC("09:01", 105, 115, 100, 110, 100, delta=15),
            MockOHLC("09:02", 110, 120, 105, 115, 100, delta=20),
        ]
        agg = _aggregate_chunk(candles)
        assert agg is not None
        assert float(agg.open) == 100  # First open
        assert float(agg.close) == 115  # Last close
        assert float(agg.high) == 120  # Max high
        assert float(agg.low) == 95  # Min low
        assert float(agg.volume) == 300  # Sum of volumes

    def test_empty_chunk(self):
        """Empty chunk returns None."""
        assert _aggregate_chunk([]) is None

    def test_analyzer_configs(self):
        """Default timeframe configs are reasonable."""
        analyzer = MultiTimeframeAMTAnalyzer()
        assert analyzer.higher_tf_config.candle_interval_minutes == 60
        assert analyzer.higher_tf_config.lookback_candles == 50
        assert analyzer.entry_tf_config.candle_interval_minutes == 1
        assert analyzer.entry_tf_config.lookback_candles == 30
