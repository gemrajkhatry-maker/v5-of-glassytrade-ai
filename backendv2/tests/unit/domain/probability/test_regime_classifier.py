"""Tests for regime_classifier — classify_regime(), RegimeHysteresis, RegimeState."""

from __future__ import annotations

import pytest

from app.domain.probability.regime_classifier import (
    RegimeHysteresis,
    RegimeState,
    classify_regime,
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
    )


def _make_amt(market_state: str = "BALANCED") -> AMTResult:
    return AMTResult(market_state=market_state)


def _make_candles(
    count: int = 25,
    base_price: float = 100.0,
    base_volume: float = 1000.0,
    high: float = 101.0,
    low: float = 99.0,
    volume_trend: str = "flat",
) -> list[OHLC]:
    """Generate a sequence of OHLC candles.

    volume_trend:
        - "flat": constant volume
        - "increasing": linearly increasing
        - "decreasing": linearly decreasing
        - "spike_last": last candle has 100x volume
    """
    candles = []
    for i in range(count):
        if volume_trend == "increasing":
            vol = base_volume + i * 50
        elif volume_trend == "decreasing":
            vol = max(base_volume - i * 50, 1)
        elif volume_trend == "spike_last":
            vol = base_volume * 100 if i == count - 1 else base_volume
        else:
            vol = base_volume

        candles.append(
            _make_ohlc(
                close=base_price + i * 0.1,
                high=high + i * 0.05,
                low=low + i * 0.05,
                volume=vol,
                time=f"2024-01-01T{i:02d}:00:00",
            )
        )
    return candles


# ---------------------------------------------------------------------------
# 1. classify_regime() — Regime classification
# ---------------------------------------------------------------------------


class TestClassifyRegimeDead:
    """DEAD regime: insufficient data or volume < 5% of average."""

    def test_insufficient_candles_returns_dead(self):
        """Fewer than 20 candles => DEAD."""
        data = [_make_ohlc(time=f"2024-01-01T{i:02d}:00:00") for i in range(10)]
        amt = _make_amt()
        tick = data[-1]
        result = classify_regime(data, amt, tick)
        assert result.regime == "DEAD"
        assert result.allowed_long is False
        assert result.allowed_short is False
        assert result.risk_scale == 0.0

    def test_zero_volume_returns_dead(self):
        """tick.close <= 0 => DEAD."""
        data = _make_candles(count=25, base_price=100.0, base_volume=1000.0)
        amt = _make_amt()
        tick = OHLC.create(
            time="2024-01-01T99:00:00", open=0, high=0, low=0, close=0, volume=0,
        )
        result = classify_regime(data, amt, tick)
        assert result.regime == "DEAD"

    def test_extremely_low_volume_returns_dead(self):
        """vol_ratio < 0.01 (<1% of average) => DEAD.
        
        vol_ratio is computed from data[-1].volume vs EMA when tick.time != data[-1].time.
        So we set the last data candle to very low volume and pass a tick with a
        different timestamp.
        """
        candles = _make_candles(count=24, base_volume=1000.0)
        # Last candle has volume 5, EMA of prior candles ~1000 => ratio ~0.005
        candles.append(
            _make_ohlc(volume=5.0, time="2024-01-01T24:00:00")
        )
        amt = _make_amt()
        # Tick with different time => uses data[-1].volume for latest_vol
        tick = _make_ohlc(close=100.0, volume=1000.0, time="2024-01-01T25:00:00")
        result = classify_regime(candles, amt, tick)
        assert result.regime == "DEAD"

    def test_no_tick_returns_dead(self):
        """tick=None => DEAD."""
        data = _make_candles(count=25)
        amt = _make_amt()
        result = classify_regime(data, amt, None)
        assert result.regime == "DEAD"


