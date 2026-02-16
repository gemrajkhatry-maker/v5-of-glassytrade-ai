"""Trade Lifecycle Handler — deterministic position management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.fabio_ai.services.trade_manager import TradeManager
from app.domain.trading.models.enums import SignalType, Source

if TYPE_CHECKING:
    from app.domain.trading.models.aggregates import Portfolio
    from app.domain.trading.models.entities import Signal, Position

logger = logging.getLogger(__name__)


class TradeLifecycleHandler:
    """Handles position exits via TradeManager (SL/TP/Trail/Time)."""

    def __init__(self) -> None:
        self._trade_manager = TradeManager()

    def check_exits(self, portfolio: Portfolio, current_price: float) -> bool:
        """Check all open positions for exit conditions.

        Returns:
            True if a position was closed (so caller knows the slot is free).
        """
        open_positions = [p for p in portfolio.positions if p.status == "OPEN"]

        for pos in open_positions:
            # Skip positions already closed (e.g. by Portfolio.process_tick SL/TP)
            if pos.status != "OPEN":
                continue
            exit_sig = self._trade_manager.check_position(pos.id, current_price)
            if exit_sig:
                portfolio.close_position(pos.id, exit_sig.exit_price, exit_sig.reason)
                self._trade_manager.unregister_position(pos.id)
                logger.info(
                    f"Position {pos.id} closed: {exit_sig.reason} "
                    f"at {exit_sig.exit_price:.2f}"
                )
                return True
        return False

    def register_position(self, position: Position, signal: Signal) -> None:
        """Register a new position with TradeManager for exit monitoring."""
        if signal.source == Source.LLM:
            allow_trail = (signal.metadata or {}).get("allow_trail", False)
            self._trade_manager.register_position(
                position_id=position.id,
                side="LONG" if signal.type == SignalType.BUY else "SHORT",
                entry_price=position.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                allow_trail=allow_trail,
            )

    @property
    def has_managed_positions(self) -> bool:
        return self._trade_manager.has_managed_positions

    def sync_closed(self, closed_positions: list) -> None:
        """Unregister positions that were closed by Portfolio (SL/TP hits).

        Prevents double-close when check_exits runs afterwards.
        """
        for pos in closed_positions:
            self._trade_manager.unregister_position(pos.id)

    def in_cooldown(self) -> bool:
        return self._trade_manager.in_cooldown()
