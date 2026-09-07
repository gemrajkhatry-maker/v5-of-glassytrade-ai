"""Broker-neutral tradable contract identity.

Broker security identifiers, order payload fields and authentication details
belong inside broker adapters. Quant/domain code uses ``ContractRef`` only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ContractRef:
    """Portable identity and exchange constraints for one derivative contract."""

    symbol: str
    exchange: str
    expiry: str
    lot_size: int
    tick_size: float
    strike: float | None = None
    option_type: str = ""
    multiplier: float = 1.0
    product_type: str = "INTRADAY"

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip()
        exchange = str(self.exchange).strip().upper()
        expiry = str(self.expiry).strip()
        option_type = str(self.option_type or "").strip().upper()
        if option_type in {"CALL", "C"}:
            option_type = "CE"
        elif option_type in {"PUT", "P"}:
            option_type = "PE"

        if not symbol or not exchange:
            raise ValueError("ContractRef symbol and exchange are required")
        if not expiry:
            raise ValueError("ContractRef expiry is required")
        try:
            date.fromisoformat(expiry)
        except ValueError as exc:
            raise ValueError("ContractRef expiry must be YYYY-MM-DD") from exc
        if int(self.lot_size) != self.lot_size or int(self.lot_size) <= 0:
            raise ValueError("ContractRef lot_size must be a positive integer")
        if float(self.tick_size) <= 0:
            raise ValueError("ContractRef tick_size must be positive")
        if float(self.multiplier) <= 0:
            raise ValueError("ContractRef multiplier must be positive")
        if option_type not in {"", "CE", "PE"}:
            raise ValueError("ContractRef option_type must be CE, PE or empty")
        if option_type and self.strike is None:
            raise ValueError("Option ContractRef requires strike")
        if self.strike is not None and float(self.strike) <= 0:
            raise ValueError("ContractRef strike must be positive")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "expiry", expiry)
        object.__setattr__(self, "lot_size", int(self.lot_size))
        object.__setattr__(self, "tick_size", float(self.tick_size))
        object.__setattr__(self, "option_type", option_type)
        object.__setattr__(self, "multiplier", float(self.multiplier))
        object.__setattr__(self, "product_type", str(self.product_type).strip().upper())