class TestClassifyRegimeTrending:
    """TRENDING regime: market_state is imbalanced."""

    def test_imbalanced_market_state_is_trending(self):
        """MarketStateCodec.is_imbalanced('IMBALANCED') => TRENDING."""
        data = _make_candles(count=25, base_volume=1000.0)
        amt = _make_amt(market_state="IMBALANCED")
        tick = data[-1]
        result = classify_regime(data, amt, tick)
        assert result.regime == "TRENDING"
        assert result.allowed_long is True
        assert result.allowed_short is True
        assert result.risk_scale == pytest.approx(1.0, abs=0.01)

    def test_trending_requires_sufficient_volume(self):
        """Even with IMBALANCED, extremely low volume in data => DEAD."""
        candles = _make_candles(count=24, base_volume=1000.0)
        # Last candle has very low volume
        candles.append(
            _make_ohlc(volume=1.0, time="2024-01-01T24:00:00")
        )
        amt = _make_amt(market_state="IMBALANCED")
        # Tick with different time => uses data[-1].volume for latest_vol
        tick = _make_ohlc(close=100.0, volume=1000.0, time="2024-01-01T25:00:00")
        result = classify_regime(candles, amt, tick)
        assert result.regime == "DEAD"


class TestClassifyRegimeBalanced:
    """BALANCED regime: moderate volume, market_state is balanced."""

    def test_balanced_market_state_is_balanced_regime(self):
        """MarketStateCodec.is_imbalanced('BALANCED') is False => BALANCED."""
        data = _make_candles(count=25, base_volume=1000.0)
        amt = _make_amt(market_state="BALANCED")
        tick = data[-1]
        result = classify_regime(data, amt, tick)
        assert result.regime == "BALANCED"
        assert result.allowed_long is True
        assert result.allowed_short is True
        assert result.risk_scale == pytest.approx(1.0, abs=0.01)

    def test_balanced_with_normal_atr_ratio(self):
        """ATR ratio within normal range => BALANCED (not VOLATILE)."""
        data = _make_candles(count=25, base_volume=1000.0, high=101.0, low=99.0)
        amt = _make_amt(market_state="BALANCE")
        tick = data[-1]
        result = classify_regime(data, amt, tick)
        assert result.regime == "BALANCED"


class TestClassifyRegimeVolatile:
    """VOLATILE regime: ATR ratio > 3.0 (5-period ATR >> 20-period ATR)."""

    def test_high_atr_ratio_is_volatile(self):
        """Recent candles with much larger range than the 20-candle average => VOLATILE."""
        candles = []
        # First 20 candles: very tight range (ATR ~0.2)
        for i in range(20):
            candles.append(
                _make_ohlc(
                    close=100.0, high=100.1, low=99.9, volume=1000.0,
                    time=f"2024-01-01T{i:02d}:00:00",
                )
            )
        # Last 5 candles: huge range (ATR ~20) => ratio ~100x > 3.0
        for i in range(5):
            candles.append(
                _make_ohlc(
                    close=100.0, high=120.0, low=80.0, volume=1000.0,
                    time=f"2024-01-01T{20 + i:02d}:00:00",
                )
            )
        amt = _make_amt(market_state="BALANCED")
        tick = candles[-1]
        result = classify_regime(candles, amt, tick)
        assert result.regime == "VOLATILE"
        assert result.allowed_long is True
        assert result.allowed_short is True
        assert result.risk_scale == pytest.approx(0.5, abs=0.01)

    def test_volatile_always_allows_both_directions(self):
        """VOLATILE regime: allowed_long=True, allowed_short=True."""
        candles = []
        for i in range(20):
            candles.append(
                _make_ohlc(close=100.0, high=100.1, low=99.9, volume=1000.0,
                           time=f"2024-01-01T{i:02d}:00:00")
            )
        for i in range(5):
            candles.append(
                _make_ohlc(close=100.0, high=120.0, low=80.0, volume=1000.0,
                           time=f"2024-01-01T{20 + i:02d}:00:00")
            )
        amt = _make_amt(market_state="IMBALANCED")
        tick = candles[-1]
        result = classify_regime(candles, amt, tick)
        assert result.regime == "VOLATILE"
        assert result.allowed_long is True
        assert result.allowed_short is True


