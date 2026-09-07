"""
Portfolio Service - Positions, trades, and P&L operations.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from shared.entities.models import Position
from brokers.broker.dhan.domain import (
    DhanError,
    DhanNetworkError,
    POSITIONS,
    TRADES,
    PNL,
)
from ..converters import DhanConverter
from brokers.broker.logging import get_logger
from .base import BaseDhanService

logger = get_logger("dhan.services.portfolio")


class PortfolioService(BaseDhanService):
    """Handles positions, trades, and P&L operations."""

    async def get_positions_async(self) -> List[Position]:
        """Async implementation of get_positions."""
        await self._ensure_initialized()
        await self._apply_rate_limit("default")

        try:
            response = await self._execute_with_cb(
                lambda: self._http_client.get(endpoint=POSITIONS)
            )

            if response.status_code != 200:
                raise DhanNetworkError(
                    message="Failed to get positions",
                    code=str(response.status_code),
                    details=response.data,
                )

            raw = response.data
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, dict):
                items = raw.get("data", [])
            else:
                items = []

            positions = []
            for pos_data in items:
                positions.append(DhanConverter.position_from_api_response(pos_data))

            return positions

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, "get_positions")

    async def get_trade_history_async(
        self, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None
    ) -> List[Any]:
        """Get trade history for a period."""
        await self._ensure_initialized()
        await self._apply_rate_limit("default")

        if from_date is None:
            from_date = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if to_date is None:
            to_date = datetime.now()

        try:
            response = await self._execute_with_cb(
                lambda: self._http_client.get(
                    endpoint=TRADES,
                    params={
                        "from_date": from_date.strftime("%Y-%m-%d"),
                        "to_date": to_date.strftime("%Y-%m-%d"),
                    },
                )
            )

            if response.status_code != 200:
                logger.warning(f"Failed to get trade history: {response.status_code}")
                return []

            return response.data.get("data", [])

        except Exception as e:
            logger.error(f"Error getting trade history: {e}")
            return []

    async def get_trade_book_async(self) -> List[Any]:
        """Get today's trades."""
        return await self.get_trade_history_async()

    async def get_pnl_async(
        self, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get P&L report for a period."""
        await self._ensure_initialized()

        positions = await self.get_positions_async()
        unrealized_pnl = sum(p.unrealized_pnl for p in positions)

        try:
            response = await self._execute_with_cb(
                lambda: self._http_client.get(PNL)
            )
            if response.status_code == 200:
                return response.data
        except Exception as e:
            logger.warning(f"Could not fetch P&L from API: {e}")

        return {
            "unrealized_pnl": unrealized_pnl,
            "positions": positions,
        }
