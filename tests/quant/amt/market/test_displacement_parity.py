"""Parity: displacement_detector moved module vs legacy shim."""

from quant.amt.market.displacement import (
    detect_acceptance as new_detect_acceptance,
    detect_displacement as new_detect_displacement,
    detect_displacement_leg as new_detect_displacement_leg,
)
from app.domain.services.displacement_detector import (
    detect_acceptance as legacy_detect_acceptance,
    detect_displacement as legacy_detect_displacement,
    detect_displacement_leg as legacy_detect_displacement_leg,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(o, h, l, c, v=1000, delta=0.0) -> OHLC:
    return OHLC(time="09:15", open=o, high=h, low=l, close=c, volume=v,
                delta=delta, taker_buy_volume=0.0)


def _impulse_series():
    """Sideways noise (20) then 3+ strong same-direction candles."""
    data = [_candle(100, 100.3, 99.7, 100.1, 1000, 0) for _ in range(20)]
    data += [
        _candle(100.1, 101.5, 100.0, 101.4, 4000, 300),
        _candle(101.4, 102.8, 101.2, 102.7, 4500, 350),
        _candle(102.7, 104.0, 102.5, 103.9, 5000, 400),
    ]
    return data


def _noise_series():
    return [_candle(100, 100.4, 99.6, 100.0, 1000, 0) for _ in range(30)]


def test_parity_detect_displacement():
    assert_parity(legacy_detect_displacement, new_detect_displacement, _impulse_series())
    assert_parity(legacy_detect_displacement, new_detect_displacement, _noise_series())
    assert_parity(legacy_detect_displacement, new_detect_displacement, _noise_series()[:20])
    assert_parity(legacy_detect_displacement, new_detect_displacement, [])
    assert_parity(legacy_detect_displacement, new_detect_displacement,
                  _impulse_series(), displacement_multiplier=2.0)


def test_parity_detect_acceptance():
    above = [_candle(100, 101, 99, 110, 1000, 100), _candle(110, 111, 109, 112, 1000, 100)]
    below = [_candle(100, 101, 99, 80, 1000, -100), _candle(80, 81, 78, 78, 1000, -100)]
    inside = [_candle(100, 101, 99, 95, 1000, 0), _candle(95, 96, 94, 98, 1000, 0)]
    assert_parity(legacy_detect_acceptance, new_detect_acceptance, above, 100.0, 90.0)
    assert_parity(legacy_detect_acceptance, new_detect_acceptance, below, 100.0, 90.0)
    assert_parity(legacy_detect_acceptance, new_detect_acceptance, inside, 100.0, 90.0)
    assert_parity(legacy_detect_acceptance, new_detect_acceptance, inside[:1], 100.0, 90.0)


def test_parity_detect_displacement_leg():
    assert_parity(legacy_detect_displacement_leg, new_detect_displacement_leg, [])
    assert_parity(legacy_detect_displacement_leg, new_detect_displacement_leg,
                  _noise_series()[:4])
    assert_parity(legacy_detect_displacement_leg, new_detect_displacement_leg,
                  _noise_series())
    assert_parity(legacy_detect_displacement_leg, new_detect_displacement_leg,
                  _impulse_series())
