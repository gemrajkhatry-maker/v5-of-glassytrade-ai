"""Risk Sizing Engine — deterministic Kelly-based position sizing.

CHANGE 5: Replace any LLM-based sizing with deterministic formula.

  BASE RISK: 0.30% of equity (hard clamp 0.25%-0.50%)
  DYNAMIC CUSHION: +20% of session PnL when winning
  CONSECUTIVE LOSS: reduce to 0.25% on 2+ losses
  LOT CALC: floor(max_risk / (stop_points × lot_size))
  SCALE-IN: 40% / 30% / 30% plan
  RR MINIMUM: 2.0 (ideal 2.5-4.0)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class RiskTier(str, Enum):
    STANDARD = "STANDARD"  # 0.30% base risk
    REDUCED = "REDUCED"  # 0.25% (2+ consecutive losses)
    ELEVATED = "ELEVATED"  # 0.50% (cushion available)


@dataclass(frozen=True)
class SizingResult:
    """Result of risk sizing calculation."""

    risk_pct: float
    max_risk_amount: float
    lots: int
    stop_points: float
    target_points: float
    rr_ratio: float
    risk_tier: RiskTier
    allowed: bool
    reason: str
    scale_in_1: int  # lots for first entry (40%)
    scale_in_2: int  # lots for second entry (30%)
    scale_in_3: int  # lots for third entry (30%)


class RiskSizingEngine:
    """Deterministic Kelly-based position sizing.

    No LLM involvement. Pure math. Sub-millisecond execution.
    """

    # Lot sizes per instrument
    LOT_SIZES = {
        "NIFTY": 25,
        "BANKNIFTY": 15,
        "FINNIFTY": 40,
        "CRUDEOIL": 100,
        "NATURALGAS": 1250,
        "GOLD": 1,
        "SILVER": 30,
    }

    def __init__(
        self,
        base_risk_pct: float = 0.0030,  # 0.30%
        min_risk_pct: float = 0.0025,  # 0.25%
        max_risk_pct: float = 0.0050,  # 0.50%
        cushion_multiplier: float = 0.20,  # 20% of session PnL
        consecutive_loss_threshold: int = 2,  # reduce to min on 2+ losses
        min_rr: float = 2.0,  # minimum risk:reward
    ) -> None:
        self._base_risk = base_risk_pct
        self._min_risk = min_risk_pct
        self._max_risk = max_risk_pct
        self._cushion_mult = cushion_multiplier
        self._consec_loss_thresh = consecutive_loss_threshold
        self._min_rr = min_rr

    def calculate(
        self,
        equity: float,
        session_pnl: float,
        consecutive_losses: int,
        underlying: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
        direction: str,
    ) -> SizingResult:
        """Calculate position size based on risk parameters.

        Args:
            equity: Current equity
            session_pnl: Current session PnL
            consecutive_losses: Number of consecutive losing trades
            underlying: "NIFTY", "BANKNIFTY", etc.
            entry_price: Planned entry price
            stop_price: Stop loss price
            target_price: Take profit price
            direction: "LONG" or "SHORT"
        """
        # Risk tier selection
        if consecutive_losses >= self._consec_loss_thresh:
            risk_tier = RiskTier.REDUCED
            risk_pct = self._min_risk
        elif session_pnl > 0:
            available_risk = max(
                self._base_risk, session_pnl * self._cushion_mult / equity
            )
            risk_tier = RiskTier.ELEVATED
            risk_pct = min(available_risk, self._max_risk)
        else:
            risk_tier = RiskTier.STANDARD
            risk_pct = self._base_risk

        # Hard clamp
        risk_pct = max(self._min_risk, min(self._max_risk, risk_pct))

        # Max risk amount
        max_risk_amount = equity * risk_pct

        # Stop points and target points
        if direction == "LONG":
            stop_points = entry_price - stop_price
            target_points = target_price - entry_price
        else:
            stop_points = stop_price - entry_price
            target_points = entry_price - target_price

        # RR check
        if stop_points <= 0:
            return SizingResult(
                risk_pct=risk_pct,
                max_risk_amount=max_risk_amount,
                lots=0,
                stop_points=0,
                target_points=target_points,
                rr_ratio=0,
                risk_tier=risk_tier,
                allowed=False,
                reason="Invalid stop (stop <= entry)",
                scale_in_1=0,
                scale_in_2=0,
                scale_in_3=0,
            )

        rr_ratio = target_points / stop_points if stop_points > 0 else 0
        if rr_ratio < self._min_rr:
            return SizingResult(
                risk_pct=risk_pct,
                max_risk_amount=max_risk_amount,
                lots=0,
                stop_points=stop_points,
                target_points=target_points,
                rr_ratio=rr_ratio,
                risk_tier=risk_tier,
                allowed=False,
                reason=f"R:R={rr_ratio:.1f} < {self._min_rr}",
                scale_in_1=0,
                scale_in_2=0,
                scale_in_3=0,
            )

        # Lot calculation
        lot_size = self.LOT_SIZES.get(underlying, 1)
        lots = math.floor(max_risk_amount / (stop_points * lot_size))

        if lots < 1:
            return SizingResult(
                risk_pct=risk_pct,
                max_risk_amount=max_risk_amount,
                lots=0,
                stop_points=stop_points,
                target_points=target_points,
                rr_ratio=rr_ratio,
                risk_tier=risk_tier,
                allowed=False,
                reason="Insufficient risk for 1 lot",
                scale_in_1=0,
                scale_in_2=0,
                scale_in_3=0,
            )

        # Scale-in plan: 40% / 30% / 30%
        scale_1 = max(1, math.floor(lots * 0.40))
        scale_2 = max(0, math.floor(lots * 0.30))
        scale_3 = lots - scale_1 - scale_2
        if scale_3 < 0:
            scale_3 = 0
            scale_2 = lots - scale_1

        return SizingResult(
            risk_pct=risk_pct,
            max_risk_amount=max_risk_amount,
            lots=lots,
            stop_points=stop_points,
            target_points=target_points,
            rr_ratio=rr_ratio,
            risk_tier=risk_tier,
            allowed=True,
            reason=f"Lots={lots} ({scale_1}/{scale_2}/{scale_3}), R:R={rr_ratio:.1f}, risk={risk_pct:.2%}",
            scale_in_1=scale_1,
            scale_in_2=scale_2,
            scale_in_3=scale_3,
        )
