"""Tests for TickContext – the pipeline's state accumulator.

TickContext is an immutable data carrier that accumulates computed state
as a tick flows through the pipeline stages. Each stage reads from and
writes to its own copy, avoiding hidden global state.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.runtime.pipeline.tick_context import TickContext
from app.domain.trading.model.canonical_objects import (
    TradingSignal,
    VWAPProfile,
    VWAPBand,
    SignalDirection,
    ConfidenceLevel,
    VWAPBias,
)


class TestTickContext:
    """Contract tests for TickContext."""

    def test_creation_requires_required_fields(self):
        """TickContext requires symbol, timestamp, sequence, tick."""
        with pytest.raises(TypeError):
            TickContext()

    def test_creation_with_minimal_fields(self):
        """Can create with only required fields."""
        ctx = TickContext(
            symbol="NIFTY",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            tick={"symbol": "NIFTY", "price": 100.0},
        )
        assert ctx.symbol == "NIFTY"
        assert ctx.sequence == 1
        assert ctx.candle is None
        assert ctx.vwap_profile is None
        assert ctx.signal is None

    def test_with_candle_returns_new_context(self):
        """with_candle produces new context with candle set."""
        ctx = TickContext(
            symbol="NIFTY",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            tick={"symbol": "NIFTY", "price": 100.0},
        )
        candle = {
            "open": 99.0,
            "high": 101.0,
            "low": 99.5,
            "close": 100.5,
            "volume": 1000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        ctx2 = ctx.with_candle(candle)
        assert ctx2.candle == candle
        assert ctx.candle is None  # original unchanged

    def test_with_signal_returns_new_context(self):
        """with_signal produces new context with signal set."""
        ctx = TickContext(
            symbol="NIFTY",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            tick={"symbol": "NIFTY", "price": 100.0},
        )
        signal = TradingSignal(
            symbol="NIFTY",
            direction=SignalDirection.LONG,
            grade=7,
            risk_reward_ratio=2.0,
            entry_price=100.0,
        )
        ctx2 = ctx.with_signal(signal)
        assert ctx2.signal is signal
        assert ctx.signal is None

    def test_with_market_structure(self):
        """with_market_structure adds market structure data."""
        ctx = TickContext(
            symbol="NIFTY",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            tick={"symbol": "NIFTY", "price": 100.0},
        )
        ms = {"state": "BALANCED", "zone": "NEAR_VAH"}
        ctx2 = ctx.with_market_structure(ms)
        assert ctx2.market_structure == ms
        assert ctx.market_structure is None

    def test_immutable(self):
        """Context fields are immutable."""
        ctx = TickContext(
            symbol="NIFTY",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            tick={"symbol": "NIFTY", "price": 100.0},
        )
        with pytest.raises(Exception):
            ctx.symbol = "BANKNIFTY"  # type: ignore

    def test_chainable_with_calls(self):
        """Multiple with_* calls chain properly."""
        ctx = TickContext(
            symbol="NIFTY",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            tick={"symbol": "NIFTY", "price": 100.0},
        )
        candle = {"close": 100.5, "volume": 1000}
        signal = TradingSignal(
            symbol="NIFTY", direction=SignalDirection.LONG, grade=8,
            risk_reward_ratio=2.5, entry_price=100.2
        )
        ctx2 = ctx.with_candle(candle).with_signal(signal)
        assert ctx2.candle == candle
        assert ctx2.signal == signal
        assert ctx.candle is None and ctx.signal is None

    def test_carries_optional_fields(self):
        """Extra optional fields are preserved."""
        ctx = TickContext(
            symbol="NIFTY",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            tick={"symbol": "NIFTY", "price": 100.0},
            metadata={"source": "feed"},
        )
        assert ctx.metadata == {"source": "feed"}