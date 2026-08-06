"""Parity: break_detector moved module vs legacy shim."""

from quant.amt.market.break_detector import (
    check_ib_break_tick as new_check_ib_break_tick,
    detect_break as new_detect_break,
)
from app.domain.services.break_detector import (
    check_ib_break_tick as legacy_check_ib_break_tick,
    detect_break as legacy_detect_break,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(o, h, l, c, v=1000, delta=0.0) -> OHLC:
    return OHLC(time="09:15", open=o, high=h, low=l, close=c, volume=v,
                delta=delta, taker_buy_volume=0.0)


def _cases_detect_break():
    impulse_up = [
        _candle(99, 100, 98, 99.5, 1000, 50),
        _candle(99.5, 100.5, 99, 100.0, 1000, 50),
        _candle(100.0, 101.0, 99.5, 100.8, 4000, 300),
    ]
    impulse_down = [
        _candle(101, 102, 100, 101.5, 1000, -50),
        _candle(101.5, 102, 100.5, 101.0, 1000, -50),
        _candle(101.0, 101.5, 99.2, 99.5, 4000, -300),
    ]
    no_vol = [
        _candle(99, 100, 98, 99.5, 1000, 50),
        _candle(99.5, 100.5, 99, 100.0, 1000, 50),
        _candle(100.0, 101.0, 99.5, 100.8, 1100, 300),
    ]
    noise = [_candle(100, 100.4, 99.6, 100.0, 1000, 0) for _ in range(6)]
    return [
        ([], 100.0, 90.0, 102.0, 98.0, 1000.0),
        (impulse_up, 100.0, 90.0, 0.0, 0.0, 1000.0),
        (impulse_down, 100.0, 100.0, 0.0, 0.0, 1000.0),
        (no_vol, 100.0, 90.0, 102.0, 98.0, 1000.0),
        (noise, 100.0, 90.0, 102.0, 98.0, 1000.0),
        (impulse_up, 100.0, 90.0, 102.0, 98.0, 1000.0),
        (impulse_down, 100.0, 100.0, 102.0, 98.0, 1000.0),
        (impulse_up, 100.0, 90.0, 102.0, 98.0, 0.0),
    ]


def test_parity_detect_break():
    for args in _cases_detect_break():
        assert_parity(legacy_detect_break, new_detect_break, *args)


def test_parity_check_ib_break_tick():
    cases = [
        (105.0, 102.0, 98.0, False),
        (105.0, 0.0, 0.0, True),
        (103.0, 102.0, 98.0, True),
        (97.0, 102.0, 98.0, True),
        (100.0, 102.0, 98.0, True),
    ]
    for price, ibh, ibl, comp in cases:
        assert_parity(legacy_check_ib_break_tick, new_check_ib_break_tick,
                      price, ibh, ibl, comp)
    assert_parity(legacy_check_ib_break_tick, new_check_ib_break_tick,
                  100.0, 102.0, 98.0, True, current_break_direction="UP")
    assert_parity(legacy_check_ib_break_tick, new_check_ib_break_tick,
                  100.0, 102.0, 98.0, True, current_break_direction="DOWN")
