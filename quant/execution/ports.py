"""IOMS — Order Management System port.

The seam between the strategy engine and the venue (paper or live).
Every ``SignalApproved`` event must route through an ``IOMS`` implementation;
the engine never constructs its own OMS — the coordinator injects the correct
implementation at startup.

Implementations:
  - ``PaperOMS`` — simulated fills for replay / paper / backtest
  - ``LiveOMS`` — routes engine signals to a real broker via ``IBroker``

The protocol mirrors the methods that ``QuantEngine`` and ``PositionManager``
already call.  Both ``PaperOMS`` and ``LiveOMS`` satisfy it without changes
to their public API — the protocol formalises what exists.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from quant.execution.order import Fill, Position


@runtime_checkable
class IOMS(Protocol):
    """Order Management System port — the seam between strategy and venue."""

    @property
    def is_live(self) -> bool:
        """Whether this OMS can submit orders to a live venue."""
        ...

    @property
    def lot_size(self) -> float:
        """Units per lot (from the broker). Used for lot-snapped sizing."""
        ...

    def submit(self, signal, quantity: float) -> Position:
        """Open a new position from an approved signal.

        Args:
            signal: Engine-domain Signal (type=LONG/SHORT, entry, sl, tp, rr).
            quantity: Pre-sized quantity from SessionRisk.position_size().

        Returns:
            Position with open_price=signal.entry, size=±quantity (lot-snapped).
        """
        ...

    def close(
        self,
        position: Position,
        price: float,
        time: str,
        reason: str,
    ) -> Fill:
        """Close an entire position.

        Args:
            position: The open position to close.
            price: Close price (bar.close, or last traded price for halt).
            time: ISO timestamp of the close.
            reason: "SL" | "TP" | "TRAIL" | "TIME" | "SESSION_CLOSE" | "EMERGENCY_HALT"

        Returns:
            Fill with pnl = (price - entry) * size.
        """
        ...

    def close_partial(
        self,
        position: Position,
        fraction: float,
        price: float,
        time: str,
        reason: str,
    ) -> tuple[Fill, Position]:
        """Close a fraction of a position (spec §13.3 tiered TP).

        Args:
            position: The open position to reduce.
            fraction: Fraction to close (0.0, 1.0]. E.g. 0.50 for TP1.
            price: Close price for the partial fill.
            time: ISO timestamp.
            reason: Exit reason.

        Returns:
            (Fill for the partial close, remaining Position with reduced size).
        """
        ...

    def add_pyramid(
        self,
        base: Position,
        entry_price: float,
        new_sl: float,
        size: float,
        time: str,
        pyramid_level: int = 1,
    ) -> Position:
        """Create a pyramid add-on position anchored to the base trade (spec §13.2).

        Args:
            base: The base position being pyramided.
            entry_price: Entry price for the add-on (at LVN retest).
            new_sl: New stop-loss behind the LVN shelf.
            size: Add-on size (50% of base for P1, 25% for P2).
            time: ISO timestamp.
            pyramid_level: 1 for P1, 2 for P2.

        Returns:
            New pyramid Position (is_pyramid=True, pyramid_level=N).
        """
        ...
