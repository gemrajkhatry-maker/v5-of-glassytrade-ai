"""Parity: lvn_play_detector moved module vs legacy shim."""

from quant.amt.market.lvn_play import detect_lvn_play as new_detect_lvn_play
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(o, h, l, c, v=1000, delta=0.0) -> OHLC:
    return OHLC(time="09:15", open=o, high=h, low=l, close=c, volume=v,
                delta=delta, taker_buy_volume=0.0)


def _cases():
    reject_long = _candle(100.0, 100.4, 99.2, 100.3, v=3000, delta=200)
    reject_short = _candle(100.0, 101.2, 99.8, 99.7, v=3000, delta=-200)
    no_rejection = _candle(100.0, 101.0, 99.0, 100.5, v=3000, delta=0)
    far_lvn = _candle(100.0, 101.0, 99.0, 100.0, v=3000, delta=200)
    return [
        (reject_long, [100.0], [], 100.0, 1000.0, 1.0),
        (reject_short, [100.0], [], 100.0, 1000.0, 1.0),
        (no_rejection, [100.0], [], 100.0, 1000.0, 1.0),
        (far_lvn, [90.0], [], 100.0, 1000.0, 1.0),
        (reject_long, [100.0], [102.0, 103.0], 101.0, 1000.0, 1.0),
        (reject_short, [100.0], [98.0, 97.0], 101.0, 1000.0, 1.0),
        (reject_long, [100.0], [], 101.0, 1000.0, 5.0, -5.0),
        (reject_long, [100.0], [], 101.0, 1000.0, 5.0, 3.0),
        (_candle(100.0, 101.0, 99.0, 100.0, v=0), [100.0], [], 100.0, 1000.0, 1.0),
        (reject_long, [], [], 100.0, 1000.0, 1.0),
    ]


def test_parity_detect_lvn_play():
    for args in _cases():
        new_detect_lvn_play(*args)
