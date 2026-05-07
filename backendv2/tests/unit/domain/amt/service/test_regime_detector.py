"""Tests for RegimeDetector — LLM triggers, contraction, failed entries,
circuit breaker, second drive, squeeze, and follow-through analysis."""

from __future__ import annotations

import time
from dataclasses import replace
from unittest.mock import patch

import pytest

from app.domain.amt.service.regime_detector import (
    ContractionConfig,
    RegimeDetector,
    SqueezeSignal,
)
from app.domain.trading.model.value_objects import AMTResult, OHLC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlc(
    close: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    open_price: float = 100.0,
    delta: float = 0.0,
    volume: float = 1000.0,
    time: str = "2024-01-01T00:00:00",
) -> OHLC:
    return OHLC.create(
        time=time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        delta=delta,
    )


def _float_ohlc(ohlc: OHLC) -> OHLC:
    """Create an OHLC with float values instead of Decimal (for tests that need arithmetic)."""
    return OHLC(
        time=ohlc.time,
        open=float(ohlc.open),
        high=float(ohlc.high),
        low=float(ohlc.low),
        close=float(ohlc.close),
        volume=float(ohlc.volume),
        vwap=float(ohlc.vwap),
        taker_buy_volume=float(ohlc.taker_buy_volume),
        delta=float(ohlc.delta),
    )


def _make_amt(
    market_state: str = "BALANCED",
    poc: float = 100.0,
    vah: float = 105.0,
    val: float = 95.0,
) -> AMTResult:
    return AMTResult(
        market_state=market_state,
        poc=poc,
        value_area_high=vah,
        value_area_low=val,
    )


def _make_contracting_candles(
    expansion_range: float = 10.0,
    contraction_ratio: float = 0.2,
    base_price: float = 100.0,
    count: int = 40,
) -> list[OHLC]:
    """Create candles: first half expanding, second half contracting."""
    candles = []
    half = count // 2
    exp_high = base_price + expansion_range
    exp_low = base_price

    # Expansion window
    for i in range(half):
        progress = i / half
        h = exp_low + (exp_high - exp_low) * progress
        l = exp_low + (exp_high - exp_low) * (progress * 0.5)
        candles.append(_make_ohlc(
            close=(h + l) / 2, high=h, low=l, time=f"2024-01-01T{i:02d}:00:00",
        ))

    # Contraction window
    cur_range = expansion_range * contraction_ratio
    for i in range(half):
        candles.append(_make_ohlc(
            close=base_price + cur_range / 2,
            high=base_price + cur_range,
            low=base_price,
            time=f"2024-01-01T{half + i:02d}:00:00",
        ))

    return candles


# ---------------------------------------------------------------------------
# 1. should_trigger_llm() — LLM trigger conditions
# ---------------------------------------------------------------------------

