"""Paper broker adapter with realistic trade cost simulation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import logging

from app.domain.shared.port.broker import IBroker
from app.domain.trading.model.aggregates import Portfolio
from app.domain.trading.model.entities import Position, Signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradeCosts:
    notional: float
    slippage: float
    stt: float
    exchange_fee: float
    brokerage: float
    gst: float
    sebi: float

    def total(self) -> float:
        return self.slippage + self.stt + self.exchange_fee + self.brokerage + self.gst + self.sebi


class PaperBrokerAdapter(IBroker):
    """Paper execution adapter with deterministic local state transitions."""

    def __init__(
        self,
        slippage_bps: float = 15.0,
        stt_pct: float = 0.000625,
        exchange_fee_pct: float = 0.000495,
        brokerage_per_order: float = 20.0,
        gst_pct: float = 0.18,
        sebi_pct: float = 0.000001,
        cost_model_enabled: bool = True,
    ) -> None:
        self._slippage_bps = slippage_bps
        self._stt_pct = stt_pct
        self._exchange_fee_pct = exchange_fee_pct
        self._brokerage = brokerage_per_order
        self._gst_pct = gst_pct
        self._sebi_pct = sebi_pct
        self._cost_model_enabled = cost_model_enabled
        self._open_orders: set[str] = set()
        self._positions: dict[str, Position] = {}

    def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Position | None:
        entry_price = float(signal.price)
        if entry_price <= 0:
            logger.error("Paper broker rejected invalid signal price=%s for %s", entry_price, symbol)
            return None
        scale_in = bool((signal.metadata or {}).get("scale_in", False))
        scale_fraction = 0.4 if scale_in else 1.0
        position = portfolio.open_position(signal, symbol, scale_fraction=scale_fraction)
        if not position:
            return None

        position.metadata = position.metadata or {}
        # Record adapter-specific metadata for downstream PnL checks.
        position.metadata["broker"] = "paper"
        position.metadata["brokerside"] = "paper"

        if self._cost_model_enabled:
            cost = self._compute_costs(float(position.entry_price), float(position.size), is_sell=False)
            position.metadata["entry_cost"] = cost.total()
            position.metadata["entry_cost_breakdown"] = cost.__dict__

        self._open_orders.add(position.id)
        self._positions[position.id] = position
        return position

    def cancel_order(self, order_id: str) -> bool:
        if order_id not in self._open_orders:
            return False
        self._open_orders.remove(order_id)
        return True

    def close_position(self, position_id: str, price: float) -> bool:
        position = self._positions.get(position_id)
        if position is None:
            return False
        if not position.is_open:
            return True
        if position_id in self._open_orders:
            position.close(Decimal(str(price)), "system.close", reason="broker-close")
            if self._cost_model_enabled:
                cost = self._compute_costs(float(price), float(position.size), is_sell=True)
                position.metadata = position.metadata or {}
                position.metadata["exit_cost"] = cost.total()
            self._open_orders.remove(position_id)
            return True
        return False

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_account(self) -> dict[str, Any]:
        open_positions = [p for p in self._positions.values() if p.is_open]
        return {
            "balance": None,
            "equity": None,
            "open_positions": len(open_positions),
            "positions": [p.id for p in open_positions],
        }

    def _compute_costs(self, price: float, size: float, *, is_sell: bool) -> TradeCosts:
        notional = price * size
        slippage = abs(notional) * (self._slippage_bps / 10000.0)
        stt = notional * (self._stt_pct if is_sell else 0.0)
        exchange_fee = abs(notional) * self._exchange_fee_pct
        brokerage = self._brokerage * 2.0
        gst = brokerage * self._gst_pct
        sebi = abs(notional) * self._sebi_pct
        return TradeCosts(
            notional=notional,
            slippage=slippage,
            stt=stt,
            exchange_fee=exchange_fee,
            brokerage=brokerage,
            gst=gst,
            sebi=sebi,
        )

