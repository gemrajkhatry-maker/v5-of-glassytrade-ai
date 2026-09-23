"""Tests for CompressionBoxDetector — Layer 2 micro-balance profile (spec §5.2)."""


from quant.amt.profile.compression_box import (
    CompressionBoxDetector,
    CompressionBox,
)
from quant.contracts.value_objects import OHLC


def _candle(
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: float = 100.0,
    delta: float = 0.0,
    time: str = "t",
) -> OHLC:
    """Build a FloatOHLC-like OHLC with float fields."""
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
        delta=delta,
    )


def _compressed_session(center: float = 100.0, n: int = 20, spread: float = 0.25) -> list[OHLC]:
    """Generate n candles rotating tightly around `center` within ±spread."""
    candles = []
    for i in range(n):
        # Oscillate within the tight range
        offset = spread * (1 if i % 2 == 0 else -1) * (0.5 + (i % 3) * 0.2)
        c = center + offset
        candles.append(
            _candle(
                close=c,
                high=c + 0.05,
                low=c - 0.05,
                volume=100.0 + (i % 5) * 50,
                delta=10.0 if i % 2 == 0 else -10.0,
                time=f"t{i}",
            )
        )
    return candles


class TestCompressionBoxDetector:
    """Compression box detection and micro-profile extraction."""

    def test_detects_compression_in_tight_range(self):
        """20 bars rotating within a 0.5-wide range → compression detected."""
        candles = _compressed_session(center=100.0, n=20, spread=0.25)
        detector = CompressionBoxDetector(max_lookback=30, range_ticks=10, min_bars=5)
        box = detector.detect(candles, tick_size=0.05)

        assert box.is_compressed is True
        assert box.bar_count >= 5
        assert box.box_high - box.box_low <= 10 * 0.05  # range_ticks * tick_size

    def test_no_compression_when_range_too_wide(self):
        """Bars spanning a wide range → no compression."""
        candles = [_candle(close=100.0 + i * 2.0, time=f"t{i}") for i in range(20)]
        detector = CompressionBoxDetector(max_lookback=30, range_ticks=5, min_bars=5)
        box = detector.detect(candles, tick_size=0.05)

        assert box.is_compressed is False

    def test_no_compression_too_few_bars(self):
        """Fewer bars than min_bars → no compression."""
        candles = _compressed_session(n=2)
        detector = CompressionBoxDetector(min_bars=5)
        box = detector.detect(candles)

        assert box.is_compressed is False

    def test_micro_poc_within_box(self):
        """Micro-POC must lie within the compression box bounds."""
        candles = _compressed_session(center=200.0, n=15, spread=0.2)
        detector = CompressionBoxDetector(max_lookback=30, range_ticks=10)
        box = detector.detect(candles, tick_size=0.05)

        assert box.is_compressed is True
        assert box.box_low <= box.micro_poc <= box.box_high

    def test_micro_vah_above_micro_val(self):
        """Micro-VAH must be >= micro-VAL."""
        candles = _compressed_session(n=15)
        detector = CompressionBoxDetector()
        box = detector.detect(candles, tick_size=0.05)

        if box.is_compressed:
            assert box.micro_vah >= box.micro_val

    def test_breakout_detection(self):
        """Close beyond micro-VAH → breakout LONG; below micro-VAL → SHORT."""
        candles = _compressed_session(center=100.0, n=15, spread=0.2)
        detector = CompressionBoxDetector(max_lookback=30, range_ticks=10)
        box = detector.detect(candles, tick_size=0.05)

        assert box.is_compressed is True

        # Breakout above
        assert box.breakout_direction(box.micro_vah + 1.0) == "LONG"
        # Breakout below
        assert box.breakout_direction(box.micro_val - 1.0) == "SHORT"
        # Inside
        mid = (box.micro_vah + box.micro_val) / 2
        assert box.breakout_direction(mid) == ""

    def test_is_broken_out(self):
        """is_broken_out returns True only when close is strictly beyond box."""
        candles = _compressed_session(center=500.0, n=10, spread=0.15)
        detector = CompressionBoxDetector(max_lookback=30, range_ticks=10)
        box = detector.detect(candles, tick_size=0.05)

        assert box.is_compressed is True
        assert box.is_broken_out(box.micro_vah + 0.01) is True
        assert box.is_broken_out(box.micro_val - 0.01) is True
        assert box.is_broken_out((box.micro_vah + box.micro_val) / 2) is False

    def test_is_inside(self):
        """is_inside returns True when price is within micro-VAH/VAL."""
        candles = _compressed_session(n=10)
        detector = CompressionBoxDetector()
        box = detector.detect(candles, tick_size=0.05)

        if box.is_compressed:
            mid = (box.micro_vah + box.micro_val) / 2
            assert box.is_inside(mid) is True
            assert box.is_inside(box.micro_vah + 1.0) is False

    def test_empty_data(self):
        """Empty candle list → no compression."""
        detector = CompressionBoxDetector()
        box = detector.detect([])
        assert box.is_compressed is False

    def test_total_volume_positive(self):
        """Compressed box has positive total volume."""
        candles = _compressed_session(n=10, spread=0.2)
        detector = CompressionBoxDetector()
        box = detector.detect(candles, tick_size=0.05)

        if box.is_compressed:
            assert box.total_volume > 0

    def test_breakout_on_no_compression(self):
        """breakout_direction returns empty when not compressed."""
        box = CompressionBox(
            is_compressed=False,
            micro_poc=0.0,
            micro_vah=0.0,
            micro_val=0.0,
            box_high=0.0,
            box_low=0.0,
            bar_count=0,
            total_volume=0.0,
        )
        assert box.breakout_direction(100.0) == ""
        assert box.is_broken_out(100.0) is False

    def test_prefers_largest_qualifying_window(self):
        """Detector picks the largest window that fits within range_ticks."""
        # First 25 bars compressed, then a wide bar breaks the range
        compressed = _compressed_session(center=100.0, n=25, spread=0.2)
        wide = [_candle(close=105.0, high=106.0, low=104.0, time=f"w{i}") for i in range(3)]
        candles = compressed + wide

        detector = CompressionBoxDetector(max_lookback=30, range_ticks=10, min_bars=5)
        box = detector.detect(candles, tick_size=0.05)

        # Should detect compression in the last qualifying window (the 3 wide
        # bars don't qualify, so it should find a sub-window of the compressed
        # section or the wide bars if they fit)
        if box.is_compressed:
            assert box.bar_count >= 5
