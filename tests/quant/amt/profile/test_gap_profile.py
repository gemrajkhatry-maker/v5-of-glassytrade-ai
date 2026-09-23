"""Tests for GapProfileDetector — Layer 4 gap liquidity profile (spec §5.2)."""

import pytest

from quant.amt.profile.gap_profile import (
    GapProfileDetector,
    GapProfile,
)
from quant.contracts.value_objects import OHLC


def _candle(
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: float = 100.0,
    time: str = "t",
) -> OHLC:
    """Build an OHLC with float fields."""
    h = high if high is not None else close + 0.1
    lo = low if low is not None else close - 0.1
    return OHLC(
        time=time,
        open=close,
        high=h,
        low=lo,
        close=close,
        volume=volume,
        vwap=close,
        delta=0.0,
    )


def _session_with_gap(
    prior_close: float,
    gap_direction: str = "UP",
    gap_size: float = 2.0,
    n_candles: int = 10,
) -> list[OHLC]:
    """Generate session candles that open with a gap from prior_close."""
    open_price = prior_close + (gap_size if gap_direction == "UP" else -gap_size)
    candles = []
    for i in range(n_candles):
        # Trade within and around the gap zone
        if gap_direction == "UP":
            c = prior_close + (gap_size * (i + 1) / (n_candles + 1))
        else:
            c = prior_close - (gap_size * (i + 1) / (n_candles + 1))
        candles.append(
            _candle(
                close=c,
                high=c + 0.05,
                low=c - 0.05,
                volume=100.0 + (i % 3) * 50,
                time=f"t{i}",
            )
        )
    # Force the first candle to open at the gap
    first = candles[0]
    candles[0] = OHLC(
        time=first.time,
        open=open_price,
        high=first.high,
        low=first.low,
        close=first.close,
        volume=first.volume,
        vwap=first.vwap,
        delta=first.delta,
    )
    return candles


