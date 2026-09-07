"""Deterministic paper execution simulator.

This is deliberately broker-neutral. It resolves only ``ContractRef`` and
never carries broker security IDs or broker payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from quant.contracts.contracts import ContractRef
from quant.execution.paper_contracts import PaperContractResolver
from quant.execution.trade_costs import TradeCosts, compute_fill_costs


class PaperOrderStatus(str, Enum):
    FILLED = "FILLED"


@dataclass(frozen=True)
class PaperFill:
    order_id: str
    instrument_key: str
    side: str
    requested_quantity: int
    filled_quantity: int
    fill_price: float
    status: PaperOrderStatus
    costs: TradeCosts
    net_cash_flow: float


class PaperExecutionSimulator:
    """Idempotent paper fills with explicit execution mode."""

    def __init__(self, *, fill_mode: str = "instant_mid", slippage_bps: float = 15.0) -> None:
        if fill_mode not in {"instant_mid", "bid_ask"}:
            raise ValueError(f"unsupported paper fill mode: {fill_mode}")
        self.fill_mode = fill_mode
        self.slippage_bps = float(slippage_bps)
        self._resolver = PaperContractResolver()
        self._fills: dict[str, PaperFill] = {}

    @property
    def fills(self) -> tuple[PaperFill, ...]:
        return tuple(self._fills.values())

    def submit(
        self,
        *,
        order_id: str,
        contract: ContractRef,
        side: str,
        quantity: int,
        reference_price: float,
        bid: float = 0.0,
        ask: float = 0.0,
    ) -> PaperFill:
        if not order_id:
            raise ValueError("paper order_id is required")
        side = str(side).upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("paper side must be BUY or SELL")
        if quantity <= 0 or quantity % contract.lot_size != 0:
            raise ValueError("paper quantity must be a positive lot multiple")
        if reference_price <= 0:
            raise ValueError("paper reference_price must be positive")

        resolved = self._resolver.resolve(contract)
        if order_id in self._fills:
            previous = self._fills[order_id]
            if (
                previous.instrument_key != resolved.instrument_key
                or previous.side != side
                or previous.requested_quantity != quantity
            ):
                raise ValueError(f"paper order_id already exists with a different request: {order_id}")
            return previous

        if self.fill_mode == "bid_ask":
            if bid <= 0 or ask <= 0 or bid > ask:
                raise ValueError("bid_ask paper mode requires a valid bid/ask")
            fill_price = ask if side == "BUY" else bid
        else:
            fill_price = float(reference_price)

        notional = float(fill_price) * int(quantity)
        costs = compute_fill_costs(
            notional=notional,
            slippage_bps=self.slippage_bps,
            is_sell=side == "SELL",
        )
        cash_flow = -notional if side == "BUY" else notional

        fill = PaperFill(
            order_id=order_id,
            instrument_key=resolved.instrument_key,
            side=side,
            requested_quantity=int(quantity),
            filled_quantity=int(quantity),
            fill_price=float(fill_price),
            status=PaperOrderStatus.FILLED,
            costs=costs,
            net_cash_flow=cash_flow - costs.total,
        )
        self._fills[order_id] = fill
        return fill
