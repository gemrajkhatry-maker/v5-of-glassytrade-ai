"""Parity: acceptance_rejection moved module vs legacy shim.

update() is stateful (accumulates time in VA) but fully deterministic given a
fresh engine and the same candle sequence, so we drive both through identical
sequences and compare every ARResult.
"""

from quant.amt.market.acceptance_rejection import (
    AcceptanceRejectionEngine as NewEngine,
)
from app.domain.services.acceptance_rejection import (
    AcceptanceRejectionEngine as LegacyEngine,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(t, o, h, l, c, v=1000, delta=0.0) -> OHLC:
    return OHLC(time=t, open=o, high=h, low=l, close=c, volume=v,
                delta=delta, taker_buy_volume=0.0)


def _run_sequence(factory, candles, vah, val, baseline_vol):
    engine = factory()
    return [engine.update(c, vah, val, baseline_vol) for c in candles]


def _sequences():
    above = [
        _candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100, 1000, 0),
        _candle("2024-01-01T09:17:00+00:00", 106, 107, 105.5, 106.5, 2000, 300),
    ]
    below = [
        _candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100, 1000, 0),
        _candle("2024-01-01T09:17:00+00:00", 94, 95, 93, 93.5, 2000, -300),
    ]
    reject_high = [
        _candle("2024-01-01T09:15:00+00:00", 104.5, 105.3, 104.0, 104.8, 2000, 300),
    ]
    sweep = [
        _candle("2024-01-01T09:15:00+00:00", 104.5, 105.6, 104.0, 104.6, 2000, 300),
    ]
    rotation = [
        _candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100, 1000, 0),
        _candle("2024-01-01T09:17:00+00:00", 100, 101.5, 98.5, 100.5, 1000, 0),
        _candle("2024-01-01T09:19:00+00:00", 100.5, 101, 99, 100, 1000, 0),
    ]
    return [
        (above, 105.0, 95.0, 1000.0),
        (below, 105.0, 95.0, 1000.0),
        (reject_high, 105.0, 95.0, 1000.0),
        (sweep, 105.0, 95.0, 1000.0),
        (rotation, 105.0, 95.0, 1000.0),
    ]


def test_parity_update_sequences():
    for candles, vah, val, base in _sequences():
        legacy = _run_sequence(LegacyEngine, candles, vah, val, base)
        new = _run_sequence(NewEngine, candles, vah, val, base)
        for l, n in zip(legacy, new):
            assert_parity(lambda: l, lambda: n)
