"""
T+1 Position Carryforward Reconciler.

On startup this reconciler pulls the broker's live positions and holdings into
the internal position book so the system has an accurate view of open risk from
the previous session.

Execution sequence (called from bootstrap.py lifespan):
    1. GET /positions  — intraday positions (opened today or not yet squared)
    2. GET /holdings   — CNC delivery holdings (previous-day carryforward)
    3. GET /orders     — today's order history (to seed the order book)

All three calls run concurrently to minimise startup latency.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.infrastructure.dhan_adapter.client import DhanHttpClient

logger = logging.getLogger(__name__)


class PositionBook:
    """
    Lightweight in-memory position registry.

    Keys are (exchange_segment, security_id).  Each entry tracks net quantity,
    average cost, product type, and the raw broker dict for reference.
    """

    def __init__(self) -> None:
        self._positions: Dict[tuple, Dict[str, Any]] = {}

    def upsert(self, key: tuple, entry: Dict[str, Any]) -> None:
        """Insert or replace a position entry."""
        self._positions[key] = entry

    def all(self) -> List[Dict[str, Any]]:
        """Return all known positions as a list."""
        return list(self._positions.values())

    def get(self, key: tuple) -> Optional[Dict[str, Any]]:
        return self._positions.get(key)

    def net_quantity(self, key: tuple) -> int:
        """Return net quantity for a key (positive=long, negative=short)."""
        entry = self._positions.get(key)
        if entry is None:
            return 0
        return int(entry.get("netQty", entry.get("quantity", 0)))

    def __len__(self) -> int:
        return len(self._positions)

    def __repr__(self) -> str:
        return f"<PositionBook positions={len(self._positions)}>"


class PositionReconciler:
    """
    Startup reconciler that seeds the internal PositionBook from the broker.

    Usage (in bootstrap.py lifespan)::

        reconciler = PositionReconciler(http_client)
        book = await reconciler.reconcile()
        # book is now populated with live positions + holdings
    """

    def __init__(self, http_client: "DhanHttpClient") -> None:
        self._client = http_client
        self._book = PositionBook()

    async def reconcile(self) -> PositionBook:
        """
        Fetch positions, holdings, and orders concurrently and populate the
        internal PositionBook.

        Returns:
            The populated PositionBook.
        """
        logger.info("PositionReconciler: starting startup reconciliation …")

        positions, holdings, orders = await asyncio.gather(
            self._fetch_positions(),
            self._fetch_holdings(),
            self._fetch_orders(),
            return_exceptions=True,
        )

        if isinstance(positions, Exception):
            logger.error("Failed to fetch positions: %s", positions)
            positions = []
        if isinstance(holdings, Exception):
            logger.error("Failed to fetch holdings: %s", holdings)
            holdings = []
        if isinstance(orders, Exception):
            logger.warning("Failed to fetch orders (non-critical): %s", orders)

        self._import_positions(positions)
        self._import_holdings(holdings)

        logger.info(
            "PositionReconciler: done — %d position(s) imported "
            "(%d intraday, %d holdings).",
            len(self._book),
            len(positions),
            len(holdings),
        )
        return self._book

    async def _fetch_positions(self) -> List[Dict[str, Any]]:
        rows = await self._client.get_positions()
        return rows if isinstance(rows, list) else []

    async def _fetch_holdings(self) -> List[Dict[str, Any]]:
        rows = await self._client.get_holdings()
        return rows if isinstance(rows, list) else []

    async def _fetch_orders(self) -> List[Dict[str, Any]]:
        rows = await self._client.get_orders()
        return rows if isinstance(rows, list) else []

    def _import_positions(self, positions: List[Dict[str, Any]]) -> None:
        for pos in positions:
            seg = pos.get("exchangeSegment", pos.get("exchange_segment", "UNKNOWN"))
            sec = str(pos.get("securityId", pos.get("security_id", "")))
            if not sec:
                continue
            entry = {
                "source": "position",
                "exchangeSegment": seg,
                "securityId": sec,
                "netQty": int(pos.get("netQty", pos.get("net_qty", 0))),
                "averageCostPrice": float(
                    pos.get("costPrice", pos.get("average_cost_price", 0.0))
                ),
                "productType": pos.get("productType", pos.get("product_type", "INTRADAY")),
                "raw": pos,
            }
            self._book.upsert((seg, sec), entry)

    def _import_holdings(self, holdings: List[Dict[str, Any]]) -> None:
        for h in holdings:
            seg = h.get("exchangeSegment", "NSE_EQ")
            sec = str(h.get("securityId", h.get("security_id", "")))
            if not sec:
                continue
            # Holdings are always CNC (delivery) and always long
            entry = {
                "source": "holding",
                "exchangeSegment": seg,
                "securityId": sec,
                "netQty": int(h.get("totalQty", h.get("quantity", 0))),
                "averageCostPrice": float(
                    h.get("averageCostPrice", h.get("avg_cost_price", 0.0))
                ),
                "productType": "CNC",
                "raw": h,
            }
            self._book.upsert((seg, sec), entry)

    @property
    def book(self) -> PositionBook:
        return self._book