class TestShouldTriggerLLM:
    def test_first_observation_triggers(self):
        detector = RegimeDetector()
        tick = _float_ohlc(_make_ohlc(close=100.0))
        amt = _make_amt()
        assert detector.should_trigger_llm(tick, amt, current_time=1000.0) is True

    def test_no_trigger_without_change(self):
        detector = RegimeDetector()
        tick = _float_ohlc(_make_ohlc(close=100.0))
        amt = _make_amt()
        detector.should_trigger_llm(tick, amt, current_time=1000.0)

        tick2 = _float_ohlc(_make_ohlc(close=100.1, delta=0.0, time="2024-01-01T00:01:00"))
        assert detector.should_trigger_llm(tick2, amt, current_time=1006.0) is False

    def test_state_transition_triggers(self):
        detector = RegimeDetector()
        tick = _float_ohlc(_make_ohlc(close=100.0))
        amt_balanced = _make_amt(market_state="BALANCED")
        detector.should_trigger_llm(tick, amt_balanced, current_time=1000.0)

        tick2 = _float_ohlc(_make_ohlc(close=100.1, time="2024-01-01T00:01:00"))
        amt_imbalanced = _make_amt(market_state="IMBALANCED")
        assert detector.should_trigger_llm(tick2, amt_imbalanced, current_time=1006.0) is True

    def test_zone_change_triggers(self):
        """Price crosses VA boundary — zone changes from INSIDE_VA to ABOVE_VAH."""
        detector = RegimeDetector()
        tick = _float_ohlc(_make_ohlc(close=100.0))  # inside VA (95-105)
        amt = _make_amt(vah=105.0, val=95.0, poc=100.0)
        detector.should_trigger_llm(tick, amt, current_time=1000.0)

        tick2 = _float_ohlc(_make_ohlc(close=106.0, time="2024-01-01T00:01:00"))  # above VAH
        assert detector.should_trigger_llm(tick2, amt, current_time=1006.0) is True

    def test_poc_migration_triggers(self):
        """POC moves > 0.2% triggers LLM."""
        detector = RegimeDetector()
        tick = _float_ohlc(_make_ohlc(close=100.0))
        amt = _make_amt(poc=100.0, vah=105.0, val=95.0)
        detector.should_trigger_llm(tick, amt, current_time=1000.0)

        # POC moved from 100 to 100.3 = 0.3% > 0.2% threshold
        tick2 = _float_ohlc(_make_ohlc(close=100.3, time="2024-01-01T00:01:00"))
        amt2 = _make_amt(poc=100.3, vah=105.0, val=95.0)
        assert detector.should_trigger_llm(tick2, amt2, current_time=1006.0) is True

    def test_delta_divergence_spike_triggers(self):
        """Delta spike > 3x average triggers LLM."""
        detector = RegimeDetector()
        amt = _make_amt()

        # Build up delta history with small deltas
        for i in range(6):
            tick = _float_ohlc(_make_ohlc(close=100.0 + i * 0.1, delta=10.0,
                              time=f"2024-01-01T00:{i:02d}:00"))
            detector.should_trigger_llm(tick, amt, current_time=1000.0 + i * 6)

        # Spike: delta = 100 (vs avg ~10, multiplier 3x = 30)
        tick_spike = _float_ohlc(_make_ohlc(close=100.6, delta=100.0, time="2024-01-01T00:06:00"))
        assert detector.should_trigger_llm(tick_spike, amt, current_time=1036.0) is True

    def test_cooldown_prevents_rapid_retrigger(self):
        """Within 5s cooldown, no trigger even with state change."""
        detector = RegimeDetector()
        tick = _float_ohlc(_make_ohlc(close=100.0))
        amt = _make_amt(market_state="BALANCED")
        detector.should_trigger_llm(tick, amt, current_time=1000.0)

        # State change but only 3 seconds later
        tick2 = _float_ohlc(_make_ohlc(close=100.1, time="2024-01-01T00:01:00"))
        amt2 = _make_amt(market_state="IMBALANCED")
        assert detector.should_trigger_llm(tick2, amt2, current_time=1003.0) is False


# ---------------------------------------------------------------------------
# 2. is_contracting() — Rule 8 contraction detection
# ---------------------------------------------------------------------------

class TestIsContracting:
    def test_contracting_market(self):
        detector = RegimeDetector()
        candles = _make_contracting_candles(
            expansion_range=10.0, contraction_ratio=0.2, base_price=100.0,
        )
        assert detector.is_contracting(candles, lookback=20) is True

    def test_expanding_market(self):
        """When current range > 30% of expansion, not contracting."""
        detector = RegimeDetector()
        candles = _make_contracting_candles(
            expansion_range=10.0, contraction_ratio=0.8, base_price=100.0,
        )
        assert detector.is_contracting(candles, lookback=20) is False

    def test_insufficient_data_returns_false(self):
        detector = RegimeDetector()
        candles = [_make_ohlc(close=100.0, time=f"2024-01-01T{i:02d}:00:00") for i in range(10)]
        assert detector.is_contracting(candles, lookback=20) is False

    def test_zero_expansion_edge_case(self):
        """All candles same price in expansion window => no contraction."""
        detector = RegimeDetector()
        candles = [_make_ohlc(close=100.0, high=100.0, low=100.0,
                               time=f"2024-01-01T{i:02d}:00:00") for i in range(40)]
        assert detector.is_contracting(candles, lookback=20) is False


# ---------------------------------------------------------------------------
# 3. Failed entry blocking (Rule 11)
# ---------------------------------------------------------------------------

class TestFailedEntryBlocking:
    def test_same_direction_blocked(self):
        detector = RegimeDetector()
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        assert detector.is_re_entry_blocked(level=100.0, direction="LONG",
                                             session_phase=1) is True

    def test_different_direction_not_blocked(self):
        detector = RegimeDetector()
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        assert detector.is_re_entry_blocked(level=100.0, direction="SHORT",
                                             session_phase=1) is False

    def test_different_session_phase_not_blocked(self):
        detector = RegimeDetector()
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        assert detector.is_re_entry_blocked(level=100.0, direction="LONG",
                                             session_phase=2) is False

    def test_atr_buffer_override(self):
        """ATR buffer widens the blocking zone."""
        detector = RegimeDetector()
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        # ATR=3 > 1.5% of 100 (=1.5), so buffer = 3
        assert detector.is_re_entry_blocked(level=101.0, direction="LONG",
                                             session_phase=1, atr=3.0) is True

    def test_outside_buffer_not_blocked(self):
        detector = RegimeDetector()
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        # 102 is > 1.5% away from 100 (buffer = 1.5)
        assert detector.is_re_entry_blocked(level=102.0, direction="LONG",
                                             session_phase=1) is False


