"""Replay module — deterministic event replay and backtesting."""

from tradex_trading.replay.backtest import BacktestEngine, BacktestResult
from tradex_trading.replay.datalake_books import DatalakeBookGenerator, book_tape_from_candles
from tradex_trading.replay.depth_tape import (
    DepthTapeRecorder,
    interleave_tape,
    load_depth_tape,
)
from tradex_trading.replay.event_journal import EventJournal, iter_journal_events, replay_journal
from tradex_trading.replay.synthetic_ticks import SyntheticTickGenerator

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "DatalakeBookGenerator",
    "DepthTapeRecorder",
    "EventJournal",
    "SyntheticTickGenerator",
    "book_tape_from_candles",
    "interleave_tape",
    "iter_journal_events",
    "load_depth_tape",
    "replay_journal",
]
