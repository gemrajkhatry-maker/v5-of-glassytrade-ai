"""Option contract selection for AMT/ML signals."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

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
    allowed: bool = False
    contract: OptionContract | None = None
    rejection_rule: str | None = None


class OptionSelectionEngine:
    MIN_OI_NIFTY = 15000
    MIN_OI_BANKNIFTY = 25000
    MAX_SPREAD_PCT = 0.05
    THETA_EDGE_THRESHOLD = 0.02
    PCR_BULLISH_MAX = 0.85
    PCR_BEARISH_MIN = 1.15

    def __init__(
        self,
        min_oi: int = 15000,
        max_spread_pct: float = 0.05,
        theta_edge_threshold: float = 0.02,
    ) -> None:
        self.min_oi = int(min_oi)
        self.max_spread_pct = float(max_spread_pct)
        self.theta_edge_threshold = float(theta_edge_threshold)

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
        pcr: float = 1.0,
        max_pain_strike: float = 0.0,
    ) -> SelectionResult:
        if not available_options:
            return SelectionResult(allowed=False, rejection_rule="NO_CANDIDATES")

        contract_type = ContractType.CE if direction == "LONG" else ContractType.PE
        if direction == "LONG" and pcr > self.PCR_BEARISH_MIN:
            logger.warning("PCR bias %.2f conflicts with LONG direction", pcr)
        if direction == "SHORT" and pcr < self.PCR_BULLISH_MAX:
            logger.warning("PCR bias %.2f conflicts with SHORT direction", pcr)

        filtered = [o for o in available_options if o.get("oi", 0) >= self.min_oi]
        if not filtered:
            return SelectionResult(allowed=False, rejection_rule="LOW_OI")

        filtered = [
            o for o in filtered if o.get("spread", 0) <= o.get("ltp", 1) * self.max_spread_pct
        ]
        if not filtered:
            return SelectionResult(allowed=False, rejection_rule="HIGH_SPREAD")

        moneyness = Moneyness.ATM if setup_type == "AAA" else Moneyness.OTM1
        target_strike = self._get_target_strike(spot_price, moneyness, strike_interval)
        if max_pain_strike > 0:
            target_strike = self._align_with_max_pain(target_strike, max_pain_strike, moneyness)

        best = min(filtered, key=lambda o: abs(o["strike"] - target_strike))

        if expected_profit > 0 and expected_hold_minutes > 0:
            theta = best.get("theta", 0)
            total_theta_cost = abs(theta) * expected_hold_minutes * lots * lot_size / 1440
            if total_theta_cost > expected_profit * self.theta_edge_threshold:
                return SelectionResult(allowed=False, rejection_rule="THETA_KILL")

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
            implied_vol=best.get("implied_vol", 0.0),
            theta=best.get("theta", 0.0),
        )
        return SelectionResult(allowed=True, contract=contract)

    def _get_target_strike(self, spot: float, moneyness: Moneyness, interval: int) -> float:
        if moneyness == Moneyness.ATM:
            return round(spot / interval) * interval
        if moneyness == Moneyness.OTM1:
            return round(spot / interval) * interval + interval
        if moneyness == Moneyness.OTM2:
            return round(spot / interval) * interval + 2 * interval
        if moneyness == Moneyness.ITM1:
            return round(spot / interval) * interval - interval
        if moneyness == Moneyness.ITM2:
            return round(spot / interval) * interval - 2 * interval
        return round(spot / interval) * interval

    def _align_with_max_pain(
        self,
        target_strike: float,
        max_pain_strike: float,
        moneyness: Moneyness,
    ) -> float:
        _ = moneyness
        distance = abs(target_strike - max_pain_strike)
        if distance > 100:
            return target_strike - (distance * 0.5 * (1 if target_strike > max_pain_strike else -1))
        return target_strike

    def get_filtered_contracts(
        self,
        contracts: list[OptionContract],
        spot_price: float,
        moneyness: Moneyness = Moneyness.ATM,
    ) -> list[OptionContract]:
        if not contracts:
            return []
        target = self._get_target_strike(spot_price, moneyness, 50)
        return sorted(contracts, key=lambda c: abs(c.strike - target))[:5]