# ---------------------------------------------------------------------------
# 4. Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_three_consecutive_stops_triggers(self):
        detector = RegimeDetector()
        with patch("time.time", return_value=1000.0):
            detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
            detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
            detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        # Should be active
        assert detector.is_circuit_breaker_active(current_time=1001.0) is True

    def test_expiry_resets_blocking(self):
        detector = RegimeDetector()
        with patch("time.time", return_value=1000.0):
            for _ in range(3):
                detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)

        # After expiry (900s later), should not be active
        assert detector.is_circuit_breaker_active(current_time=2000.0) is False

    def test_successful_exit_resets_counter(self):
        detector = RegimeDetector()
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        detector.record_successful_exit()
        # Now only need one more to trigger, but circuit breaker not yet active
        assert detector.is_circuit_breaker_active(current_time=time.time() + 1) is False

    def test_active_check_returns_correct_state(self):
        detector = RegimeDetector()
        # Not triggered yet
        assert detector.is_circuit_breaker_active(current_time=1000.0) is False

        with patch("time.time", return_value=1000.0):
            for _ in range(3):
                detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)

        # Within cooldown window
        assert detector.is_circuit_breaker_active(current_time=1001.0) is True


# ---------------------------------------------------------------------------
# 5. Second drive tracking
# ---------------------------------------------------------------------------

class TestSecondDrive:
    def test_approach_retreat_reapproach_detects_second_drive(self):
        detector = RegimeDetector()
        key_levels = [100.0]

        # First approach
        detector.record_level_approach(price=100.2, key_levels=key_levels, timestamp=1000.0)
        # Retreat (price > 0.5% away)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=1001.0)
        # Re-approach
        detector.record_level_approach(price=100.2, key_levels=key_levels, timestamp=1002.0)

        assert detector.is_second_drive(price=100.2, key_levels=key_levels) is True

    def test_no_touch_means_no_second_drive(self):
        detector = RegimeDetector()
        key_levels = [100.0]
        # Never approached before
        assert detector.is_second_drive(price=100.2, key_levels=key_levels) is False

    def test_approach_without_retreat_not_second_drive(self):
        """Must have retreated before re-approach counts as second drive."""
        detector = RegimeDetector()
        key_levels = [100.0]
        detector.record_level_approach(price=100.2, key_levels=key_levels, timestamp=1000.0)
        # Still near level, never retreated
        assert detector.is_second_drive(price=100.2, key_levels=key_levels) is False

    def test_second_drive_requires_proximity_on_reapproach(self):
        detector = RegimeDetector()
        key_levels = [100.0]
        detector.record_level_approach(price=100.2, key_levels=key_levels, timestamp=1000.0)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=1001.0)
        # Far from level on re-approach
        assert detector.is_second_drive(price=105.0, key_levels=key_levels) is False


# ---------------------------------------------------------------------------
# 6. Squeeze detection
# ---------------------------------------------------------------------------

