"""Tests for MarketDataSequencer (duplicate/out-of-order market data)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import (
    Candle,
    Equity,
    OHLC,
    Price,
    Quantity,
    Quote,
    Timeframe,
)

from tradex_trading.reactive.sequencer import MarketDataSequencer


def _ts(sec: int) -> datetime:
    return datetime(2026, 8, 14, 9, 15, sec, tzinfo=UTC)


def _candle(sec: int) -> Candle:
    return Candle(
        instrument=Equity.of("NSE", "RELIANCE"),
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(Decimal("100")),
            high=Price(Decimal("101")),
            low=Price(Decimal("99")),
            close=Price(Decimal("100")),
        ),
        volume=Quantity(Decimal("100")),
        timestamp=_ts(sec),
    )


def _quote(sec: int, symbol: str = "RELIANCE") -> Quote:
    return Quote(
        instrument=Equity.of("NSE", symbol),
        ltp=Price(Decimal("100")),
        timestamp=_ts(sec),
    )


class TestMarketDataSequencer:
    def test_accepts_monotonic_messages(self) -> None:
        seq = MarketDataSequencer()
        assert seq.accept(_candle(1)) is True
        assert seq.accept(_candle(2)) is True

    def test_drops_duplicate_timestamp(self) -> None:
        seq = MarketDataSequencer()
        assert seq.accept(_candle(1)) is True
        assert seq.accept(_candle(1)) is False

    def test_drops_out_of_order(self) -> None:
        seq = MarketDataSequencer()
        assert seq.accept(_candle(2)) is True
        assert seq.accept(_candle(1)) is False

    def test_sequences_per_instrument_and_type(self) -> None:
        seq = MarketDataSequencer()
        # Same timestamp, different instrument -> both accepted.
        assert seq.accept(_quote(1)) is True
        assert seq.accept(_quote(1, symbol="TCS")) is True

    def test_non_market_messages_pass_through(self) -> None:
        seq = MarketDataSequencer()
        assert seq.accept("anything") is True
        assert seq.accept(42) is True

    def test_untimestamped_passes(self) -> None:
        seq = MarketDataSequencer()
        q = Quote(
            instrument=Equity.of("NSE", "RELIANCE"),
            ltp=Price(Decimal("100")),
            timestamp=None,
        )
        assert seq.accept(q) is True
        assert seq.accept(q) is True  # nothing to sequence
