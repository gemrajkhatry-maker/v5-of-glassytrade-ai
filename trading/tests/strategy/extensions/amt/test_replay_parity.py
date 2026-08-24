from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import OHLC, Candle, Equity, Price, Quantity, Timeframe

from tradex_trading.strategy.extensions.amt.strategy import AMTStrategy

INSTRUMENT = Equity.of("NSE", "RELIANCE")


def _tape() -> list[Candle]:
    out: list[Candle] = []
    for i in range(20):
        close = Decimal("100") + Decimal(i % 4)
        out.append(Candle(
            instrument=INSTRUMENT, timeframe=Timeframe.M1,
            ohlc=OHLC(
                open=Price(close),
                high=Price(close + 1),
                low=Price(close - 1),
                close=Price(close),
            ),
            volume=Quantity(Decimal("100")),
            timestamp=datetime(2026, 8, 1, 9, 15 + i, tzinfo=UTC),
        ))
    return out


def test_same_candle_tape_produces_identical_amt_trace() -> None:
    def run() -> tuple:
        strategy = AMTStrategy("amt-test", INSTRUMENT)
        for candle in _tape():
            strategy.on_bar(None, candle)
        return tuple(strategy.snapshots), tuple(strategy.signals)

    assert run() == run()
