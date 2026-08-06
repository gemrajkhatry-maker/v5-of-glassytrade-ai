"""Parity: confirmation_bundle via legacy shim vs moved quant module."""

from __future__ import annotations

from quant.decision.gates.confirmation_bundle import (
    check_confirmation_bundle,
    compute_atr,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0, time="2026-01-01T00:00:00Z"):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time=time, open=close, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


def test_compute_atr_parity():
    data = [_tick(high=110, low=90) for _ in range(20)]
    compute_atr(data, 14)


def test_compute_atr_insufficient_parity():
    compute_atr([_tick()], 14)


def test_check_confirmation_bundle_pass_parity():
    data = [_tick(volume=100, delta=5) for _ in range(30)]
    tick = _tick(volume=500, delta=200)
    check_confirmation_bundle(data, tick)


def test_check_confirmation_bundle_fail_parity():
    data = [_tick(volume=100, delta=5) for _ in range(30)]
    tick = _tick(volume=100, delta=5)
    check_confirmation_bundle(data, tick)


def test_check_confirmation_bundle_short_data_parity():
    data = [_tick() for _ in range(10)]
    check_confirmation_bundle(data, _tick())
