"""Paper-only contract resolution.

Paper execution must use a deterministic internal instrument identity without
inventing or exposing a broker security ID.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant.contracts.contracts import ContractRef


@dataclass(frozen=True)
class PaperContract:
    """Resolved paper instrument with no broker-specific identity."""

    instrument_key: str
    symbol: str
    exchange: str
    expiry: str
    lot_size: int
    tick_size: float
    strike: float | None = None
    option_type: str = ""
    multiplier: float = 1.0
    product_type: str = "INTRADAY"


class PaperContractResolver:
    """Resolve a validated ContractRef into a deterministic paper contract."""

    def resolve(self, ref: ContractRef) -> PaperContract:
        if not isinstance(ref, ContractRef):
            raise ValueError("PaperContractResolver requires a ContractRef")
        instrument_key = ":".join(
            (
                ref.exchange,
                ref.symbol,
                ref.expiry,
                "" if ref.strike is None else str(ref.strike),
                ref.option_type,
            )
        )
        return PaperContract(
            instrument_key=instrument_key,
            symbol=ref.symbol,
            exchange=ref.exchange,
            expiry=ref.expiry,
            lot_size=ref.lot_size,
            tick_size=ref.tick_size,
            strike=ref.strike,
            option_type=ref.option_type,
            multiplier=ref.multiplier,
            product_type=ref.product_type,
        )
