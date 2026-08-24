"""AMT scanner tests — multi-instrument setup ranking over the pure kernel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain import OHLC, Candle, Equity, Price, Quantity, Timeframe

from tradex_trading.strategy.extensions.amt.scanner import AMTScanner, AMTScanResult

BASE = datetime(2026, 8, 1, 9, 15, tzinfo=UTC)


def _candle(
    instrument: Equity,
    i: int,
    *,
    close: str = "100",
    open_: str = "100",
    high: str = "101",
    low: str = "99",
    volume: str = "100",
) -> Candle:
    return Candle(
        instrument=instrument,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(Decimal(open_)),
            high=Price(Decimal(high)),
            low=Price(Decimal(low)),
            close=Price(Decimal(close)),
        ),
        volume=Quantity(Decimal(volume)),
        timestamp=BASE + timedelta(minutes=i),
    )


def _flat_tape(instrument: Equity, n: int = 12) -> list[Candle]:
    return [_candle(instrument, i) for i in range(n)]


def _absorption_tape(instrument: Equity) -> list[Candle]:
    """Baseline + a BUY absorption spike (compressed range, 5x volume)."""
    tape = _flat_tape(instrument, 20)
    tape.append(_candle(
        instrument, 20, close="100.3", open_="100",
        high="100.3", low="100.1", volume="500",
    ))
    return tape


def _triple_a_tape(instrument: Equity) -> list[Candle]:
    """Baseline -> absorption -> accumulation -> breakout above VWAP+1sigma."""
    tape = _flat_tape(instrument, 20)
    tape.append(_candle(
        instrument, 20, close="100.3", open_="100",
        high="100.3", low="100.1", volume="500",
    ))
    tape.append(_candle(instrument, 21, close="100", open_="100"))
    tape.append(_candle(instrument, 22, close="100", open_="100"))
    tape.append(_candle(
        instrument, 23, close="101.5", open_="101",
        high="101.5", low="100.8", volume="300",
    ))
    return tape


def test_scanner_ranks_triple_a_setup_first() -> None:
    a = Equity.of("NSE", "RELIANCE")
    b = Equity.of("NSE", "TCS")
    c = Equity.of("NSE", "HDFCBANK")
    results = AMTScanner().scan([
        (a, _triple_a_tape(a)),
        (b, _flat_tape(b)),
        (c, _absorption_tape(c)),
    ])

    assert isinstance(results, list)
    assert all(isinstance(r, AMTScanResult) for r in results)
    assert results[0].instrument == a
    assert results[0].setup == "TRIPLE_A"
    # Flat tape produced no setup and is excluded.
    assert all(r.instrument != b for r in results)
    # Absorption setup ranks below the completed Triple-A.
    assert results[-1].setup == "ABSORBING"
    assert results[0].score > results[-1].score


def test_scanner_is_deterministic() -> None:
    a = Equity.of("NSE", "RELIANCE")
    c = Equity.of("NSE", "HDFCBANK")
    data = [(a, _triple_a_tape(a)), (c, _absorption_tape(c))]

    first = AMTScanner().scan(data)
    second = AMTScanner().scan(data)

    assert [(r.instrument.symbol, r.score, r.setup) for r in first] == [
        (r.instrument.symbol, r.score, r.setup) for r in second
    ]


def test_scanner_empty_universe_returns_empty() -> None:
    assert AMTScanner().scan([]) == []
