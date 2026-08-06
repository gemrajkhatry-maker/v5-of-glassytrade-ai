"""Parity: opening_classifier moved module vs legacy shim."""

from quant.amt.market.opening import OpeningTypeClassifier as NewClassifier
from app.domain.fabio_ai.services.opening_classifier import (
    OpeningTypeClassifier as LegacyClassifier,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(o, h, l, c, v=1000) -> OHLC:
    return OHLC(time="09:15", open=o, high=h, low=l, close=c, volume=v,
                delta=0.0, taker_buy_volume=0.0)


def _cases():
    # (data, prior_vah, prior_val, prior_poc)
    drive_up = [
        _candle(100, 100.2, 99.8, 100.2),
        _candle(100.2, 101.5, 100.1, 101.3),
        _candle(101.3, 102.5, 101.2, 102.4),
    ]
    drive_down = [
        _candle(100, 100.2, 99.8, 99.8),
        _candle(99.8, 100.0, 98.6, 98.7),
        _candle(98.7, 98.8, 97.6, 97.7),
    ]
    quiet = [
        _candle(100, 100.2, 99.8, 100.1),
        _candle(100.1, 100.3, 99.9, 100.0),
        _candle(100.0, 100.2, 99.8, 100.1),
    ]
    test_reject_high = [
        _candle(100, 100.2, 99.8, 100.1),
        _candle(100.1, 102.0, 100.0, 100.3),
        _candle(100.3, 100.5, 98.5, 98.8),
    ]
    rejection_reverse = [
        _candle(100, 100.4, 99.6, 100.2),
        _candle(100.2, 100.6, 99.9, 100.3),
        _candle(100.3, 100.7, 99.8, 100.4),
        _candle(100.4, 100.8, 99.9, 100.5),
        _candle(100.5, 102.0, 100.5, 101.9),
    ]
    return [
        ([], 100.0, 90.0, 95.0),
        ([_candle(100, 101, 99, 100)], 100.0, 90.0, 95.0),
        (drive_up, 100.0, 90.0, 95.0),
        (drive_down, 100.0, 90.0, 95.0),
        (quiet, 100.0, 90.0, 95.0),
        (test_reject_high, 102.0, 90.0, 95.0),
        (rejection_reverse, 100.0, 90.0, 95.0),
    ]


def test_parity_opening_classify():
    for data, vah, val, poc in _cases():
        assert_parity(
            LegacyClassifier().classify,
            NewClassifier().classify,
            data,
            vah,
            val,
            poc,
        )
