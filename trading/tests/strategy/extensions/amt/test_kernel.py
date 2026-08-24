from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import OHLC, Candle, Equity, Price, Quantity, Timeframe

from tradex_trading.strategy.extensions.amt.kernel import AMTKernel
from tradex_trading.strategy.extensions.amt.model import AMTPhase, AMTSnapshot

INSTRUMENT = Equity.of("NSE", "RELIANCE")


def _candle(i: int, close: str, volume: str = "100") -> Candle:
    price = Decimal(close)
    return Candle(
        instrument=INSTRUMENT,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(price), high=Price(price + Decimal("1")),
            low=Price(price - Decimal("1")), close=Price(price),
        ),
        volume=Quantity(Decimal(volume)),
        timestamp=datetime(2026, 8, 1, 9, 15 + i, tzinfo=UTC),
    )


def test_kernel_returns_immutable_snapshot_with_profile_vwap_and_location() -> None:
    kernel = AMTKernel()
    snapshot = kernel.update(_candle(0, "100"))

    assert isinstance(snapshot, AMTSnapshot)
    assert snapshot.instrument == INSTRUMENT
    assert snapshot.poc is not None
    assert snapshot.vwap == Decimal("100")
    assert snapshot.ib_high == Decimal("101")
    assert snapshot.ib_low == Decimal("99")
    assert snapshot.location == "INSIDE_VA"
    assert snapshot.phase is AMTPhase.WAITING


def test_kernel_is_deterministic_for_same_candle_tape() -> None:
    candles = [_candle(i, str(100 + i % 3), "100") for i in range(8)]
    first = [AMTKernel().update(candle) for candle in candles]
    second = [AMTKernel().update(candle) for candle in candles]

    assert first == second
