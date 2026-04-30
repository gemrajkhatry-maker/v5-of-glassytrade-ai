"""Option Selection Engine — Select optimal option contracts.

Implements Fabio Valentini's AMT option selection logic:
- LONG setups → CE (call) options
- SHORT setups → PE (put) options
- AAA setups → ATM options
- MR setups → OTM options for better risk/reward
- Liquidity filters (OI, spread)
- Theta kill logic for options with excessive time decay
- PCR bias alignment (NSE order flow confirmation)
- Max pain proximity for strike selection (NSE-specific)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


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
    theta: float = 0.0


@dataclass
class SelectionResult:
    """Result of option selection."""
    allowed: bool = False
    contract: Optional[OptionContract] = None
    rejection_rule: Optional[str] = None


class OptionSelectionEngine:
    """Select optimal option contracts for trading.

    Selection criteria (per AMT spec):
    - Direction determines contract type (LONG=CE, SHORT=PE)
    - Setup type determines moneyness (AAA=ATM, MR=OTM1)
    - Minimum OI threshold (15000 for NIFTY)
    - Maximum spread percentage
    - Theta kill if holding cost exceeds threshold
    - PCR bias alignment (NSE order flow confirmation)
    - Max pain proximity for strike selection (NSE-specific)
    """

    # NSE NIFTY thresholds
    MIN_OI_NIFTY = 15000
    MIN_OI_BANKNIFTY = 25000
    MAX_SPREAD_PCT = 0.05  # 5% of LTP
    THETA_EDGE_THRESHOLD = 0.02  # 2% edge for theta
    
    # PCR thresholds for bias
    PCR_BULLISH_MAX = 0.85  # PCR < 0.85 = bullish
    PCR_BEARISH_MIN = 1.15  # PCR > 1.15 = bearish

    def __init__(
        self,
        min_oi: int = 15000,
        max_spread_pct: float = 0.05,
        theta_edge_threshold: float = 0.02,
    ):
        self.min_oi = min_oi
        self.max_spread_pct = max_spread_pct
        self.theta_edge_threshold = theta_edge_threshold

    def select(
        self,
        direction: str,
        setup_type: str,
        underlying: str,
        spot_price: float,
        strike_interval: int,
        available_options: list[dict],
        expected_profit: float = 0,
        expected_hold_minutes: int = 0,
        lots: int = 1,
        lot_size: int = 75,
        pcr: float = 1.0,  # Put-Call Ratio for bias alignment
        max_pain_strike: float = 0.0,  # Max pain strike for optimization
    ) -> SelectionResult:
        """Select the best option contract for the given criteria."""
        if not available_options:
            return SelectionResult(allowed=False, rejection_rule="NO_CANDIDATES")

        # Determine contract type from direction
        contract_type = ContractType.CE if direction == "LONG" else ContractType.PE

        # Determine moneyness from setup type
        moneyness = Moneyness.ATM if setup_type == "AAA" else Moneyness.OTM1

        # PCR bias alignment (NSE order flow confirmation)
        if direction == "LONG" and pcr > self.PCR_BEARISH_MIN:
            # Bearish PCR bias but we want LONG - caution
            logger.warning("PCR bias (%.2f) conflicts with LONG direction", pcr)
        if direction == "SHORT" and pcr < self.PCR_BULLISH_MAX:
            # Bullish PCR bias but we want SHORT - caution
            logger.warning("PCR bias (%.2f) conflicts with SHORT direction", pcr)

        # Filter by liquidity (OI)
        filtered = [o for o in available_options if o.get("oi", 0) >= self.min_oi]
        if not filtered:
            return SelectionResult(allowed=False, rejection_rule="LOW_OI")

        # Filter by spread
        filtered = [
            o for o in filtered
            if o.get("spread", 0) <= o.get("ltp", 1) * self.max_spread_pct
        ]
        if not filtered:
            return SelectionResult(allowed=False, rejection_rule="HIGH_SPREAD")

        # Select by moneyness proximity to spot
        target_strike = self._get_target_strike(spot_price, moneyness, strike_interval)
        
        # Max pain optimization: prefer strikes near max pain
        if max_pain_strike > 0:
            # Weight towards max pain but still respect moneyness
            target_strike = self._align_with_max_pain(target_strike, max_pain_strike, moneyness)
        best = min(filtered, key=lambda o: abs(o["strike"] - target_strike))

        # Check theta kill
        if expected_profit > 0 and expected_hold_minutes > 0:
            theta = best.get("theta", 0)
            total_theta_cost = abs(theta) * expected_hold_minutes * lots * lot_size / 1440
            if total_theta_cost > expected_profit * self.theta_edge_threshold:
                return SelectionResult(
                    allowed=False,
                    rejection_rule="THETA_KILL",
                )

        contract = OptionContract(
            symbol=best.get("symbol", ""),
            underlying=underlying,
            strike=best["strike"],
            expiry=best.get("expiry", ""),
            option_type=contract_type,
            ltp=best.get("ltp", 0),
            bid=best.get("bid", 0),
            ask=best.get("ask", 0),
            volume=best.get("volume", 0),
            oi=best.get("oi", 0),
            moneyness=moneyness,
            theta=best.get("theta", 0),
        )

        return SelectionResult(allowed=True, contract=contract)

    def _get_target_strike(self, spot: float, moneyness: Moneyness, interval: int) -> float:
        """Calculate target strike based on moneyness."""
        if moneyness == Moneyness.ATM:
            return round(spot / interval) * interval
        elif moneyness == Moneyness.OTM1:
            return round(spot / interval) * interval + interval
        elif moneyness == Moneyness.OTM2:
            return round(spot / interval) * interval + 2 * interval
        elif moneyness == Moneyness.ITM1:
            return round(spot / interval) * interval - interval
        return round(spot / interval) * interval

    def _align_with_max_pain(
        self,
        target_strike: float,
        max_pain_strike: float,
        moneyness: Moneyness,
    ) -> float:
        """Align strike selection with max pain for better probability.
        
        Max pain is where market makers have maximum losses at expiry.
        Strikes near max pain have higher pin probability.
        """
        distance_from_max_pain = abs(target_strike - max_pain_strike)
        
        # If target is more than 100 points from max pain, consider moving closer
        if distance_from_max_pain > 100:
            # Move 50% towards max pain as compromise
            return target_strike - (distance_from_max_pain * 0.5 * (1 if target_strike > max_pain_strike else -1))
        
        return target_strike

    def get_filtered_contracts(
        self,
        contracts: list[OptionContract],
        spot_price: float,
        moneyness: Moneyness = Moneyness.ATM,
    ) -> list[OptionContract]:
        """Filter contracts by moneyness proximity."""
        if not contracts:
            return []
        return sorted(
            contracts,
            key=lambda c: abs(c.strike - self._get_target_strike(spot_price, moneyness, 50))
        )[:5]