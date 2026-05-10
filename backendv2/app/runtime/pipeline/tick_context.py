"""TickContext – immutable context that flows through the pipeline.

Stores all computed state for a single tick as it traverses the pipeline.
Each stage receives a TickContext and returns a modified copy, ensuring
explicit data flow and no hidden global state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.trading.model.canonical_objects import (
    TradingSignal,
    VWAPProfile,
)


@dataclass(frozen=True)
class TickContext:
    """Immutable accumulator for tick pipeline state."""

    # Required fields
    symbol: str
    timestamp: datetime
    sequence: int
    tick: dict[str, Any]

    # Computed state (stages fill these)
    candle: dict[str, Any] | None = None
    vwap_profile: VWAPProfile | None = None
    market_structure: dict[str, Any] | None = None
    signal: TradingSignal | None = None
    exit_decision: dict[str, Any] | None = None
    order_status: dict[str, Any] | None = None

    # Additional optional data
    metadata: dict[str, Any] | None = None

    def with_candle(self, candle: dict[str, Any]) -> TickContext:
        """Return new context with candle set."""
        return TickContext(
            symbol=self.symbol,
            timestamp=self.timestamp,
            sequence=self.sequence,
            tick=self.tick,
            candle=candle,
            vwap_profile=self.vwap_profile,
            market_structure=self.market_structure,
            signal=self.signal,
            exit_decision=self.exit_decision,
            order_status=self.order_status,
            metadata=self.metadata,
        )

    def with_signal(self, signal: TradingSignal) -> TickContext:
        """Return new context with signal set."""
        return TickContext(
            symbol=self.symbol,
            timestamp=self.timestamp,
            sequence=self.sequence,
            tick=self.tick,
            candle=self.candle,
            vwap_profile=self.vwap_profile,
            market_structure=self.market_structure,
            signal=signal,
            exit_decision=self.exit_decision,
            order_status=self.order_status,
            metadata=self.metadata,
        )

    def with_market_structure(self, ms: dict[str, Any]) -> TickContext:
        """Return new context with market structure set."""
        return TickContext(
            symbol=self.symbol,
            timestamp=self.timestamp,
            sequence=self.sequence,
            tick=self.tick,
            candle=self.candle,
            vwap_profile=self.vwap_profile,
            market_structure=ms,
            signal=self.signal,
            exit_decision=self.exit_decision,
            order_status=self.order_status,
            metadata=self.metadata,
        )

    def with_vwap_profile(self, profile: VWAPProfile) -> TickContext:
        """Return new context with VWAP profile set."""
        return TickContext(
            symbol=self.symbol,
            timestamp=self.timestamp,
            sequence=self.sequence,
            tick=self.tick,
            candle=self.candle,
            vwap_profile=profile,
            market_structure=self.market_structure,
            signal=self.signal,
            exit_decision=self.exit_decision,
            order_status=self.order_status,
            metadata=self.metadata,
        )

    def with_exit_decision(self, decision: dict[str, Any]) -> TickContext:
        """Return new context with exit decision set."""
        return TickContext(
            symbol=self.symbol,
            timestamp=self.timestamp,
            sequence=self.sequence,
            tick=self.tick,
            candle=self.candle,
            vwap_profile=self.vwap_profile,
            market_structure=self.market_structure,
            signal=self.signal,
            exit_decision=decision,
            order_status=self.order_status,
            metadata=self.metadata,
        )

    def with_order_status(self, status: dict[str, Any]) -> TickContext:
        """Return new context with order status set."""
        return TickContext(
            symbol=self.symbol,
            timestamp=self.timestamp,
            sequence=self.sequence,
            tick=self.tick,
            candle=self.candle,
            vwap_profile=self.vwap_profile,
            market_structure=self.market_structure,
            signal=self.signal,
            exit_decision=self.exit_decision,
            order_status=status,
            metadata=self.metadata,
        )
