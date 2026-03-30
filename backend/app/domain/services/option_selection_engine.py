"""Option Selection Engine — deterministic strike selection + liquidity validation.

CHANGE 9: Fully deterministic option contract selection.
No LLM involvement. Pure math and rule-based logic.

RULES:
  1. Contract type: CE for LONG, PE for SHORT (strict)
  2. Moneyness selection:
     - AAA Trend: ATM or ITM-1 (high delta, follow underlying)
     - Mean Reversion: OTM-1 (cheap, captures rotation)
     - Scalp: ATM (fast delta response)
  3. Liquidity validation:
     - Min OI: 100,000 (NIFTY), 30,000 (BANKNIFTY)
     - Max spread: 10% of option premium
     - Min volume: 500
  4. Theta validation (pre-entry):
     - holding_cost = theta_per_minute × hold_minutes × lots × lot_size
     - IF holding_cost > 20% of expected_profit → SKIP
  5. Expiry selection:
     - Monday-Wednesday: current week expiry
     - Thursday-Friday: next week expiry (avoid theta decay on weekend)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Moneyness(str, Enum):
    ATM = "ATM"
    ITM_1 = "ITM_1"
    ITM_2 = "ITM_2"
    OTM_1 = "OTM_1"
    OTM_2 = "OTM_2"


class ContractType(str, Enum):
    CE = "CE"
    PE = "PE"


@dataclass(frozen=True)
class OptionContract:
    """Selected option contract."""

    symbol: str
    contract_type: ContractType
    strike: float
    expiry: str
    moneyness: Moneyness
    ltp: float
    oi: int
    volume: int
    spread_pct: float
    delta: float
    theta: float


@dataclass(frozen=True)
class SelectionResult:
    """Result of option selection."""

    contract: OptionContract | None
    allowed: bool
    reason: str
    rejection_rule: str = ""


class OptionSelectionEngine:
    """Deterministic option contract selection engine.

    Selects the optimal option contract based on:
    - Trade direction (CE/PE)
    - Setup type (AAA/MR/scalp)
    - Moneyness (ATM/ITM/OTM)
    - Liquidity (OI, spread, volume)
    - Theta cost
    """

    # Min OI by underlying
    MIN_OI = {
        "NIFTY": 100_000,
        "BANKNIFTY": 30_000,
        "FINNIFTY": 10_000,
        "CRUDEOIL": 10,
        "NATURALGAS": 500,
    }

    # Strike intervals
    STRIKE_INTERVALS = {
        "NIFTY": 50,
        "BANKNIFTY": 100,
        "FINNIFTY": 50,
        "CRUDEOIL": 50,
        "NATURALGAS": 5,
    }

    # Moneyness by setup type
    MONEYNESS_MAP = {
        "AAA": Moneyness.ATM,
        "MR": Moneyness.OTM_1,
        "scalp": Moneyness.ATM,
    }

    def __init__(
        self,
        max_spread_pct: float = 0.10,  # 10% of premium
        min_volume: int = 500,
        theta_edge_threshold: float = 0.20,  # 20% of expected profit
        moneyness_override: Moneyness | None = None,
    ) -> None:
        self._max_spread = max_spread_pct
        self._min_volume = min_volume
        self._theta_threshold = theta_edge_threshold
        self._moneyness_override = moneyness_override

    def select(
        self,
        direction: str,
        setup_type: str,
        underlying: str,
        spot_price: float,
        strike_interval: float,
        available_options: list[dict],  # list of option data dicts
        expected_profit: float = 0,
        expected_hold_minutes: float = 30,
        lots: int = 1,
        lot_size: int = 75,
    ) -> SelectionResult:
        """Select the best option contract.

        Args:
            direction: "LONG" or "SHORT"
            setup_type: "AAA", "MR", or "scalp"
            underlying: "NIFTY", "BANKNIFTY", etc.
            spot_price: Current spot price
            strike_interval: Strike interval for the underlying
            available_options: List of option dicts with strike, ltp, oi, volume, spread
            expected_profit: Expected profit from the trade
            expected_hold_minutes: Expected hold time
            lots: Number of lots
            lot_size: Lot size
        """
        # Step 1: Contract type
        contract_type = ContractType.CE if direction == "LONG" else ContractType.PE

        # Step 2: Moneyness
        moneyness = self._moneyness_override or self.MONEYNESS_MAP.get(
            setup_type, Moneyness.ATM
        )

        # Step 3: Compute target strike
        target_strike = self._compute_target_strike(
            spot_price,
            strike_interval,
            moneyness,
            contract_type,
        )

        # Step 4: Find matching contracts
        candidates = self._find_candidates(
            available_options,
            contract_type,
            target_strike,
            strike_interval,
        )

        if not candidates:
            return SelectionResult(
                contract=None,
                allowed=False,
                reason=f"No {contract_type.value} contracts near strike {target_strike:.0f}",
                rejection_rule="NO_CANDIDATES",
            )

        # Step 5: Filter by liquidity
        min_oi = self.MIN_OI.get(underlying, 10_000)
        for c in candidates:
            oi_ok = c.get("oi", 0) >= min_oi
            spread_ok = c.get("spread", 0) / max(c.get("ltp", 1), 1) <= self._max_spread
            volume_ok = c.get("volume", 0) >= self._min_volume

            if not oi_ok:
                continue
            if not spread_ok:
                continue
            if not volume_ok:
                continue

            # Step 6: Theta validation
            theta = c.get("theta", 0)
            if abs(theta) > 0 and expected_profit > 0:
                holding_cost = (
                    abs(theta) / 375 * expected_hold_minutes * lots * lot_size
                )
                if holding_cost / expected_profit > self._theta_threshold:
                    return SelectionResult(
                        contract=None,
                        allowed=False,
                        reason=f"Theta kills edge: cost={holding_cost:.0f} vs profit={expected_profit:.0f}",
                        rejection_rule="THETA_KILL",
                    )

            # Contract selected
            contract = OptionContract(
                symbol=f"{underlying} {c.get('expiry', '')} {c.get('strike', 0)} {contract_type.value}",
                contract_type=contract_type,
                strike=c.get("strike", 0),
                expiry=c.get("expiry", ""),
                moneyness=moneyness,
                ltp=c.get("ltp", 0),
                oi=c.get("oi", 0),
                volume=c.get("volume", 0),
                spread_pct=c.get("spread", 0) / max(c.get("ltp", 1), 1),
                delta=c.get("delta", 0),
                theta=theta,
            )

            return SelectionResult(
                contract=contract,
                allowed=True,
                reason=f"Selected {contract_type.value} strike={contract.strike:.0f} OI={contract.oi}",
            )

        return SelectionResult(
            contract=None,
            allowed=False,
            reason=f"No {contract_type.value} contracts pass liquidity filter",
            rejection_rule="LIQUIDITY",
        )

    def _compute_target_strike(
        self,
        spot: float,
        interval: float,
        moneyness: Moneyness,
        contract_type: ContractType,
    ) -> float:
        """Compute target strike based on moneyness."""
        atm = round(spot / interval) * interval

        if moneyness == Moneyness.ATM:
            return atm
        elif moneyness == Moneyness.ITM_1:
            if contract_type == ContractType.CE:
                return atm - interval  # ITM CE: strike below spot
            else:
                return atm + interval  # ITM PE: strike above spot
        elif moneyness == Moneyness.ITM_2:
            if contract_type == ContractType.CE:
                return atm - 2 * interval
            else:
                return atm + 2 * interval
        elif moneyness == Moneyness.OTM_1:
            if contract_type == ContractType.CE:
                return atm + interval  # OTM CE: strike above spot
            else:
                return atm - interval  # OTM PE: strike below spot
        else:  # OTM_2
            if contract_type == ContractType.CE:
                return atm + 2 * interval
            else:
                return atm - 2 * interval

    def _find_candidates(
        self,
        options: list[dict],
        contract_type: ContractType,
        target_strike: float,
        interval: float,
    ) -> list[dict]:
        """Find contracts matching the target strike."""
        return [
            opt
            for opt in options
            if abs(opt.get("strike", 0) - target_strike) <= interval * 0.6
        ]