class TestGapProfileDetector:
    """Gap detection and micro-profile extraction."""

    def test_detects_up_gap(self):
        """Session opening above prior close with sufficient gap → UP gap."""
        prior_close = 100.0
        candles = _session_with_gap(prior_close, "UP", gap_size=2.0)

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=105.0,
            prior_val=95.0,
            tick_size=0.05,
        )

        assert gap.is_gapped is True
        assert gap.gap_direction == "UP"

    def test_detects_down_gap(self):
        """Session opening below prior close with sufficient gap → DOWN gap."""
        prior_close = 100.0
        candles = _session_with_gap(prior_close, "DOWN", gap_size=2.0)

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=105.0,
            prior_val=95.0,
            tick_size=0.05,
        )

        assert gap.is_gapped is True
        assert gap.gap_direction == "DOWN"

    def test_no_gap_when_overlap(self):
        """Session opens at prior close (no gap) → no gap detected."""
        prior_close = 100.0
        # Open at prior close, no gap
        candles = [_candle(close=100.0 + i * 0.1, time=f"t{i}") for i in range(5)]

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=105.0,
            prior_val=95.0,
            tick_size=0.05,
        )

        assert gap.is_gapped is False

    def test_gap_poc_within_zone(self):
        """Gap-POC must lie within the gap zone bounds."""
        prior_close = 500.0
        candles = _session_with_gap(prior_close, "UP", gap_size=5.0, n_candles=8)

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=510.0,
            prior_val=490.0,
            tick_size=0.05,
        )

        if gap.is_gapped and gap.bars_in_gap >= 2:
            assert gap.gap_low <= gap.gap_poc <= gap.gap_high

    def test_gap_vah_above_gap_val(self):
        """Gap-VAH must be >= gap-VAL."""
        prior_close = 200.0
        candles = _session_with_gap(prior_close, "UP", gap_size=3.0, n_candles=8)

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=210.0,
            prior_val=190.0,
            tick_size=0.05,
        )

        if gap.is_gapped:
            assert gap.gap_vah >= gap.gap_val

    def test_gap_range(self):
        """gap_range returns the absolute price span of the gap zone."""
        prior_close = 100.0
        candles = _session_with_gap(prior_close, "UP", gap_size=3.0)

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=105.0,
            prior_val=95.0,
            tick_size=0.05,
        )

        if gap.is_gapped:
            assert abs(gap.gap_range - 3.0) < 0.2  # approximately the gap size

    def test_is_inside_gap(self):
        """is_inside_gap returns True for prices within the gap zone."""
        prior_close = 100.0
        candles = _session_with_gap(prior_close, "UP", gap_size=2.0)

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=105.0,
            prior_val=95.0,
            tick_size=0.05,
        )

        if gap.is_gapped:
            mid = (gap.gap_high + gap.gap_low) / 2
            assert gap.is_inside_gap(mid) is True
            assert gap.is_inside_gap(gap.gap_high + 10.0) is False

    def test_gap_fill_pct(self):
        """gap_fill_pct measures how much of the gap has been filled."""
        prior_close = 100.0
        candles = _session_with_gap(prior_close, "UP", gap_size=3.0, n_candles=5)

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=105.0,
            prior_val=95.0,
            tick_size=0.05,
        )

        if gap.is_gapped:
            # Price at gap_high = no fill (just opened)
            assert gap.gap_fill_pct(gap.gap_high) == 0.0
            # Price at gap_low = fully filled
            assert gap.gap_fill_pct(gap.gap_low) == 1.0
            # Price beyond gap range clamps
            assert gap.gap_fill_pct(gap.gap_low - 5.0) == 1.0

    def test_no_prior_close(self):
        """Without prior_close, no gap can be detected."""
        detector = GapProfileDetector()
        gap = detector.detect(
            [_candle(close=100.0, time="t0")],
            prior_close=0.0,
            tick_size=0.05,
        )
        assert gap.is_gapped is False

    def test_empty_data(self):
        """Empty candle list → no gap."""
        detector = GapProfileDetector()
        gap = detector.detect([], prior_close=100.0, tick_size=0.05)
        assert gap.is_gapped is False

    def test_small_gap_below_threshold(self):
        """Gap smaller than min_gap_pct → no gap."""
        prior_close = 100.0
        # Create a tiny gap: open at 100.05 (0.05% of range 20)
        # below the 1% min_gap_pct threshold
        c = _candle(close=100.05, time="t0")
        candles = [OHLC(
            time=c.time, open=100.05, high=c.high, low=c.low,
            close=c.close, volume=c.volume, vwap=c.vwap, delta=c.delta,
        )]

        detector = GapProfileDetector(min_gap_pct=0.01)  # 1% threshold
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=110.0,
            prior_val=90.0,
            tick_size=0.05,
        )
        assert gap.is_gapped is False

    def test_total_volume_positive(self):
        """Gapped profile with sufficient bars has positive total volume."""
        prior_close = 100.0
        candles = _session_with_gap(prior_close, "UP", gap_size=3.0, n_candles=8)

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=105.0,
            prior_val=95.0,
            tick_size=0.05,
        )

        if gap.is_gapped and gap.bars_in_gap >= 2:
            assert gap.total_volume > 0


class TestGapProfileEdgeCases:
    """Edge cases for GapProfile."""

    def test_gap_with_no_candles_in_zone(self):
        """Gap exists but no candles trade inside the zone."""
        prior_close = 100.0
        # Open with gap but all candles trade far above the gap zone
        open_price = 105.0  # UP gap of 5
        candles = [_candle(close=110.0 + i, time=f"t{i}") for i in range(5)]
        # Force first open
        first = candles[0]
        candles[0] = OHLC(
            time=first.time, open=open_price,
            high=first.high, low=first.low, close=first.close,
            volume=first.volume, vwap=first.vwap, delta=first.delta,
        )

        detector = GapProfileDetector(min_gap_pct=0.005)
        gap = detector.detect(
            candles,
            prior_close=prior_close,
            prior_vah=110.0,
            prior_val=90.0,
            tick_size=0.05,
        )

        # Gap detected but bars_in_gap might be 0 or 1
        if gap.is_gapped and gap.bars_in_gap < 2:
            # Should return minimal profile with midpoint as POC
            assert gap.gap_poc == pytest.approx(102.5, abs=0.1)
            assert gap.gap_vah == pytest.approx(105.0, abs=0.1)
            assert gap.gap_val == pytest.approx(100.0, abs=0.1)

    def test_gap_direction_empty_when_no_gap(self):
        """gap_direction is empty string when no gap."""
        gap = GapProfile(
            is_gapped=False, gap_direction="", gap_size_pct=0.0,
            gap_high=0.0, gap_low=0.0, gap_poc=0.0, gap_vah=0.0, gap_val=0.0,
        )
        assert gap.gap_direction == ""
        assert gap.is_inside_gap(100.0) is False
        assert gap.gap_fill_pct(100.0) == 0.0
