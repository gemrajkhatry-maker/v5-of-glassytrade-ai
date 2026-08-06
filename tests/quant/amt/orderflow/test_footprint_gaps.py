"""Tests for absorption detection and contested zone detection."""

from quant.amt.orderflow.footprint import (
    FootprintCandle, FootprintLevel, detect_absorption, detect_contested_zone,
)


class TestAbsorptionDetection:
    def _make_candle(self, levels):
        fp_levels = [
            FootprintLevel(price=p, bid=b, ask=a, delta=a - b, imbalance=False, stacked=False)
            for p, b, a in levels
        ]
        return FootprintCandle(time="2025-01-01T10:00:00", levels=tuple(fp_levels), poc_price=100.0, total_delta=0.0, step_price=0.5)

    def test_absorption_high_volume_no_move(self):
        # Strong sell aggression (bid >> ask) but price didn't move
        candle = self._make_candle([
            (100.0, 500, 100),  # heavy bidding (selling)
            (100.5, 400, 80),
            (101.0, 300, 60),
        ])
        result = detect_absorption(candle, price_change_pct=0.05)
        assert result is not None
        assert result["detected"] is True
        assert result["aggressive_side"] == "SELL"
        assert result["absorbed_by"] == "BUY"

    def test_no_absorption_when_price_moves(self):
        candle = self._make_candle([
            (100.0, 500, 100),
            (100.5, 400, 80),
        ])
        result = detect_absorption(candle, price_change_pct=0.5)
        assert result is None

    def test_no_absorption_balanced_volume(self):
        candle = self._make_candle([
            (100.0, 100, 110),
            (100.5, 105, 100),
        ])
        result = detect_absorption(candle, price_change_pct=0.05)
        assert result is None

    def test_buy_absorption(self):
        # Strong ask aggression (ask >> bid) but price didn't move
        candle = self._make_candle([
            (100.0, 80, 500),
            (100.5, 60, 400),
        ])
        result = detect_absorption(candle, price_change_pct=0.02)
        assert result is not None
        assert result["aggressive_side"] == "BUY"
        assert result["absorbed_by"] == "SELL"

    def test_empty_candle(self):
        candle = FootprintCandle(time="t")
        assert detect_absorption(candle, 0.0) is None


class TestContestedZone:
    def _make_candle(self, stacked_levels):
        """stacked_levels: list of (price, delta, stacked)"""
        fp_levels = [
            FootprintLevel(price=p, bid=100, ask=100, delta=d, imbalance=True, stacked=s)
            for p, d, s in stacked_levels
        ]
        return FootprintCandle(time="t", levels=tuple(fp_levels), poc_price=100.0, total_delta=0.0, step_price=0.5)

    def test_contested_zone_both_sides(self):
        candles = [
            self._make_candle([(100, 50, True), (101, 30, False)]),   # buy stacked
            self._make_candle([(100, -50, True), (101, -30, False)]), # sell stacked
        ]
        assert detect_contested_zone(candles) is True

    def test_not_contested_single_side(self):
        candles = [
            self._make_candle([(100, 50, True)]),
            self._make_candle([(101, 30, True)]),
        ]
        assert detect_contested_zone(candles) is False

    def test_not_contested_no_stacked(self):
        candles = [
            self._make_candle([(100, 50, False)]),
            self._make_candle([(100, -50, False)]),
        ]
        assert detect_contested_zone(candles) is False

    def test_empty_candles(self):
        assert detect_contested_zone([]) is False
