"""
Mock implementations for testing.

This module contains test-only mocks that should NEVER be used in production.
"""

from __future__ import annotations

import uuid
import random
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class DryRunBroker:
    """
    Mock broker for DRY RUN testing mode.
    
    WARNING: This is for testing only. Never use in production.
    
    Simulates all operations without real execution:
    - Mock order placement with generated IDs
    - Mock quotes with realistic prices
    - Mock historical data
    - Operation logging for audit
    """

    def __init__(self):
        self.operation_log: List[Dict[str, Any]] = []
        self._order_counter = 0

    def place_order_mock(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        side: str,
        order_type: str,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Simulate order placement."""
        self._order_counter += 1
        order_id = f"DRY_RUN_{self._order_counter}_{uuid.uuid4().hex[:8]}"

        operation = {
            "operation": "place_order",
            "order_id": order_id,
            "symbol": symbol,
            "exchange": exchange,
            "quantity": quantity,
            "side": side,
            "order_type": order_type,
            "price": price,
            "status": "COMPLETED",
            "dry_run": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self.operation_log.append(operation)
        logger.info(f"[DRY RUN] Simulated order: {order_id} - {side} {quantity} {symbol}")

        return operation

    def cancel_order_mock(self, order_id: str) -> Dict[str, Any]:
        """Simulate order cancellation."""
        operation = {
            "operation": "cancel_order",
            "order_id": order_id,
            "cancelled": True,
            "dry_run": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self.operation_log.append(operation)
        logger.info(f"[DRY RUN] Simulated cancellation: {order_id}")

        return operation

    def get_quote_mock(self, symbol: str) -> Dict[str, Any]:
        """Simulate quote retrieval."""
        base_price = {
            "RELIANCE": 2500.0,
            "TCS": 3500.0,
            "INFY": 1500.0,
            "HDFCBANK": 1600.0,
            "NIFTY": 22000.0,
            "BANKNIFTY": 48000.0,
        }.get(symbol.split(":")[-1] if ":" in symbol else symbol, 1000.0)

        ltp = base_price * random.uniform(0.98, 1.02)

        return {
            "symbol": symbol,
            "ltp": round(ltp, 2),
            "open": round(base_price * 0.99, 2),
            "high": round(base_price * 1.02, 2),
            "low": round(base_price * 0.98, 2),
            "close": round(base_price, 2),
            "volume": random.randint(100000, 1000000),
            "dry_run": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_historical_mock(
        self,
        symbol: str,
        exchange: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> Dict[str, Any]:
        """Simulate historical data retrieval."""
        base_price = 1000.0
        candles = []

        for i in range(30):
            open_price = base_price * random.uniform(0.95, 1.05)
            high_price = open_price * random.uniform(1.01, 1.03)
            low_price = open_price * random.uniform(0.97, 0.99)
            close_price = open_price * random.uniform(0.98, 1.02)

            candles.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2),
                "volume": random.randint(10000, 100000),
            })

        return {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "candles": candles,
            "count": len(candles),
            "from_date": from_date,
            "to_date": to_date,
            "dry_run": True,
        }