class TestSqueezeDetection:
    def test_long_squeeze(self):
        """Price broke below VAL then recovered above it during contraction."""
        detector = RegimeDetector()
        val = 95.0
        amt = _make_amt(val=val, vah=105.0, poc=100.0)

        # Build candles: first 20 expanding (range ~20), last 20 contracting (range ~2)
        candles = []
        # Expansion window: large range
        for i in range(20):
            candles.append(_make_ohlc(
                close=90.0 + i * 1.0, high=100.0 + i * 0.5, low=80.0 + i * 0.5,
                time=f"2024-01-01T{i:02d}:00:00",
            ))
        # Contraction window: small range around 95
        for i in range(20):
            candles.append(_make_ohlc(
                close=95.0 + i * 0.05, high=96.0, low=94.0,
                time=f"2024-01-01T{20 + i:02d}:00:00",
            ))

        # Modify last 5 for squeeze pattern
        candles[-5] = _make_ohlc(close=95.0, low=94.0, high=96.0,
                                  time=candles[-5].time)
        candles[-4] = _make_ohlc(close=95.5, low=94.2, high=96.5,
                                  time=candles[-4].time)
        candles[-3] = _make_ohlc(close=95.5, low=94.5, high=96.5,
                                  time=candles[-3].time)
        candles[-2] = _make_ohlc(close=95.5, low=95.0, high=96.5,
                                  time=candles[-2].time)
        candles[-1] = _make_ohlc(close=96.0, low=95.5, high=97.0,
                                  time=candles[-1].time)

        candles = [_float_ohlc(c) for c in candles]
        assert detector.is_contracting(candles) is True
        result = detector.detect_squeeze(candles, amt)
        assert result is not None
        assert result.direction == "LONG"
        assert result.trapped_level == val

    def test_short_squeeze(self):
        """Price broke above VAH then recovered below it during contraction."""
        detector = RegimeDetector()
        vah = 105.0
        amt = _make_amt(val=95.0, vah=vah, poc=100.0)

        # Build candles: first 20 expanding, last 20 contracting
        candles = []
        for i in range(20):
            candles.append(_make_ohlc(
                close=100.0 + i * 1.0, high=110.0 + i * 0.5, low=90.0 + i * 0.5,
                time=f"2024-01-01T{i:02d}:00:00",
            ))
        for i in range(20):
            candles.append(_make_ohlc(
                close=105.0 + i * 0.05, high=106.0, low=104.0,
                time=f"2024-01-01T{20 + i:02d}:00:00",
            ))

        # Modify last 5 for squeeze pattern
        candles[-5] = _make_ohlc(close=105.0, high=106.0, low=104.0,
                                  time=candles[-5].time)
        candles[-4] = _make_ohlc(close=105.5, high=106.2, low=104.5,
                                  time=candles[-4].time)
        candles[-3] = _make_ohlc(close=105.5, high=106.0, low=104.8,
                                  time=candles[-3].time)
        candles[-2] = _make_ohlc(close=105.2, high=105.8, low=104.5,
                                  time=candles[-2].time)
        candles[-1] = _make_ohlc(close=104.0, high=105.0, low=103.0,
                                  time=candles[-1].time)

        candles = [_float_ohlc(c) for c in candles]
        assert detector.is_contracting(candles) is True
        result = detector.detect_squeeze(candles, amt)
        assert result is not None
        assert result.direction == "SHORT"

    def test_no_squeeze_when_not_contracting(self):
        detector = RegimeDetector()
        amt = _make_amt(val=95.0, vah=105.0, poc=100.0)
        # Expanding candles, not contracting
        candles = _make_contracting_candles(
            expansion_range=10.0, contraction_ratio=0.8, base_price=100.0,
        )
        assert detector.detect_squeeze(candles, amt) is None

    def test_squeeze_requires_contraction(self):
        """Without contraction setup, squeeze returns None."""
        detector = RegimeDetector()
        amt = _make_amt(val=95.0, vah=105.0, poc=100.0)
        candles = [_make_ohlc(close=100.0, time=f"2024-01-01T{i:02d}:00:00") for i in range(5)]
        assert detector.detect_squeeze(candles, amt) is None  # insufficient data

    def test_squeeze_with_invalid_val(self):
        detector = RegimeDetector()
        amt = _make_amt(val=0.0, vah=105.0, poc=100.0)
        candles = _make_contracting_candles(expansion_range=10.0, contraction_ratio=0.2)
        assert detector.detect_squeeze(candles, amt) is None


# ---------------------------------------------------------------------------
# 7. Bollinger squeeze detection
# ---------------------------------------------------------------------------

class TestBollingerSqueeze:
    def test_bollinger_squeeze_detected(self):
        """Narrow BB width < 10% = squeeze."""
        detector = RegimeDetector()
        # Create candles with very tight range (low volatility)
        candles = [
            _float_ohlc(_make_ohlc(close=100.0 + i * 0.01, high=100.05, low=99.95,
                        time=f"2024-01-01T{i:02d}:00:00"))
            for i in range(20)
        ]
        assert detector.detect_bollinger_squeeze(candles, period=20) is True

    def test_no_bollinger_squeeze_with_high_volatility(self):
        """Wide BB width > 10% = no squeeze."""
        detector = RegimeDetector()
        # Create candles with wide range (high volatility)
        candles = [
            _float_ohlc(_make_ohlc(close=100.0 + i * 2.0, high=105.0 + i * 2.0, low=95.0 + i * 2.0,
                        time=f"2024-01-01T{i:02d}:00:00"))
            for i in range(20)
        ]
        assert detector.detect_bollinger_squeeze(candles, period=20) is False

    def test_insufficient_data_returns_false(self):
        detector = RegimeDetector()
        candles = [_float_ohlc(_make_ohlc(close=100.0, time=f"2024-01-01T{i:02d}:00:00")) for i in range(5)]
        assert detector.detect_bollinger_squeeze(candles, period=20) is False

    def test_zero_sma_handling(self):
        detector = RegimeDetector()
        candles = [
            _float_ohlc(_make_ohlc(close=0.0, high=0.0, low=0.0,
                        time=f"2024-01-01T{i:02d}:00:00"))
            for i in range(20)
        ]
        assert detector.detect_bollinger_squeeze(candles, period=20) is False


