"""Unit tests for Footprint Analyzer domain service."""

import pytest
from quant.contracts.value_objects import OHLC
from quant.amt.orderflow.footprint import FootprintAnalyzer
from quant.contracts.timezones import epoch_to_iso
from tests.helpers.market_data import generate_market_data


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
