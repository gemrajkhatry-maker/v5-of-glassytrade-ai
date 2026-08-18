"""Unit tests for Layer 2 Compression Box Sub-Profile Detector (spec §6.2)."""

from quant.bars import Bar
from quant.compression_box import CompressionBoxDetector


def test_compression_box_detects_tight_consolidation():
    det = CompressionBoxDetector(min_bars=5, max_box_range_ticks=20, tick_size=0.05)
    # max_box_range = 20 * 0.05 = 1.00

    # Feed 5 tight bars around 100.0 (high=100.40, low=99.80, range=0.60 <= 1.00)
    box = None
    for i in range(5):
        bar = Bar(time=f"t{i}", open=100.0, high=100.30, low=99.90, close=100.10, volume=100)
        box = det.update(bar)

    assert box is not None
    assert box.bar_count == 5
    assert box.high == 100.30
    assert box.low == 99.90
    assert box.range_span <= 1.00
    assert box.micro_poc > 0
    assert box.micro_vah >= box.micro_val
    assert box.breakout_state == "INSIDE"


def test_compression_box_detects_expanding_breakout():
    det = CompressionBoxDetector(min_bars=5, max_box_range_ticks=20, tick_size=0.05)

    for i in range(5):
        bar = Bar(time=f"t{i}", open=100.0, high=100.30, low=99.90, close=100.10, volume=100)
        det.update(bar)

    # Bar 6: breakout above box high (close=100.50 > 100.30)
    bar6 = Bar(time="t5", open=100.20, high=100.60, low=100.20, close=100.50, volume=200)
    box6 = det.update(bar6)

    assert box6 is not None
    assert box6.breakout_state == "EXPANDING_UP"
