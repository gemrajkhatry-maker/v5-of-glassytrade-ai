"""Absorption semantics (AMT: aggression without price movement = hidden
opposite-side activity) survive the deletion of the test-only parallel impl
(``footprint.detect_absorption``). The single production definition is
``AbsorptionDetector``.

Semantic mapping from the deleted fixtures:
- one-sided aggression  -> signed delta (delta < 0 = aggressive SELL, delta > 0 = aggressive BUY)
- price didn't move     -> narrow candle range vs H_range (range_ratio <= 0.50,
                        the spec §7.2 ceiling; the denominator is the 20-bar
                        average RANGE, not ATR)
- absorption direction  -> opposite side absorbs: SELL aggression ⇒ SELL_ABSORBED
  (bullish, absorbed by hidden BUY); BUY aggression ⇒ BUY_ABSORBED
  (bearish, absorbed by hidden SELL)
- signal lifecycle      -> pending on the absorption candle, confirmed only by
  displacement (close beyond the absorption candle's high/low)

Also preserves the contested-zone assertions for the PRODUCTION
``detect_contested_zone`` (footprint.py, stays) whose only coverage lived in
the deleted test_footprint_gaps.py.
"""

from quant.amt.orderflow.detectors import AbsorptionDetector
from quant.amt.orderflow.footprint import (
    FootprintCandle, FootprintLevel, detect_contested_zone,
)
from quant.contracts.value_objects import OHLC


def _candle(close=100, volume=500, delta=100, high=None, low=None, time="t"):
    h = high or close * 1.01
    lo = low or close * 0.99
    return OHLC(
        time=time,
        open=close,
        high=h,
        low=lo,
        close=close,
        volume=volume,
        vwap=0,
        delta=delta,
    )


class TestAbsorptionSemanticsPreserved:
    """Ported from the deleted ``detect_absorption`` tests."""

    def test_sell_aggression_no_move_absorbed_by_buy(self):
        # Strong sell aggression (mirrors bid 500/400/300 vs ask 100/80/60)
        # but price didn't move → pending; bullish displacement confirms
        # SELL_ABSORBED (aggressive SELL absorbed by hidden BUY).
        detector = AbsorptionDetector()
        candle1 = _candle(close=100, high=100.14, low=99.86, volume=500, delta=-400)
        result1 = detector.detect(candle1, h_range=1.0, avg_vol=200)
        assert result1.detected is False  # pending displacement validation
        assert result1.side == ""

        # Displacement: close beyond the absorption candle's high
        candle2 = _candle(close=100.2, high=100.3, low=100.0, volume=300, delta=50)
        result2 = detector.detect(candle2, h_range=1.0, avg_vol=200)
        assert result2.detected is True
        assert result2.side == "SELL_ABSORBED"

    def test_no_absorption_when_price_moves(self):
        # Price moved (wide range vs ATR) → no absorption despite aggression.
        detector = AbsorptionDetector()
        candle = _candle(close=100, high=101.0, low=99.0, volume=500, delta=-400)
        result = detector.detect(candle, h_range=1.0, avg_vol=200)
        assert result.detected is False

    def test_no_absorption_balanced_volume(self):
        # Balanced two-sided flow (delta == 0) → no absorption.
        detector = AbsorptionDetector()
        candle = _candle(close=100, high=100.14, low=99.86, volume=500, delta=0)
        result = detector.detect(candle, h_range=1.0, avg_vol=200)
        assert result.detected is False
        assert result.side == ""

    def test_buy_aggression_no_move_absorbed_by_sell(self):
        # Strong ask aggression (mirrors ask 500/400 vs bid 80/60) but price
        # didn't move → pending; bearish displacement confirms BUY_ABSORBED
        # (aggressive BUY absorbed by hidden SELL).
        detector = AbsorptionDetector()
        candle1 = _candle(close=100, high=100.14, low=99.86, volume=500, delta=400)
        result1 = detector.detect(candle1, h_range=1.0, avg_vol=200)
        assert result1.detected is False  # pending displacement validation
        assert result1.side == ""

        # Displacement: close below the absorption candle's low
        candle2 = _candle(close=99.8, high=100.0, low=99.7, volume=300, delta=-50)
        result2 = detector.detect(candle2, h_range=1.0, avg_vol=200)
        assert result2.detected is True
        assert result2.side == "BUY_ABSORBED"


class TestContestedZone:
    """Verbatim port from the deleted test_footprint_gaps.py — tests the
    production ``detect_contested_zone`` (contested zone ⇒ FLAT)."""

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