# ---------------------------------------------------------------------------
# 8. ATR compression detection
# ---------------------------------------------------------------------------

class TestATRCompression:
    def test_atr_compression_detected(self):
        """Current ATR < 50% of prior ATR."""
        detector = RegimeDetector()
        candles = []

        # First 20 candles: high volatility (ATR ~10)
        for i in range(20):
            candles.append(_float_ohlc(_make_ohlc(
                close=100.0, high=110.0, low=90.0,
                time=f"2024-01-01T{i:02d}:00:00",
            )))

        # Next 20 candles: low volatility (ATR ~2)
        for i in range(20, 40):
            candles.append(_float_ohlc(_make_ohlc(
                close=100.0, high=101.0, low=99.0,
                time=f"2024-01-01T{i:02d}:00:00",
            )))

        assert detector.is_atr_compressed(candles, lookback=20) is True

    def test_no_atr_compression(self):
        """Volatility didn't decrease."""
        detector = RegimeDetector()
        candles = [
            _float_ohlc(_make_ohlc(close=100.0, high=105.0, low=95.0,
                        time=f"2024-01-01T{i:02d}:00:00"))
            for i in range(40)
        ]
        # Same volatility in both windows
        assert detector.is_atr_compressed(candles, lookback=20) is False

    def test_insufficient_data_for_atr(self):
        detector = RegimeDetector()
        candles = [_float_ohlc(_make_ohlc(close=100.0, time=f"2024-01-01T{i:02d}:00:00")) for i in range(10)]
        assert detector.is_atr_compressed(candles, lookback=20) is False

    def test_zero_prior_atr(self):
        """Prior window has zero range => can't compress."""
        detector = RegimeDetector()
        candles = []
        # Prior 20: all same price
        for i in range(20):
            candles.append(_float_ohlc(_make_ohlc(close=100.0, high=100.0, low=100.0,
                                       time=f"2024-01-01T{i:02d}:00:00")))
        # Current 20: some range
        for i in range(20, 40):
            candles.append(_float_ohlc(_make_ohlc(close=100.0, high=101.0, low=99.0,
                                       time=f"2024-01-01T{i:02d}:00:00")))
        assert detector.is_atr_compressed(candles, lookback=20) is False


# ---------------------------------------------------------------------------
# 9. Follow-through analysis
# ---------------------------------------------------------------------------

