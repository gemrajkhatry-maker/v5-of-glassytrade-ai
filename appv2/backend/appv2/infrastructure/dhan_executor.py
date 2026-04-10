"""Dhan Order Executor — wraps existing brokers library for live order placement.

Reuses: brokers/broker/dhan/ (DhanBroker order methods)
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path

_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from appv2.domain.ports.broker import BrokerPort
from appv2.domain.enums.signal_type import OrderType, OrderSide, OrderStatus

logger = logging.getLogger(__name__)


class DhanExecutorAdapter(BrokerPort):
    """Adapts Dhan broker library to BrokerPort interface for live execution.

    Safety:
    - LIVE_TRADING env var must be True to place real orders
    - Otherwise, delegates to PaperBrokerAdapter
    """

    def __init__(self, access_token: str, client_id: str, live: bool = False):
        self._access_token = access_token
        self._client_id = client_id
        self._live = live
        self._broker = None
        self._paper = None

    def _ensure_broker(self):
        if self._broker is not None:
            return
        if self._live:
            try:
                from broker.dhan.application.broker import DhanBroker
                from broker.dhan.application.config import DhanConfig
                config = DhanConfig(
                    access_token=self._access_token,
                    client_id=self._client_id,
                )
                self._broker = DhanBroker(config)
                logger.warning("LIVE TRADING MODE — real orders will be placed!")
            except Exception as e:
                logger.error("Failed to initialize DhanBroker: %s", e)
                raise
        else:
            from appv2.infrastructure.paper_executor import PaperBrokerAdapter
            self._paper = PaperBrokerAdapter()
            logger.info("Paper trading mode")

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float = 0.0,
        trigger_price: float = 0.0,
        square_off: float = 0.0,
        stop_loss_value: float = 0.0,
    ) -> str:
        self._ensure_broker()
        if self._live and self._broker:
            # Map OrderType to Dhan order type
            dhan_order_type = self._map_order_type(order_type)
            dhan_side = "BUY" if side == OrderSide.BUY else "SELL"

            if self._live:
                logger.warning(
                    "LIVE ORDER: %s %s %s %d @ %.4f",
                    dhan_side, symbol, dhan_order_type, quantity, price,
                )

            try:
                order_id = self._broker.place_order(
                    symbol=symbol,
                    side=dhan_side,
                    order_type=dhan_order_type,
                    quantity=quantity,
                    price=price,
                    trigger_price=trigger_price,
                )
                return order_id
            except Exception as e:
                logger.error("Live order error: %s", e)
                raise
        elif self._paper:
            return await self._paper.place_order(
                symbol, side, order_type, quantity, price, trigger_price,
                square_off, stop_loss_value,
            )
        raise RuntimeError("No execution backend available")

    @staticmethod
    def _map_order_type(order_type: OrderType) -> str:
        mapping = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.SL: "STOP_LOSS",
            OrderType.SL_MARKET: "STOP_LOSS_MARKET",
            OrderType.BRACKET: "BRACKET",
        }
        return mapping.get(order_type, "MARKET")

    async def cancel_order(self, order_id: str) -> bool:
        self._ensure_broker()
        if self._live and self._broker:
            return self._broker.cancel_order(order_id)
        if self._paper:
            return await self._paper.cancel_order(order_id)
        return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        self._ensure_broker()
        if self._live and self._broker:
            status = self._broker.get_order_status(order_id)
            return OrderStatus(status)
        if self._paper:
            return await self._paper.get_order_status(order_id)
        return OrderStatus.PENDING

    async def get_positions(self) -> list[dict]:
        self._ensure_broker()
        if self._live and self._broker:
            return self._broker.get_positions()
        if self._paper:
            return await self._paper.get_positions()
        return []

    async def get_open_orders(self) -> list[dict]:
        self._ensure_broker()
        if self._live and self._broker:
            return self._broker.get_open_orders()
        if self._paper:
            return await self._paper.get_open_orders()
        return []

    async def get_portfolio(self) -> dict:
        self._ensure_broker()
        if self._live and self._broker:
            return self._broker.get_portfolio()
        if self._paper:
            return await self._paper.get_portfolio()
        return {}

    async def square_off_position(self, symbol: str) -> bool:
        self._ensure_broker()
        if self._live and self._broker:
            return self._broker.square_off(symbol)
        if self._paper:
            return await self._paper.square_off_position(symbol)
        return False

    async def get_available_balance(self) -> float:
        self._ensure_broker()
        if self._live and self._broker:
            return self._broker.get_available_balance()
        if self._paper:
            return await self._paper.get_available_balance()
        return 0.0
