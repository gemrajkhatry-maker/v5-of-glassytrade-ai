"""Paper Trading Executor — simulated execution with configurable slippage & commission."""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from appv2.domain.ports.broker import BrokerPort
from appv2.domain.enums.signal_type import OrderType, OrderSide, OrderStatus, TradeStatus
from appv2.domain.models.trade import Trade
from appv2.config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class PaperOrder:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float
    status: OrderStatus = OrderStatus.FILLED
    fill_price: float = 0.0
    fill_time: float = 0.0


class PaperBrokerAdapter(BrokerPort):
    """Paper broker for simulated execution.

    Adds configurable slippage and commission to test realism.
    """

    def __init__(
        self,
        slippage_bps: int | None = None,
        commission_per_trade: float | None = None,
    ):
        self._slippage_bps = slippage_bps or settings.PAPER_SLIPPAGE_BPS
        self._commission = commission_per_trade or settings.PAPER_COMMISSION_PER_TRADE
        self._order_counter: int = 0
        self._orders: list[PaperOrder] = []

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
        """Simulate order placement with slippage."""
        self._order_counter += 1
        order_id = f"PAPER-{self._order_counter:06d}"

        # Simulate fill at current price with slippage
        exec_price = price
        if self._slippage_bps > 0:
            slippage = price * self._slippage_bps / 10_000
            if side == OrderSide.BUY:
                exec_price = price + slippage
            else:
                exec_price = price - slippage

        order = PaperOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=OrderStatus.FILLED,
            fill_price=round(exec_price, 4),
            fill_time=time.time(),
        )
        self._orders.append(order)

        logger.info(
            "PAPER FILLED: %s %s %d @ %.4f (slippage: %.0f bps, commission: %.2f)",
            order_id, symbol, quantity, exec_price, self._slippage_bps, self._commission,
        )

        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        for order in self._orders:
            if order.order_id == order_id:
                order.status = OrderStatus.CANCELLED
                return True
        return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        for order in self._orders:
            if order.order_id == order_id:
                return order.status
        return OrderStatus.PENDING

    async def get_positions(self) -> list[dict]:
        return []  # Paper broker doesn't track positions

    async def get_open_orders(self) -> list[dict]:
        return [o.__dict__ for o in self._orders if o.status == OrderStatus.FILLED]

    async def get_portfolio(self) -> dict:
        return {
            "balance": settings.CAPITAL,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
        }

    async def square_off_position(self, symbol: str) -> bool:
        return True

    async def get_available_balance(self) -> float:
        return settings.CAPITAL

    @property
    def commission(self) -> float:
        return self._commission