class TestFollowThroughAnalysis:
    def test_continuation_pattern(self):
        """Price continues in break direction after bubble break."""
        detector = RegimeDetector()
        candles = [
            _make_ohlc(close=95.0, time="2024-01-01T00:00:00"),
            _make_ohlc(close=96.0, time="2024-01-01T00:01:00"),
            _make_ohlc(close=97.0, time="2024-01-01T00:02:00"),
            _make_ohlc(close=98.0, time="2024-01-01T00:03:00"),  # post_break[0]
            _make_ohlc(close=99.0, time="2024-01-01T00:04:00"),  # post_break[1]
            _make_ohlc(close=100.0, time="2024-01-01T00:05:00"), # post_break[2], current
        ]
        result = detector.analyze_follow_through(candles, "LONG", break_level=97.0)
        assert result is not None
        assert result["outcome"] == "CONTINUATION"
        assert result["strength"] == 0.8

    def test_reversal_pattern(self):
        """Price reverses back through break level."""
        detector = RegimeDetector()
        candles = [
            _make_ohlc(close=95.0, time="2024-01-01T00:00:00"),
            _make_ohlc(close=96.0, time="2024-01-01T00:01:00"),
            _make_ohlc(close=97.0, time="2024-01-01T00:02:00"),
            _make_ohlc(close=98.0, time="2024-01-01T00:03:00"),  # post_break[0]
            _make_ohlc(close=96.0, low=96.0, time="2024-01-01T00:04:00"),  # went below 97
            _make_ohlc(close=95.0, time="2024-01-01T00:05:00"),
        ]
        result = detector.analyze_follow_through(candles, "LONG", break_level=97.0)
        assert result is not None
        assert result["outcome"] == "REVERSAL"
        assert result["strength"] == 0.7

    def test_consolidation_pattern(self):
        """Price stalls after break (not continuing, not reversing)."""
        detector = RegimeDetector()
        candles = [
            _make_ohlc(close=95.0, time="2024-01-01T00:00:00"),
            _make_ohlc(close=96.0, time="2024-01-01T00:01:00"),
            # post_break[0]: entry
            _make_ohlc(close=98.0, low=97.5, time="2024-01-01T00:02:00"),
            # post_break[1]: same price
            _make_ohlc(close=98.0, low=97.5, time="2024-01-01T00:03:00"),
            # post_break[2]: exit = same as entry (98 == 98) => not continuation
            _make_ohlc(close=98.0, low=97.5, time="2024-01-01T00:04:00"),
            # current candle
            _make_ohlc(close=98.0, low=97.5, time="2024-01-01T00:05:00"),
        ]
        result = detector.analyze_follow_through(candles, "LONG", break_level=97.0)
        assert result is not None
        # exit_price (98.0) == entry_price (98.0) => not continuation
        # No candle low < 97 => not reversal
        # So it's consolidation
        assert result["outcome"] == "CONSOLIDATION"
        assert result["strength"] == 0.5

    def test_short_break_continuation(self):
        detector = RegimeDetector()
        candles = [
            _make_ohlc(close=105.0, time="2024-01-01T00:00:00"),
            _make_ohlc(close=104.0, time="2024-01-01T00:01:00"),
            _make_ohlc(close=103.0, time="2024-01-01T00:02:00"),
            _make_ohlc(close=102.0, time="2024-01-01T00:03:00"),
            _make_ohlc(close=101.0, time="2024-01-01T00:04:00"),
            _make_ohlc(close=100.0, time="2024-01-01T00:05:00"),
        ]
        result = detector.analyze_follow_through(candles, "SHORT", break_level=103.0)
        assert result is not None
        assert result["outcome"] == "CONTINUATION"

    def test_insufficient_data_returns_none(self):
        detector = RegimeDetector()
        candles = [_make_ohlc(close=100.0, time=f"2024-01-01T{i:02d}:00:00") for i in range(3)]
        assert detector.analyze_follow_through(candles, "LONG", break_level=100.0) is None

    def test_invalid_direction_returns_none(self):
        detector = RegimeDetector()
        candles = [_make_ohlc(close=100.0, time=f"2024-01-01T{i:02d}:00:00") for i in range(6)]
        assert detector.analyze_follow_through(candles, "INVALID", break_level=100.0) is None


# ---------------------------------------------------------------------------
# Additional edge cases and integration tests
# ---------------------------------------------------------------------------

class TestRegimeDetectorEdgeCases:
    def test_clear_failed_entries_resets_everything(self):
        detector = RegimeDetector()
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        detector.clear_failed_entries()
        assert detector.is_re_entry_blocked(level=100.0, direction="LONG",
                                             session_phase=1) is False

    def test_contraction_config_custom_ratio(self):
        config = ContractionConfig(contraction_ratio=0.50, lookback=10)
        detector = RegimeDetector(contraction_config=config)
        # More lenient ratio => easier to detect contraction
        candles = _make_contracting_candles(
            expansion_range=10.0, contraction_ratio=0.4, base_price=100.0, count=20,
        )
        assert detector.is_contracting(candles, lookback=10) is True

    def test_squeeze_override_allows_reentry(self):
        detector = RegimeDetector()
        detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        # Squeeze active overrides blocking
        assert detector.is_re_entry_blocked(level=100.0, direction="LONG",
                                             session_phase=1, squeeze_active=True) is False

    def test_level_touches_capped_at_100(self):
        detector = RegimeDetector()
        # Add 110 unique level touches
        for i in range(110):
            detector.record_level_approach(
                price=100.0, key_levels=[float(i)], timestamp=float(i),
            )
        assert len(detector._level_touches) <= 100

    def test_failed_entries_capped_at_50(self):
        detector = RegimeDetector()
        for i in range(60):
            detector.record_failed_entry(level=100.0, direction="LONG", session_phase=1)
        assert len(detector._failed_entries) <= 50
