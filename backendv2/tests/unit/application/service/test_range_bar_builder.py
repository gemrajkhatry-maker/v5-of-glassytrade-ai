"""Tests for RangeBarBuilder and TickProcessor.

Covers:
- Range bar construction from ticks
- Bar completion when range threshold is met
- Volume accumulation
- Multiple bars from tick stream
- Edge cases (single tick, zero volume, gap jumps)
- TickProcessor integration
"""

from __future__ import annotations

import pytest

from app.application.service.tick_processor import RangeBar, RangeBarBuilder, TickProcessor


# ---------------------------------------------------------------------------
# 1. RangeBar dataclass
# ---------------------------------------------------------------------------

class TestRangeBar:
    def test_default_values(self):
        bar = RangeBar()
        assert bar.open == 0
        assert bar.high == 0
        assert bar.low == 0
        assert bar.close == 0
        assert bar.volume == 0
        assert bar.is_complete is False

    def test_complete_bar(self):
        bar = RangeBar(open=100, high=105, low=98, close=103, volume=500, is_complete=True)
        assert bar.open == 100
        assert bar.high == 105
        assert bar.low == 98
        assert bar.close == 103
        assert bar.volume == 500
        assert bar.is_complete is True


# ---------------------------------------------------------------------------
# 2. RangeBarBuilder — basic construction
# ---------------------------------------------------------------------------

class TestRangeBarBuilderBasics:
    def test_first_tick_starts_bar(self):
        builder = RangeBarBuilder(range_size=5.0)
        result = builder.update(price=100.0, volume=10)
        assert result is None  # Bar not complete yet
        assert builder.current_bar is not None
        assert builder.current_bar.open == 100.0

    def test_bar_completes_when_range_reached(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0, volume=10)
        result = builder.update(price=105.0, volume=20)  # range = 5.0
        assert result is not None
        assert result.is_complete is True
        assert result.high - result.low >= 5.0

    def test_bar_does_not_complete_below_range(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0, volume=10)
        result = builder.update(price=103.0, volume=20)  # range = 3.0 < 5.0
        assert result is None

    def test_new_bar_starts_after_completion(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0, volume=10)
        builder.update(price=105.0, volume=20)  # Completes first bar
        # Current bar should be a fresh bar starting at 105
        assert builder.current_bar is not None
        assert builder.current_bar.open == 105.0
        assert builder.current_bar.high == 105.0
        assert builder.current_bar.low == 105.0


# ---------------------------------------------------------------------------
# 3. RangeBarBuilder — price tracking
# ---------------------------------------------------------------------------

class TestRangeBarBuilderPriceTracking:
    def test_high_tracks_maximum_price(self):
        builder = RangeBarBuilder(range_size=10.0)
        builder.update(price=100.0)
        builder.update(price=103.0)
        builder.update(price=107.0)
        assert builder.current_bar.high == 107.0

    def test_low_tracks_minimum_price(self):
        builder = RangeBarBuilder(range_size=10.0)
        builder.update(price=100.0)
        builder.update(price=97.0)
        builder.update(price=93.0)
        assert builder.current_bar.low == 93.0

    def test_high_low_from_both_directions(self):
        """Range is computed from high-low, not just close-open."""
        builder = RangeBarBuilder(range_size=10.0)
        builder.update(price=100.0)
        builder.update(price=105.0)  # high
        result = builder.update(price=95.0)   # low, range = 105-95 = 10.0, completes
        assert result is not None
        assert result.high == 105.0
        assert result.low == 95.0
        assert result.close == 95.0  # close is the completing tick's price

    def test_close_always_last_price_of_completed_bar(self):
        builder = RangeBarBuilder(range_size=10.0)
        builder.update(price=100.0)
        builder.update(price=105.0)
        completed = builder.update(price=95.0)  # This completes the bar
        assert completed.close == 95.0
        assert completed.high == 105.0
        assert completed.low == 95.0


# ---------------------------------------------------------------------------
# 4. RangeBarBuilder — volume tracking
# ---------------------------------------------------------------------------

class TestRangeBarBuilderVolume:
    def test_volume_accumulates(self):
        builder = RangeBarBuilder(range_size=10.0)
        builder.update(price=100.0, volume=10)
        builder.update(price=102.0, volume=20)
        builder.update(price=105.0, volume=30)
        assert builder.current_bar.volume == 60

    def test_buy_sell_volume_tracked(self):
        builder = RangeBarBuilder(range_size=10.0)
        builder.update(price=100.0, volume=50, buy_vol=30, sell_vol=20)
        builder.update(price=102.0, volume=40, buy_vol=25, sell_vol=15)
        assert builder.current_bar.buy_volume == 55
        assert builder.current_bar.sell_volume == 35

    def test_volume_reset_on_new_bar(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0, volume=100)
        builder.update(price=105.0, volume=200)  # Completes
        # New bar starts with volume from the completing tick
        assert builder.current_bar.volume == 0  # Fresh bar, no volume yet


# ---------------------------------------------------------------------------
# 5. RangeBarBuilder — multiple bars
# ---------------------------------------------------------------------------

