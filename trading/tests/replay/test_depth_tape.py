"""Depth tape — capture live Depth snapshots, load them back, drive a backtest.

A ``SyntheticTickGenerator`` emitting Depth snapshots stands in for a live
feed; the recorder writes every snapshot to a JSONL tape. Round-tripping the
tape and interleaving it with the bars must reproduce the same book-driven
backtest equity as running from the in-memory snapshots (capture == replay).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain import (
    OHLC,
    Candle,
    Depth,
    Equity,
    OrderSide,
    Price,
    Quantity,
    Signal,
    Timeframe,
)

from tradex_trading.execution.book_fill_source import BookFillSource
from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.replay.backtest import BacktestEngine
from tradex_trading.replay.depth_tape import (
    DepthTapeRecorder,
    interleave_tape,
    load_depth_tape,
)
from tradex_trading.replay.synthetic_ticks import SyntheticTickGenerator

INST = Equity.of("NSE", "RELIANCE")


def _candles() -> list[Candle]:
    """Four deterministic M1 bars with up-gaps so orders cross the book.

    The synthetic book's best ask sits at the bar's close + tick; the
    next_open bridge prices the order at the NEXT bar's open, so each open
    must gap above the prior close (close + 1.0) for the order to cross.
    """
    specs = [
        ("100", "101", 9, 15),
        ("102", "103", 9, 16),
        ("104", "105", 9, 17),
        ("106", "105.5", 9, 18),
    ]
    candles: list[Candle] = []
    for open_s, close_s, h, m in specs:
        open_p = Decimal(open_s)
        close_p = Decimal(close_s)
        candles.append(
            Candle(
                instrument=INST,
                timeframe=Timeframe.M1,
                ohlc=OHLC(
                    open=Price(value=open_p),
                    high=Price(value=max(open_p, close_p) + Decimal("0.5")),
                    low=Price(value=min(open_p, close_p) - Decimal("0.5")),
                    close=Price(value=close_p),
                ),
                volume=Quantity(value=Decimal("2000")),
                timestamp=datetime(2026, 8, 1, h, m, tzinfo=UTC),
            )
        )
    return candles


class _SignalStrategy:
    """Emits a BUY on the first bar only, sized by strength."""

    def __init__(self, strength: float = 8) -> None:
        self.strength = strength
        self.strategy_id = "depth-tape"
        self.version = "1.0.0"
        self.signals: list[Signal] = []

    def on_start(self, context) -> None:
        pass

    def on_bar(self, context, candle) -> Signal | None:
        if not self.signals:
            signal = Signal(
                instrument=INST,
                direction=OrderSide.BUY,
                strength=self.strength,
                reason="depth-tape",
                timestamp=candle.timestamp,
            )
            self.signals.append(signal)
            return signal
        return None

    def on_quote(self, context, quote) -> Signal | None:
        return None

    def on_depth(self, context, depth) -> None:
        pass

    def on_fill(self, context, fill) -> None:
        pass


def _captured_tape(candles: list[Candle], tmp_path) -> tuple[list[Depth], list[Candle | Depth]]:
    """Run a synthetic depth feed, recording to a tape; return (in-memory, tape)."""
    bus = ReactiveBus()
    in_memory: list[Depth] = []
    bus.of_type(Depth).subscribe(lambda d: in_memory.append(d))
    recorder = DepthTapeRecorder(tmp_path / "depth.jsonl", bus=bus)
    generator = SyntheticTickGenerator(
        bus, seed=7, method="bridge", depth_levels=3, ticks_per_bar=60,
    )
    for candle in candles:
        generator.feed_bar(candle)
    recorder.close()
    return in_memory, interleave_tape(candles, load_depth_tape(recorder.path))


def test_tape_round_trip_is_lossless(tmp_path) -> None:
    in_memory, _ = _captured_tape(_candles(), tmp_path)

    assert len(in_memory) == 4  # one Depth snapshot per bar
    tape = load_depth_tape(tmp_path / "depth.jsonl")
    assert len(tape) == 4
    # Serialized round-trip preserves the snapshot exactly.
    assert tape == in_memory
    assert all(d.best_bid is not None and d.best_ask is not None for d in tape)


def test_interleave_orders_candle_then_depth(tmp_path) -> None:
    _, tape = _captured_tape(_candles(), tmp_path)

    assert len(tape) == 8
    # candle(0), depth(0), candle(1), depth(1), ...
    assert isinstance(tape[0], Candle) and isinstance(tape[1], Depth)
    assert tape[0].timestamp <= tape[1].timestamp


def test_tape_drives_book_backtest_identically_to_memory(tmp_path) -> None:
    candles = _candles()
    in_memory, tape = _captured_tape(candles, tmp_path)

    # Same strategy, same BookFillSource — once from in-memory depth, once
    # from the loaded tape. The book state at every fill is identical, so the
    # equity curves must match to the rupee (capture == replay).
    result_mem = BacktestEngine(
        fill_source=BookFillSource(), initial_capital=Decimal("1000000"),
    ).run(_SignalStrategy(), interleave_tape(candles, in_memory))
    result_tape = BacktestEngine(
        fill_source=BookFillSource(), initial_capital=Decimal("1000000"),
    ).run(_SignalStrategy(), tape)

    assert result_mem.num_trades > 0  # the tape actually exercised matching
    assert result_tape.num_trades == result_mem.num_trades
    assert result_tape.total_fees == result_mem.total_fees
    assert result_tape.equity_curve == result_mem.equity_curve
