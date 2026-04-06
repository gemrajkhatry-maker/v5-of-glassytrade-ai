"""
Option scanner — contract selection and ranking.

Selects option contracts based on exchange mode and filters.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from src.config.instruments import InstrumentConfig


@dataclass
class OptionContract:
    """Option contract details."""

    symbol: str
    strike: float
    option_type: str  # CE or PE
    expiry: str
    security_id: str
    exchange: str
    lot_size: int
    ltp: float = 0.0
    oi: int = 0
    volume: int = 0


class OptionScanner:
    """
    Scan and select option contracts.

    Filters by:
    - Exchange mode (MCX, NSE)
    - Strike range
    - Expiry
    - Liquidity (OI, volume)
    """

    def __init__(self):
        self._contracts: Dict[str, OptionContract] = {}

    def scan(
        self,
        underlying: str,
        exchange: str,
        option_chain: List[Dict],
        current_price: float,
        strike_range_pct: float = 0.05,  # ±5% from current price
    ) -> List[OptionContract]:
        """
        Scan option chain and select contracts.

        Args:
            underlying: Underlying symbol
            exchange: Exchange segment
            option_chain: Option chain data from Dhan
            current_price: Current underlying price
            strike_range_pct: Strike range percentage

        Returns:
            List of selected OptionContracts.
        """
        selected = []
        min_strike = current_price * (1 - strike_range_pct)
        max_strike = current_price * (1 + strike_range_pct)

        for option in option_chain:
            try:
                strike = float(option.get("strike_price", 0))
                option_type = option.get("option_type", "")
                expiry = option.get("expiry_date", "")

                # Filter by strike range
                if not (min_strike <= strike <= max_strike):
                    continue

                # Create contract
                contract = OptionContract(
                    symbol=f"{underlying}{strike}{option_type}",
                    strike=strike,
                    option_type=option_type,
                    expiry=expiry,
                    security_id=str(option.get("security_id", "")),
                    exchange=exchange,
                    lot_size=int(option.get("lot_size", 1)),
                    ltp=float(option.get("last_price", 0)),
                    oi=int(option.get("open_interest", 0)),
                    volume=int(option.get("volume", 0)),
                )

                # Filter by liquidity
                if contract.oi > 100:  # Minimum OI
                    selected.append(contract)

            except (ValueError, TypeError):
                continue

        # Sort by OI (highest first)
        selected.sort(key=lambda c: c.oi, reverse=True)

        return selected

    def select_atm(
        self,
        contracts: List[OptionContract],
        current_price: float,
    ) -> Optional[OptionContract]:
        """
        Select ATM (At The Money) contract.

        Args:
            contracts: List of contracts
            current_price: Current underlying price

        Returns:
            ATM contract or None.
        """
        if not contracts:
            return None

        # Find closest strike to current price
        closest = min(contracts, key=lambda c: abs(c.strike - current_price))
        return closest

    def select_itm(
        self,
        contracts: List[OptionContract],
        current_price: float,
        option_type: str,
    ) -> Optional[OptionContract]:
        """
        Select ITM (In The Money) contract.

        Args:
            contracts: List of contracts
            current_price: Current underlying price
            option_type: CE or PE

        Returns:
            ITM contract or None.
        """
        itm_contracts = []

        for contract in contracts:
            if contract.option_type != option_type:
                continue

            if option_type == "CE":
                # CE is ITM when strike < current price
                if contract.strike < current_price:
                    itm_contracts.append(contract)
            else:  # PE
                # PE is ITM when strike > current price
                if contract.strike > current_price:
                    itm_contracts.append(contract)

        if not itm_contracts:
            return None

        # Return closest to ATM
        return min(itm_contracts, key=lambda c: abs(c.strike - current_price))