class TestRangeBarBuilderMultipleBars:
    def test_completed_bars_list(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0, volume=10)
        builder.update(price=105.0, volume=20)  # Bar 1
        builder.update(price=110.0, volume=30)  # Bar 2
        assert len(builder.completed_bars) == 2

    def test_completed_bars_are_copy_not_reference(self):
        """Completed bars should be snapshots, not references to mutable state."""
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0)
        completed = builder.update(price=105.0)
        # Modify the returned bar
        completed.high = 999.0
        # The bar in completed_bars should be the same object
        assert builder.completed_bars[0].high == 999.0

    def test_to_bars_converts_to_dicts(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0, volume=10)
        builder.update(price=105.0, volume=20)  # Completes bar 1
        bars = builder.to_bars(builder.completed_bars)
        # to_bars includes completed bars + current incomplete bar
        assert len(bars) == 2  # 1 completed + 1 current (incomplete)
        assert bars[0]["open"] == 100.0
        assert bars[0]["high"] == 105.0
        assert bars[0]["volume"] == 30

    def test_to_bars_includes_current_incomplete_bar(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0, volume=10)
        builder.update(price=102.0, volume=5)  # Not complete
        bars = builder.to_bars([])
        assert len(bars) == 1
        assert bars[0]["close"] == 102.0


# ---------------------------------------------------------------------------
# 6. RangeBarBuilder — edge cases
# ---------------------------------------------------------------------------

class TestRangeBarBuilderEdgeCases:
    def test_zero_range_size_completes_immediately(self):
        builder = RangeBarBuilder(range_size=0.0)
        builder.update(price=100.0)
        result = builder.update(price=100.0)  # Same price, range=0
        assert result is not None  # Should complete immediately

    def test_large_price_jump_completes(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0)
        result = builder.update(price=200.0)  # Huge jump
        assert result is not None
        assert result.high == 200.0
        assert result.low == 100.0

    def test_downward_move_completes(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0)
        result = builder.update(price=95.0)
        assert result is not None
        assert result.high == 100.0
        assert result.low == 95.0

    def test_oscillating_prices_eventually_complete(self):
        builder = RangeBarBuilder(range_size=5.0)
        builder.update(price=100.0)
        builder.update(price=102.0)
        builder.update(price=99.0)
        builder.update(price=103.0)  # high=103, low=99, range=4, not yet
        result = builder.update(price=98.0)  # high=103, low=98, range=5.0, completes!
        assert result is not None
        assert result.high == 103.0
        assert result.low == 98.0


# ---------------------------------------------------------------------------
# 7. TickProcessor integration
# ---------------------------------------------------------------------------

class TestTickProcessor:
    def test_get_or_create_range_builder(self):
        processor = TickProcessor(range_default_size=5.0)
        builder = processor.get_or_create_range_builder("NIFTY")
        assert builder is not None
        assert builder._range_size == 5.0

    def test_same_builder_returned_for_same_symbol(self):
        processor = TickProcessor()
        b1 = processor.get_or_create_range_builder("NIFTY")
        b2 = processor.get_or_create_range_builder("NIFTY")
        assert b1 is b2

    def test_different_builders_for_different_symbols(self):
        processor = TickProcessor()
        b1 = processor.get_or_create_range_builder("NIFTY")
        b2 = processor.get_or_create_range_builder("BANKNIFTY")
        assert b1 is not b2

    def test_oi_tracking(self):
        processor = TickProcessor()
        result = processor.track_oi("NIFTY", 1000)
        assert result is not None
        assert result["oi"] == 1000
        assert result["oi_change"] == 0  # First reading
        assert result["oi_trend"] == "FLAT"

    def test_oi_rising(self):
        processor = TickProcessor()
        processor.track_oi("NIFTY", 1000)
        result = processor.track_oi("NIFTY", 1200)
        assert result["oi_change"] == 200
        assert result["oi_trend"] == "RISING"

    def test_oi_falling(self):
        processor = TickProcessor()
        processor.track_oi("NIFTY", 1000)
        result = processor.track_oi("NIFTY", 800)
        assert result["oi_change"] == -200
        assert result["oi_trend"] == "FALLING"

    def test_oi_ignored_when_zero(self):
        processor = TickProcessor()
        result = processor.track_oi("NIFTY", 0)
        assert result is None

    def test_build_order_book(self):
        processor = TickProcessor()
        bids = [(100.0, 50), (99.5, 30)]
        asks = [(100.5, 40), (101.0, 20)]
        book = processor.build_order_book(bids, asks)
        assert len(book.bids) == 2
        assert len(book.asks) == 2
        assert book.bids[0].price == 100.0
        assert book.asks[0].price == 100.5


# ---------------------------------------------------------------------------
# 8. End-to-end: tick stream produces range bars
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_tick_stream_produces_multiple_range_bars(self):
        """Simulate a realistic tick stream producing multiple range bars."""
        builder = RangeBarBuilder(range_size=10.0)
        ticks = [
            (100.0, 10), (101.0, 15), (102.0, 20), (103.0, 25),
            (104.0, 30), (105.0, 35), (106.0, 40), (107.0, 45),
            (108.0, 50), (109.0, 55), (110.0, 60),  # Bar 1 completes at 110
            (111.0, 10), (112.0, 15), (113.0, 20),
            (114.0, 25), (115.0, 30), (116.0, 35),
            (117.0, 40), (118.0, 45), (119.0, 50),
            (120.0, 55),  # Bar 2 completes at 120
        ]
        completed = []
        for price, vol in ticks:
            result = builder.update(price=price, volume=vol)
            if result is not None:
                completed.append(result)

        assert len(completed) == 2
        assert completed[0].high - completed[0].low >= 10.0
        assert completed[1].high - completed[1].low >= 10.0

    def test_processor_with_multiple_symbols(self):
        """TickProcessor handles range bars for multiple symbols independently."""
        processor = TickProcessor(range_default_size=10.0)
        nifty = processor.get_or_create_range_builder("NIFTY")
        bank = processor.get_or_create_range_builder("BANKNIFTY")

        nifty.update(price=22000.0)
        bank.update(price=48000.0)

        nifty.update(price=22010.0)  # NIFTY completes
        bank.update(price=48005.0)   # BANKNIFTY not yet

        assert len(nifty.completed_bars) == 1
        assert len(bank.completed_bars) == 0
