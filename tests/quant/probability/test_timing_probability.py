"""Tests for timing probability calculation (ported to quant.probability)."""

from __future__ import annotations

import pytest

from quant.probability.agent_pipeline import calculate_timing_probability
from quant.contracts.value_objects import AMTResult, OHLC


def _tick(close=100.0, volume=1000.0, delta=200.0, high=None, low=None):
    return OHLC(
        time="2026-01-01T10:00:00Z",
        open=close,
        high=high if high is not None else close + 1.0,
        low=low if low is not None else close - 1.0,
        close=close,
        volume=volume,
        delta=delta,
        vwap=close,
    )


def _amt(state="BALANCED", poc=100.0, vah=105.0, val=95.0, cvd_slope=0.6):
    return AMTResult(
        market_state=state,
        poc=poc,
        value_area_high=vah,
        value_area_low=val,
        aggression=0.8,
        cvd_slope=cvd_slope,
    )


def test_timing_probability_nonzero_at_extreme():
    """Timing probability should be >0.3 when price is at VAL/VAH extreme."""
    # Create BALANCED leg with price at VAL extreme
    data = [
        OHLC(
            time=f"2026-01-01T10:{i:02d}:00Z",
            open=95.0, high=96.0, low=94.0, close=95.0,
            volume=1000.0, delta=200.0
        )
        for i in range(10)
    ]
    tick = OHLC(
        time="2026-01-01T10:10:00Z",
        open=95.2, high=95.5, low=95.0, close=95.3,
        volume=1200.0, delta=300.0
    )
    amt = AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=105.0,
        value_area_low=95.0,  # Price near VAL
        aggression=2.5,
        cvd_slope=0.6,
    )

    prob = calculate_timing_probability(data, tick, amt, "LONG", "return_to_value", "ENTER_NOW")
    assert prob > 0.3, f"Timing probability too low: {prob}"
    assert prob <= 1.0, f"Timing probability out of range: {prob}"


def test_timing_probability_zero_for_skip():
    """Timing probability should be 0.0 for SKIP decisions."""
    prob = calculate_timing_probability([], None, None, "LONG", "return_to_value", "SKIP")
    assert prob == 0.0


def test_timing_probability_wait_returns_base():
    """Timing probability should return 0.3 for WAIT decisions."""
    prob = calculate_timing_probability([], None, None, "LONG", "return_to_value", "WAIT")
    assert prob == 0.3


def test_timing_probability_insufficient_data():
    """Timing probability should return 0.5 when insufficient data."""
    tick = _tick(close=100.0)
    amt = _amt()
    prob = calculate_timing_probability([], tick, amt, "LONG", "return_to_value", "ENTER_NOW")
    assert prob == 0.5


def test_timing_probability_high_delta_increases_score():
    """Higher delta should increase timing probability."""
    data = [_tick(close=100.0) for _ in range(10)]
    tick_low_delta = _tick(close=100.0, delta=50.0)
    tick_high_delta = _tick(close=100.0, delta=500.0)
    amt = _amt(cvd_slope=0.6)

    prob_low = calculate_timing_probability(data, tick_low_delta, amt, "LONG", "return_to_value", "ENTER_NOW")
    prob_high = calculate_timing_probability(data, tick_high_delta, amt, "LONG", "return_to_value", "ENTER_NOW")

    assert prob_high > prob_low, f"High delta ({prob_high}) should be > low delta ({prob_low})"


def test_timing_probability_cvd_alignment():
    """CVD slope aligned with direction should increase probability."""
    data = [_tick(close=100.0) for _ in range(10)]
    tick = _tick(close=100.0, delta=200.0)

    # Aligned: LONG + positive CVD
    amt_aligned = _amt(cvd_slope=0.8)
    prob_aligned = calculate_timing_probability(data, tick, amt_aligned, "LONG", "return_to_value", "ENTER_NOW")

    # Misaligned: LONG + negative CVD
    amt_misaligned = _amt(cvd_slope=-0.8)
    prob_misaligned = calculate_timing_probability(data, tick, amt_misaligned, "LONG", "return_to_value", "ENTER_NOW")

    assert prob_aligned > prob_misaligned, f"Aligned CVD ({prob_aligned}) should be > misaligned ({prob_misaligned})"


def test_timing_probability_return_to_value_edge_proximity():
    """return_to_value playbook should have higher probability near VAL/VAH."""
    data = [_tick(close=95.0) for _ in range(10)]

    # At VAL edge
    tick_at_edge = _tick(close=95.2)
    amt = _amt(poc=100.0, vah=105.0, val=95.0)
    prob_at_edge = calculate_timing_probability(data, tick_at_edge, amt, "LONG", "return_to_value", "ENTER_NOW")

    # Far from edge (middle of VA)
    tick_middle = _tick(close=100.0)
    prob_middle = calculate_timing_probability(data, tick_middle, amt, "LONG", "return_to_value", "ENTER_NOW")

    assert prob_at_edge > prob_middle, f"Edge proximity ({prob_at_edge}) should be > middle ({prob_middle})"


def test_timing_probability_range_vs_atr():
    """Lower bar range vs ATR should increase timing probability."""
    # Low ATR, small range (good timing)
    data_low_atr = [
        OHLC(time=f"2026-01-01T10:{i:02d}:00Z", open=100.0, high=100.5, low=99.5, close=100.0, volume=1000.0, delta=200.0)
        for i in range(10)
    ]
    tick_low_atr = OHLC(time="2026-01-01T10:10:00Z", open=100.0, high=100.3, low=99.7, close=100.1, volume=1000.0, delta=200.0)

    # High ATR, large range (bad timing - chasing)
    data_high_atr = [
        OHLC(time=f"2026-01-01T10:{i:02d}:00Z", open=100.0, high=105.0, low=95.0, close=100.0, volume=1000.0, delta=200.0)
        for i in range(10)
    ]
    tick_high_atr = OHLC(time="2026-01-01T10:10:00Z", open=100.0, high=108.0, low=92.0, close=100.0, volume=1000.0, delta=200.0)

    amt = _amt()

    prob_low_atr = calculate_timing_probability(data_low_atr, tick_low_atr, amt, "LONG", "return_to_value", "ENTER_NOW")
    prob_high_atr = calculate_timing_probability(data_high_atr, tick_high_atr, amt, "LONG", "return_to_value", "ENTER_NOW")

    # Lower ATR ratio should give better timing score
    assert prob_low_atr > prob_high_atr, f"Low ATR timing ({prob_low_atr}) should be > high ATR ({prob_high_atr})"