class TestClassifyRegimePriority:
    """Regime classification priority order."""

    def test_volatile_takes_priority_over_trending(self):
        """High ATR ratio => VOLATILE even when market_state is IMBALANCED."""
        candles = []
        for i in range(20):
            candles.append(
                _make_ohlc(close=100.0, high=100.1, low=99.9, volume=1000.0,
                           time=f"2024-01-01T{i:02d}:00:00")
            )
        for i in range(5):
            candles.append(
                _make_ohlc(close=100.0, high=150.0, low=50.0, volume=1000.0,
                           time=f"2024-01-01T{20 + i:02d}:00:00")
            )
        amt = _make_amt(market_state="IMBALANCED")
        tick = candles[-1]
        result = classify_regime(candles, amt, tick)
        assert result.regime == "VOLATILE"

    def test_dead_takes_priority_over_everything(self):
        """Fewer than 20 candles => DEAD regardless of other conditions."""
        data = [_make_ohlc(time=f"2024-01-01T{i:02d}:00:00") for i in range(5)]
        amt = _make_amt(market_state="IMBALANCED")
        tick = data[-1]
        result = classify_regime(data, amt, tick)
        assert result.regime == "DEAD"


# ---------------------------------------------------------------------------
# 2. RegimeHysteresis
# ---------------------------------------------------------------------------


class TestRegimeHysteresis:
    """Hysteresis prevents rapid regime flipping."""

    def test_first_evaluation_always_accepts(self):
        """First call: no current regime => accept immediately."""
        hyst = RegimeHysteresis(min_persistence=3)
        state = RegimeState("BALANCED", True, True, 1.0)
        result = hyst.apply(state)
        assert result.regime == "BALANCED"

    def test_same_regime_confirmed_immediately(self):
        """Same regime as current stable => no delay."""
        hyst = RegimeHysteresis(min_persistence=3)
        state = RegimeState("BALANCED", True, True, 1.0)
        hyst.apply(state)  # First evaluation

        state2 = RegimeState("BALANCED", True, True, 1.0)
        result = hyst.apply(state2)
        assert result.regime == "BALANCED"

    def test_persistence_prevents_flipping(self):
        """New regime needs min_persistence consecutive evaluations."""
        hyst = RegimeHysteresis(min_persistence=3)
        # Establish BALANCED as current
        hyst.apply(RegimeState("BALANCED", True, True, 1.0))

        # Try switching to TRENDING — not enough persistence yet
        trending = RegimeState("TRENDING", True, True, 1.0)
        r1 = hyst.apply(trending)  # candidate_count=1
        assert r1.regime == "BALANCED"

        r2 = hyst.apply(trending)  # candidate_count=2
        assert r2.regime == "BALANCED"

    def test_persistence_allows_flip_after_threshold(self):
        """After min_persistence consecutive evaluations, flip occurs."""
        hyst = RegimeHysteresis(min_persistence=3)
        hyst.apply(RegimeState("BALANCED", True, True, 1.0))

        trending = RegimeState("TRENDING", True, True, 1.0)
        hyst.apply(trending)  # 1
        hyst.apply(trending)  # 2
        r3 = hyst.apply(trending)  # 3 => flip!
        assert r3.regime == "TRENDING"

    def test_candidate_resets_on_different_regime(self):
        """Switching candidate regime resets the counter."""
        hyst = RegimeHysteresis(min_persistence=3)
        hyst.apply(RegimeState("BALANCED", True, True, 1.0))

        # Try TRENDING once
        hyst.apply(RegimeState("TRENDING", True, True, 1.0))  # candidate=TRENDING, count=1

        # Switch to a different candidate
        hyst.apply(RegimeState("BALANCED", True, True, 1.0))  # same as current, resets

        # Now try TRENDING again — should start from count=1
        r = hyst.apply(RegimeState("TRENDING", True, True, 1.0))
        assert r.regime == "BALANCED"  # not yet enough persistence

    def test_dead_bypasses_hysteresis(self):
        """DEAD regime always passes through immediately (safety)."""
        hyst = RegimeHysteresis(min_persistence=3)
        hyst.apply(RegimeState("BALANCED", True, True, 1.0))

        dead = RegimeState("DEAD", False, False, 0.0)
        result = hyst.apply(dead)
        assert result.regime == "DEAD"

    def test_volatile_bypasses_hysteresis(self):
        """VOLATILE regime always passes through immediately (safety)."""
        hyst = RegimeHysteresis(min_persistence=3)
        hyst.apply(RegimeState("BALANCED", True, True, 1.0))

        volatile = RegimeState("VOLATILE", True, True, 0.5)
        result = hyst.apply(volatile)
        assert result.regime == "VOLATILE"

    def test_hysteresis_preserves_risk_scale_from_raw(self):
        """While holding current regime, risk_scale comes from raw input."""
        hyst = RegimeHysteresis(min_persistence=3)
        hyst.apply(RegimeState("BALANCED", True, True, 1.0))

        # TRENDING with reduced risk
        trending = RegimeState("TRENDING", True, True, 0.7)
        r = hyst.apply(trending)
        # Regime stays BALANCED, but risk_scale is from raw input
        assert r.regime == "BALANCED"
        assert r.risk_scale == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# 3. RegimeState
