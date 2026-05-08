"""Property-based tests for trading logic invariants.

Uses hypothesis to verify that core trading functions maintain invariants
across arbitrary input combinations.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from app.domain.amt.service.volume_profile import build_volume_profile
from app.domain.exit.service.exit_rules import (
    classify_exit,
    check_time_stop,
    is_valid_rr,
    check_spread_blowout,
)
from app.runtime.pipeline.signal import SignalGeneration
from app.runtime.pipeline.events import FeatureVector


# ============================================================
# Volume Profile Invariants
# ============================================================

@given(
    st.lists(
        st.dictionaries(
            st.sampled_from(["low", "high", "volume", "buyVolume", "sellVolume"]),
            st.floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=5,
        ),
        min_size=1,
        max_size=20,
    ),
    st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_volume_profile_poc_is_highest_volume_bucket(bars, bucket_size):
    """POC (Point of Control) should always be the bucket with highest total volume."""
    # Ensure bars have required fields
    for bar in bars:
        bar.setdefault("low", 10.0)
        bar.setdefault("high", 20.0)
        bar.setdefault("volume", 100.0)
        bar.setdefault("buyVolume", 50.0)
        bar.setdefault("sellVolume", 50.0)
        # Ensure low <= high
        if bar["low"] > bar["high"]:
            bar["low"], bar["high"] = bar["high"], bar["low"]

    vp = build_volume_profile(bars, bucket_size)

    if not vp.levels:
        return  # Empty profile is valid for degenerate cases

    # Find bucket with max volume
    max_volume = max(level.volume for level in vp.levels)
    poc_buckets = [level for level in vp.levels if level.volume == max_volume]

    # POC should be one of the max volume buckets
    assert vp.poc in [bucket.price for bucket in poc_buckets]


@given(
    st.lists(
        st.dictionaries(
            st.sampled_from(["low", "high", "volume"]),
            st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=3,
        ),
        min_size=1,
        max_size=10,
    ),
    st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_volume_profile_all_levels_within_price_range(bars, bucket_size):
    """All volume profile levels should fall within the global price range."""
    for bar in bars:
        bar.setdefault("low", 10.0)
        bar.setdefault("high", 20.0)
        bar.setdefault("volume", 100.0)
        if bar["low"] > bar["high"]:
            bar["low"], bar["high"] = bar["high"], bar["low"]

    vp = build_volume_profile(bars, bucket_size)

    global_min = min(bar["low"] for bar in bars)
    global_max = max(bar["high"] for bar in bars)

    for level in vp.levels:
        assert global_min - bucket_size <= level.price <= global_max + bucket_size


@given(
    st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
)
def test_volume_profile_empty_bars_returns_empty(volume):
    """Empty bar list should return empty volume profile."""
    vp = build_volume_profile([], bucket_size=5.0)
    assert len(vp.levels) == 0
    assert vp.poc == 0.0
    assert vp.vah == 0.0
    assert vp.val == 0.0


# ============================================================
# Exit Rules Invariants
# ============================================================

@given(
    st.sampled_from(["LONG", "SHORT"]),
    st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_exit_price_at_sl_always_classified_as_stop_loss(direction, entry, sl_distance):
    """Exit at exactly SL should always be classified as STOP_LOSS."""
    if direction == "LONG":
        sl = entry - sl_distance
        tp = entry + sl_distance * 2
        exit_price = sl
    else:
        sl = entry + sl_distance
        tp = entry - sl_distance * 2
        exit_price = sl

    result = classify_exit(direction, entry, exit_price, sl, tp)
    assert result == "STOP_LOSS"


@given(
    st.sampled_from(["LONG", "SHORT"]),
    st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_exit_price_at_tp_always_classified_as_take_profit(direction, entry, tp_distance):
    """Exit at exactly TP should always be classified as TAKE_PROFIT."""
    if direction == "LONG":
        sl = entry - tp_distance
        tp = entry + tp_distance * 2
        exit_price = tp
    else:
        sl = entry + tp_distance
        tp = entry - tp_distance * 2
        exit_price = tp

    result = classify_exit(direction, entry, exit_price, sl, tp)
    assert result == "TAKE_PROFIT"


@given(
    st.floats(min_value=0.0, max_value=86400.0, allow_nan=False, allow_infinity=False),
    st.sampled_from(["MORNING", "AFTERNOON", "UNKNOWN"]),
    st.sampled_from(["BALANCED", "IMBALANCED", "UNKNOWN"]),
    st.booleans(),
)
@settings(max_examples=100)
def test_time_stop_is_monotonic(hold_time, phase, state, is_expiry):
    """If time stop triggers at time T, it should also trigger at any time > T."""
    result_now = check_time_stop(hold_time, phase, state, is_expiry)
    result_later = check_time_stop(hold_time + 1, phase, state, is_expiry)

    if result_now:
        assert result_later, "Time stop should remain triggered once activated"


@given(
    st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    st.sampled_from(["LONG", "SHORT"]),
)
@settings(max_examples=50)
def test_valid_rr_implies_positive_expected_value(entry, risk, reward_mult, direction):
    """If RR >= 1.5, the reward should be at least 1.5x the risk."""
    if direction == "LONG":
        sl = entry - risk
        tp = entry + risk * reward_mult
    else:
        sl = entry + risk
        tp = entry - risk * reward_mult

    if is_valid_rr(entry, sl, tp, direction, min_rr=1.5):
        actual_risk = abs(entry - sl)
        if direction == "LONG":
            actual_reward = tp - entry
        else:
            actual_reward = entry - tp

        if actual_risk > 0:
            assert actual_reward / actual_risk >= 1.5


@given(
    st.floats(min_value=-0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_spread_blowout_threshold_is_strict_inequality(spread):
    """Spread must be strictly greater than threshold to trigger blowout."""
    threshold = 0.01
    result = check_spread_blowout(spread, threshold)

    if spread <= threshold:
        assert not result
    else:
        assert result


# ============================================================
# Signal Generation Invariants
# ============================================================

@given(
    st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_signal_stage_produces_consistent_outputs(vwap, upper_sigma, lower_sigma):
    """Signal generation should produce consistent outputs for same inputs."""
    stage = SignalGeneration(
        ofi_long_threshold=0.15,
        ofi_short_threshold=-0.30,
        min_confidence=0.3,
        max_confidence=0.95,
    )

    # Ensure upper > lower
    if upper_sigma < lower_sigma:
        upper_sigma, lower_sigma = lower_sigma, upper_sigma

    feature = FeatureVector(
        symbol="TEST",
        timestamp=1704169800.0,
        vwap=vwap,
        vwap_upper_1sigma=vwap + upper_sigma,
        vwap_lower_1sigma=vwap - lower_sigma,
        vwap_upper_2sigma=vwap + upper_sigma * 2,
        vwap_lower_2sigma=vwap - lower_sigma * 2,
        atr_14=10.0,
        rsi_14=50.0,
        rolling_volume_avg_20=1000.0,
    )

    result1 = stage.process(feature)
    result2 = stage.process(feature)

    # Same input should produce same output (deterministic)
    assert len(result1) == len(result2)
    if result1 and result2:
        assert result1[0].type == result2[0].type
        assert result1[0].entry == result2[0].entry
