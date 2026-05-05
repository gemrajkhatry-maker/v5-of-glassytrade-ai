"""Risk tier engine — dynamic A/B/C ladder for AMT trade sizing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SessionRiskTier(str, Enum):
    HALT = "HALT"
    C = "C"
    B = "B"
    A = "A"


TIER_RISK_PCT = {
    SessionRiskTier.HALT: 0.0,
    SessionRiskTier.C: 0.0015,
    SessionRiskTier.B: 0.0025,
    SessionRiskTier.A: 0.0045,
}

TIER_B_UNLOCK_R = 1.0
TIER_A_UNLOCK_R = 3.0
TIER_A_DOWNGRADE_R = 2.0
TIER_B_DOWNGRADE_R = 1.0
HALT_CONSECUTIVE_LOSSES = 3
CONFIDENCE_HIGH_THRESHOLD = 0.65


@dataclass(frozen=True)
class TierAPremiumCheck:
    aggression_score: float = 0.0
    lvn_strength: float = 0.0
    cvd_divergence: bool = False
    is_second_drive: bool = False
    ml_probability: float = 0.0

    @property
    def is_premium(self) -> bool:
        return (
            self.aggression_score >= 3.5
            and self.lvn_strength >= 0.85
            and self.cvd_divergence
            and self.is_second_drive
            and self.ml_probability >= CONFIDENCE_HIGH_THRESHOLD
        )


@dataclass(frozen=True)
class TierState:
    tier: SessionRiskTier
    risk_pct: float
    daily_pnl_r: float
    consecutive_losses: int
    trade_count: int
    is_halted: bool
    halt_reason: str = ""


class RiskTierEngine:
    """Dynamic risk tier state machine."""

    def __init__(self, capital: float = 5_000_000.0, max_consecutive_losses: int = HALT_CONSECUTIVE_LOSSES):
        self._capital = float(capital)
        self._max_consecutive_losses = max_consecutive_losses
        self._tier: SessionRiskTier = SessionRiskTier.C
        self._daily_pnl_r = 0.0
        self._consecutive_losses = 0
        self._trade_count = 0
        self._halted = False
        self._halt_reason = ""

    @property
    def tier(self) -> SessionRiskTier:
        return SessionRiskTier.HALT if self._halted else self._tier

    @property
    def risk_pct(self) -> float:
        return TIER_RISK_PCT[self.tier]

    @property
    def risk_amount(self) -> float:
        return self._capital * self.risk_pct

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    @property
    def daily_pnl_r(self) -> float:
        return self._daily_pnl_r

    def get_state(self) -> TierState:
        return TierState(
            tier=self.tier,
            risk_pct=self.risk_pct,
            daily_pnl_r=self._daily_pnl_r,
            consecutive_losses=self._consecutive_losses,
            trade_count=self._trade_count,
            is_halted=self._halted,
            halt_reason=self._halt_reason,
        )

    def record_trade(self, pnl_r: float, premium_check: TierAPremiumCheck | None = None) -> TierState:
        self._trade_count += 1
        self._daily_pnl_r += float(pnl_r)

        if pnl_r < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        if self._consecutive_losses >= self._max_consecutive_losses:
            self._halted = True
            self._halt_reason = f"3-loss circuit breaker: {self._consecutive_losses} consecutive losses"
            logger.critical("Risk tier HALT: %s", self._halt_reason)
            return self.get_state()

        if self._daily_pnl_r >= TIER_A_UNLOCK_R and premium_check and premium_check.is_premium:
            if self._tier != SessionRiskTier.A:
                self._tier = SessionRiskTier.A
                logger.info("Risk tier -> A (pnl=%.2fR, premium criteria met)", self._daily_pnl_r)
        elif self._daily_pnl_r >= TIER_B_UNLOCK_R:
            if self._tier != SessionRiskTier.B:
                logger.info("Risk tier -> B (pnl=%.2fR)", self._daily_pnl_r)
            self._tier = SessionRiskTier.B
        elif self._tier == SessionRiskTier.A and self._daily_pnl_r < TIER_A_DOWNGRADE_R:
            logger.info("Risk tier A -> B (pnl=%.2fR)", self._daily_pnl_r)
            self._tier = SessionRiskTier.B
        elif self._tier == SessionRiskTier.B and self._daily_pnl_r < TIER_B_DOWNGRADE_R:
            logger.info("Risk tier B -> C (pnl=%.2fR)", self._daily_pnl_r)
            self._tier = SessionRiskTier.C

        return self.get_state()

    def can_trade(self) -> bool:
        if self._halted:
            return False
        if self._consecutive_losses >= self._max_consecutive_losses:
            self._halted = True
            self._halt_reason = (
                f"3-loss circuit breaker: {self._consecutive_losses} consecutive losses"
            )
            return False
        return self.tier != SessionRiskTier.HALT

    def daily_reset(self) -> None:
        self._tier = SessionRiskTier.C
        self._daily_pnl_r = 0.0
        self._consecutive_losses = 0
        self._halted = False
        self._halt_reason = ""

    def to_dict(self) -> dict:
        return {
            "tier": self._tier.value,
            "daily_pnl_r": self._daily_pnl_r,
            "consecutive_losses": self._consecutive_losses,
            "trade_count": self._trade_count,
            "halted": self._halted,
        }

    def load_from_dict(self, data: dict) -> None:
        self._tier = SessionRiskTier(data.get("tier", "C"))
        self._daily_pnl_r = float(data.get("daily_pnl_r", 0.0))
        self._consecutive_losses = int(data.get("consecutive_losses", 0))
        self._trade_count = int(data.get("trade_count", 0))
        self._halted = bool(data.get("halted", False))
        self._halt_reason = ""
