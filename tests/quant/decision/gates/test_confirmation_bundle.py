"""Tests for confirmation_bundle — ported from backend/tests/unit/domain/test_entry_gate.py."""

import pytest

from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel
from quant.decision.gates.confirmation_bundle import (
    check_confirmation_bundle,
    compute_atr,
)


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time="2026-01-01T00:00:00Z", open=close, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


class TestConfirmationBundle:
    def test_requires_20_bars(self):
        data = [_tick() for _ in range(10)]
        assert check_confirmation_bundle(data, _tick()) is False

    def test_passes_with_strong_volume_and_delta(self):
        data = [_tick(volume=100, delta=5) for _ in range(30)]
        tick = _tick(volume=500, delta=200)  # 5x volume, 40% delta ratio
        assert check_confirmation_bundle(data, tick) is True

    def test_fails_with_weak_signals(self):
        data = [_tick(volume=100, delta=5) for _ in range(30)]
        tick = _tick(volume=100, delta=5)  # no impulse, low delta ratio
        assert check_confirmation_bundle(data, tick) is False

    def test_spread_tightness_passes_tight_spread(self):
        data = [_tick(volume=200, delta=80) for _ in range(30)]
        tick = _tick(volume=500, delta=200)
        ob = OrderBook(
            bids=(OrderBookLevel(price=99.99, quantity=100),),
            asks=(OrderBookLevel(price=100.01, quantity=100),),  # 2 bps spread
        )
        assert check_confirmation_bundle(data, tick, ob) is True

    def test_spread_tightness_no_orderbook_blocks_when_others_weak(self):
        data = [_tick(volume=200, delta=80) for _ in range(30)]
        tick = _tick(volume=200, delta=10)
        assert check_confirmation_bundle(data, tick, None) is False


class TestComputeATR:
    def test_basic(self):
        data = [_tick(high=110, low=90) for _ in range(20)]
        assert compute_atr(data, 14) == pytest.approx(20.0)

    def test_insufficient_data(self):
        assert compute_atr([_tick()], 14) == 0.0