# ---------------------------------------------------------------------------


class TestRegimeState:
    """RegimeState properties per regime."""

    def test_dead_allows_no_trades(self):
        state = RegimeState("DEAD", False, False, 0.0)
        assert state.allowed_long is False
        assert state.allowed_short is False
        assert state.risk_scale == 0.0

    def test_balanced_allows_both_directions(self):
        state = RegimeState("BALANCED", True, True, 1.0)
        assert state.allowed_long is True
        assert state.allowed_short is True
        assert state.risk_scale == 1.0

    def test_trending_allows_both_directions(self):
        state = RegimeState("TRENDING", True, True, 1.0)
        assert state.allowed_long is True
        assert state.allowed_short is True
        assert state.risk_scale == 1.0

    def test_volatile_allows_both_with_reduced_risk(self):
        state = RegimeState("VOLATILE", True, True, 0.5)
        assert state.allowed_long is True
        assert state.allowed_short is True
        assert state.risk_scale == 0.5

    def test_regime_state_is_immutable(self):
        """RegimeState is frozen — cannot modify fields."""
        state = RegimeState("BALANCED", True, True, 1.0)
        with pytest.raises(Exception):
            # dataclass(frozen=True) raises either AttributeError or FrozenInstanceError
            state.regime = "TRENDING"


# ---------------------------------------------------------------------------
# 4. Integration: classify_regime + hysteresis
# ---------------------------------------------------------------------------


class TestRegimeClassificationIntegration:
    """End-to-end classification with hysteresis."""

    def test_stable_regime_through_hysteresis(self):
        """Consistent BALANCED classification remains stable."""
        data = _make_candles(count=25, base_volume=1000.0)
        amt = _make_amt(market_state="BALANCED")
        tick = data[-1]
        hyst = RegimeHysteresis(min_persistence=3)

        for _ in range(5):
            raw = classify_regime(data, amt, tick)
            result = hyst.apply(raw)
            assert result.regime == "BALANCED"

    def test_regime_transition_with_hysteresis(self):
        """Switching market_state requires persistence to flip."""
        data = _make_candles(count=25, base_volume=1000.0)
        amt_balanced = _make_amt(market_state="BALANCED")
        amt_imbalanced = _make_amt(market_state="IMBALANCED")
        tick = data[-1]
        hyst = RegimeHysteresis(min_persistence=3)

        # Establish BALANCED
        hyst.apply(classify_regime(data, amt_balanced, tick))

        # Switch to IMBALANCED — takes 3 evaluations
        r1 = hyst.apply(classify_regime(data, amt_imbalanced, tick))
        assert r1.regime == "BALANCED"

        r2 = hyst.apply(classify_regime(data, amt_imbalanced, tick))
        assert r2.regime == "BALANCED"

        r3 = hyst.apply(classify_regime(data, amt_imbalanced, tick))
        assert r3.regime == "TRENDING"

    def test_volatile_forces_immediate_transition(self):
        """High ATR forces immediate VOLATILE regardless of hysteresis."""
        candles = []
        for i in range(20):
            candles.append(
                _make_ohlc(close=100.0, high=100.1, low=99.9, volume=1000.0,
                           time=f"2024-01-01T{i:02d}:00:00")
            )
        for i in range(5):
            candles.append(
                _make_ohlc(close=100.0, high=120.0, low=80.0, volume=1000.0,
                           time=f"2024-01-01T{20 + i:02d}:00:00")
            )
        amt = _make_amt(market_state="BALANCED")
        tick = candles[-1]
        hyst = RegimeHysteresis(min_persistence=3)

        # Establish BALANCED first
        stable_candles = _make_candles(count=25, base_volume=1000.0)
        hyst.apply(classify_regime(stable_candles, amt, stable_candles[-1]))

        # VOLATILE should pass through immediately
        result = hyst.apply(classify_regime(candles, amt, tick))
        assert result.regime == "VOLATILE"
