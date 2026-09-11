"""Broker-neutral execution port owned by the quant domain."""
from __future__ import annotations

from abc import ABC, abstractmethod
from quant.contracts.aggregates import Portfolio
from quant.contracts.entities import Position, Signal


class IBroker(ABC):
    @abstractmethod
    def execute_order(self, signal: Signal, portfolio: Portfolio, symbol: str, contract_ref=None) -> Position | None:
        """Submit an entry for the exact contract."""
        ...

    @abstractmethod
    def close_position(self, symbol: str, side: str, quantity: int, portfolio: Portfolio,
                       reference_price: float | None = None, contract_ref=None) -> Position | None:
        """Submit an exit for the exact contract."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    def place_stop_loss(
        self,
        symbol: str,
        side: str,
        quantity: int,
        stop_price: float,
        contract_ref=None,
    ) -> str | None:
        """Submit an exchange-side Stop-Loss Market (SL-M) order."""
        raise NotImplementedError("Native SL-M placement not implemented by this broker")




__all__ = ["IBroker"]
