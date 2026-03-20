"""Position Recovery Service — unified position recovery from storage.

Eliminates duplicated position recovery logic that exists in both
trading_session.py and engine.py with slightly different implementations.

Usage:
    recovery = PositionRecoveryService(storage, trade_manager)
    recovered = recovery.recover_positions(session, symbol)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side, PositionStatus, Source

if TYPE_CHECKING:
    from app.domain.ports.storage import StoragePort
    from app.domain.fabio_ai.services.trade_manager import TradeManager
    from app.application.services.trading_session import SessionState

logger = logging.getLogger(__name__)


class PositionRecoveryService:
    """Unified service for recovering open positions from storage.

    Single responsibility: Load positions from DB and restore them
    to both the portfolio and TradeManager.
    """

    def __init__(
        self,
        storage: StoragePort | None,
        trade_manager: TradeManager | None = None,
    ) -> None:
        self._storage = storage
        self._trade_manager = trade_manager

    def recover_positions(
        self,
        session: SessionState,
        symbol: str,
    ) -> int:
        """Recover open positions for a symbol from storage.

        Args:
            session: Session state to restore positions into.
            symbol: Trading symbol to recover.

        Returns:
            Number of positions recovered.
        """
        if not self._storage:
            logger.debug("No storage available — skipping position recovery")
            return 0

        try:
            saved_positions = self._storage.load_open_positions()
        except Exception as e:
            logger.error("Failed to load open positions: %s", e, exc_info=True)
            return 0

        if not saved_positions:
            logger.debug("No open positions to recover for %s", symbol)
            return 0

        recovered = 0
        for pos_data in saved_positions:
            if pos_data.get("symbol") != symbol:
                continue

            position = self._restore_position(pos_data)
            if position is None:
                continue

            # Add to portfolio
            session.portfolio.positions.append(position)

            # Register with TradeManager for exit monitoring
            if self._trade_manager:
                self._trade_manager.register_position(
                    position_id=position.id,
                    symbol=symbol,
                    side=pos_data.get("side", "LONG"),
                    entry_price=position.entry_price,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                )

            logger.info(
                "Recovered position %s: %s %s @ %.2f (SL=%.2f, TP=%.2f)",
                position.id,
                pos_data.get("side", "?"),
                symbol,
                position.entry_price,
                position.stop_loss,
                position.take_profit,
            )
            recovered += 1

        if recovered > 0:
            logger.info("Recovered %d open positions for %s", recovered, symbol)

        return recovered

    def _restore_position(self, pos_data: dict) -> Position | None:
        """Restore a Position object from persisted data.

        Args:
            pos_data: Dictionary from storage with position fields.

        Returns:
            Position object or None if restoration fails.
        """
        try:
            position_id = pos_data.get("id", "")
            symbol = pos_data.get("symbol", "")
            side_str = pos_data.get("side", "LONG")

            if not position_id or not symbol:
                logger.warning("Position missing id or symbol: %s", pos_data)
                return None

            # Normalize side
            side = Side.LONG if side_str == "LONG" else Side.SHORT

            return Position(
                id=position_id,
                symbol=symbol,
                side=side,
                source=Source.LLM,
                entry_price=float(pos_data.get("entry_price", 0)),
                size=float(pos_data.get("size", 0)),
                stop_loss=float(pos_data.get("stop_loss", 0)),
                take_profit=float(pos_data.get("take_profit", 0)),
                entry_time=pos_data.get("opened_at", ""),
                status=PositionStatus.OPEN,
            )

        except Exception as e:
            logger.error("Failed to restore position: %s", e, exc_info=True)
            return None

    def clear_recovered_position(self, position_id: str) -> None:
        """Remove a recovered position from storage after successful restore.

        Args:
            position_id: ID of the position to clear.
        """
        if not self._storage:
            return
        try:
            self._storage.delete_open_position(position_id)
        except Exception as e:
            logger.debug("Failed to clear recovered position %s: %s", position_id, e)