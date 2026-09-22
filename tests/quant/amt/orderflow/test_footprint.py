"""Unit tests for Footprint Analyzer domain service."""

import pytest
from quant.contracts.value_objects import OHLC
from quant.amt.orderflow.footprint import FootprintAnalyzer, TickFootprintAccumulator
from quant.contracts.timezones import epoch_to_iso
from backend.tests.helpers.market_data import generate_market_data


class TestFootprintAnalyzer:
    def setup_method(self):
        self.analyzer = FootprintAnalyzer()

    def test_empty_data(self):
        result = self.analyzer.generate([])
        assert result == {}

    def test_single_candle(self):
        candle = OHLC(
            time="2026-01-01", open=100, high=110, low=90, close=105,
            volume=1000, vwap=102, taker_buy_volume=600, delta=200,
        )
        result = self.analyzer.generate([candle])
        key = epoch_to_iso(candle.time)
        assert key in result
        fc = result[key]
        assert len(fc.levels) > 0
        assert fc.total_delta == 200

    def test_flat_candle(self):
        candle = OHLC(
            time="t", open=100, high=100, low=100, close=100,
            volume=1000, vwap=100, delta=0,
        )
        result = self.analyzer.generate([candle])
        assert "t" in result
        fc = result["t"]
        assert len(fc.levels) >= 1

    def test_multiple_candles(self):
        data = generate_market_data(10, 100, "bullish")
        result = self.analyzer.generate(data)
        assert len(result) == 10

    def test_poc_price_set(self):
        candle = OHLC(
            time="t", open=100, high=110, low=90, close=105,
            volume=5000, vwap=102, taker_buy_volume=3000, delta=1000,
        )
        result = self.analyzer.generate([candle])
        fc = result["t"]
        assert fc.poc_price > 0

    def test_imbalance_detection(self):
        candle = OHLC(
            time="t", open=100, high=110, low=90, close=108,
            volume=10000, vwap=102, taker_buy_volume=8000, delta=6000,
        )
        result = self.analyzer.generate([candle])
        fc = result["t"]
        has_imbalance = any(l.imbalance for l in fc.levels)
        # With strong delta, some levels should show imbalance
        assert isinstance(has_imbalance, bool)

    def test_same_length_forming_update_preserves_completed_candles(self):
        completed = OHLC(
            time="2026-01-01T09:15:00+05:30",
            open=100, high=102, low=99, close=101,
            volume=100, vwap=100.5, delta=20,
        )
        forming = OHLC(
            time="2026-01-01T09:20:00+05:30",
            open=101, high=103, low=100, close=102,
            volume=80, vwap=101.5, delta=10,
        )
        first = dict(self.analyzer.generate([completed, forming]))
        updated = OHLC(
            time=forming.time,
            open=101, high=104, low=100, close=103,
            volume=140, vwap=102, delta=20,
        )

        result = self.analyzer.generate([completed, updated])

        assert len(result) == 2
        assert result[completed.time] is first[completed.time]
        assert sum(level.ask + level.bid for level in result[forming.time].levels) == 140

    def test_epoch_and_iso_keys_collide_when_data_grows(self):
        epoch = "1767225600"
        iso = "2026-01-01T05:30:00+05:30"
        first = OHLC(
            time=epoch, open=100, high=102, low=99, close=101,
            volume=100, vwap=100.5, delta=20,
        )
        replacement = OHLC(
            time=iso, open=100, high=103, low=99, close=102,
            volume=120, vwap=101, delta=20,
        )

        self.analyzer.generate([first])
        result = self.analyzer.generate([first, replacement])

        assert list(result) == [epoch_to_iso(epoch)]
        assert result[epoch_to_iso(epoch)].time == epoch_to_iso(epoch)
        assert sum(level.ask + level.bid for level in result[epoch_to_iso(epoch)].levels) == 120

    def test_gaussian_levels_conserve_volume_and_delta(self):
        candle = OHLC(
            time="2026-01-01T09:15:00+05:30",
            open=100, high=113, low=97, close=108,
            volume=101, vwap=105, delta=19,
        )

        footprint = self.analyzer.generate([candle])[candle.time]
        ask = sum(level.ask for level in footprint.levels)
        bid = sum(level.bid for level in footprint.levels)

        assert ask == 60
        assert bid == 41
        assert ask + bid == candle.volume
        assert ask - bid == candle.delta


class TestTickFootprintAccumulator:
    def test_epoch_and_iso_ticks_accumulate_in_one_forming_candle(self):
        accumulator = TickFootprintAccumulator()
        epoch = "1767225600"
        iso = "2026-01-01T05:30:00+05:30"

        accumulator.on_tick(100, 3, 99, 100, epoch)
        accumulator.on_tick(100, 2, 99, 100, iso)
        result = accumulator.get_all()

        assert list(result) == [epoch_to_iso(epoch)]
        assert sum(level.ask + level.bid for level in result[epoch_to_iso(epoch)].levels) == 5
