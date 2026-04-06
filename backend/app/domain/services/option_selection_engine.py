"""Option Selection Engine — Stub.

Planned feature: Select optimal option contracts based on moneyness,
liquidity, and strategy requirements.

Status: Stub — types defined but not fully implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Moneyness(str, Enum):
    ATM = "ATM"
    OTM1 = "OTM1"
    OTM2 = "OTM2"
    ITM1 = "ITM1"
    ITM2 = "ITM2"


class ContractType(str, Enum):
    CE = "CE"
    PE = "PE"


@dataclass
class OptionContract:
    """Represents a single option contract."""
    symbol: str = ""
    underlying: str = ""
    strike: float = 0.0
    expiry: str = ""
    option_type: ContractType = ContractType.CE
    ltp: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    volume: float = 0.0
    oi: int = 0
    moneyness: Moneyness = Moneyness.ATM
    implied_vol: float = 0.0


class OptionSelectionEngine:
    """Select optimal option contracts for trading.

    Stub implementation — returns first matching contract.
    """

    def select(
        self,
        underlying: str,
        spot_price: float,
        direction: str = "LONG",
        moneyness: Moneyness = Moneyness.ATM,
        contracts: list[OptionContract] | None = None,
    ) -> Optional[OptionContract]:
        """Select the best option contract for the given criteria."""
        return None

    def get_filtered_contracts(
        self,
        contracts: list[OptionContract],
        spot_price: float,
        moneyness: Moneyness = Moneyness.ATM,
    ) -> list[OptionContract]:
        """Filter contracts by moneyness proximity."""
        return contracts or []
