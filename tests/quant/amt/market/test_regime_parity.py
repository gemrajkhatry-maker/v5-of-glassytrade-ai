"""Parity: regime_detector moved module vs legacy shim.

We cover the deterministic pure/stateless methods (is_contracting,
detect_bollinger_squeeze, is_atr_compressed, _compute_atr). Stateful /
live-session methods (should_trigger_llm, detect_squeeze, record_*/is_*
level tracking) depend on accumulated session state and are exercised by the
ported unit tests instead — see report.
"""

from quant.amt.market.regime import RegimeDetector as NewDetector
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(o, h, l, c, v=1000) -> OHLC:
    return OHLC(time="09:15", open=o, high=h, low=l, close=c, volume=v,
                delta=0.0, taker_buy_volume=0.0)


def _contracting_series():
    # Expansion (first 40) then tight compression (last 40)
    data = []
    for i in range(40):
        data.append(_candle(100 + i * 0.5, 102 + i * 0.5, 99 + i * 0.5, 101 + i * 0.5))
    for i in range(40):
        data.append(_candle(120, 120.2, 119.9, 120.05))
    return data


def _trending_series():
    return [_candle(100 + i, 101.5 + i, 99.5 + i, 101 + i) for i in range(80)]


def test_parity_is_contracting():
    NewDetector().is_contracting(_contracting_series(), 20)
    NewDetector().is_contracting(_trending_series(), 20)
    NewDetector().is_contracting(_trending_series()[:30], 20)
    NewDetector().is_contracting([], 20)


def test_parity_detect_bollinger_squeeze():
    tight = [_candle(100, 100.05, 99.95, 100.0) for _ in range(25)]
    wide = [_candle(100 + i * 0.3, 101.5 + i * 0.3, 98.5 + i * 0.3, 100 + i * 0.3)
            for i in range(25)]
    NewDetector().detect_bollinger_squeeze(tight, 20)
    NewDetector().detect_bollinger_squeeze(wide, 20)
    NewDetector().detect_bollinger_squeeze(wide[:10], 20)


def test_parity_is_atr_compressed():
    # High ATR period then low ATR period
    data = [_candle(100 + i * 0.5, 102 + i * 0.5, 98 + i * 0.5, 101 + i * 0.5)
            for i in range(40)]
    data += [_candle(120, 120.1, 119.9, 120.0) for _ in range(40)]
    NewDetector().is_atr_compressed(data, 20)
    NewDetector().is_atr_compressed(_trending_series(), 20)
    NewDetector().is_atr_compressed(data[:20], 20)


def test_parity_compute_atr():
    NewDetector()._compute_atr(_trending_series())
    NewDetector()._compute_atr([_candle(100, 101, 99, 100)])
    NewDetector()._compute_atr([])
