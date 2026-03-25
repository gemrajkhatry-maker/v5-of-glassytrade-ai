"""Risk Tier Engine — Fabio's A/B/C dynamic risk model.

Feature-flagged replacement for SessionRiskManager when risk_tier_engine=true.

Tier Definitions:
  HALT: 0% risk — 3 consecutive losses
  C:    0.15% of capital — session start (always)
  B:    0.25% of capital — daily P&L ≥ +1R
  A:    0.45% of capital — daily P&L ≥ +3R AND premium setup

Tier A Premium Setup Requirements (ALL must be true):
  aggression_score >= 3.5
  lvn_strength >= 0.85
  cvd_divergence = true
  drive = D2 (not first drive)
  ml_probability >= 0.65

State Machine:
  SESSION START: tier=C, daily_pnl_r=0, consecutive_losses=0
  ON TRADE CLOSED: update daily_pnl_r, consecutive_losses
  DAILY RESET: called at session close → tier=C, daily_pnl_r=0, consecutive_losses=0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RiskTier(str, Enum):
    HALT = "HALT"
    C = "C"
    B = "B"
    A = "A"


# Risk percentage per tier (fraction of capital)
TIER_RISK_PCT: dict[RiskTier, float] = {
    RiskTier.HALT: 0.0,
    RiskTier.C: 0.0015,  # 0.15%
    RiskTier.B: 0.0025,  # 0.25%
    RiskTier.A: 0.0045,  # 0.45%
}

# Tier unlock thresholds in R-multiples
TIER_B_UNLOCK_R = 1.0  # daily_pnl_r >= 1.0
TIER_A_UNLOCK_R = 3.0  # daily_pnl_r >= 3.0

# Tier downgrade thresholds
TIER_B_DOWNGRADE_R = 1.0  # daily_pnl_r < 1.0 → drop to C
TIER_A_DOWNGRADE_R = 2.0  # daily_pnl_r < 2.0 → drop to B

# HALT threshold
HALT_CONSECUTIVE_LOSSES = 3


@dataclass(frozen=True)
class TierAPremiumCheck:
    """All must be true for Tier A unlock."""

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
            and self.ml_probability >= 0.65
        )


@dataclass(frozen=True)
class TierState:
    """Immutable snapshot of risk tier state."""

    tier: RiskTier
    risk_pct: float
    daily_pnl_r: float
    consecutive_losses: int
    trade_count: int
    is_halted: bool
    halt_reason: str = ""


class RiskTierEngine:
    """Dynamic risk tier engine — Fabio's A/B/C model.

    Manages risk tiers based on daily PnL in R-multiples and consecutive losses.
    Feature-flagged via risk_tier_engine flag.
    """

    def __init__(
        self,
        capital: float = 5000000.0,
        max_consecutive_losses: int = HALT_CONSECUTIVE_LOSSES,
    ) -> None:
        self._capital = capital
        self._max_consecutive_losses = max_consecutive_losses

        # State
        self._tier: RiskTier = RiskTier.C
        self._daily_pnl_r: float = 0.0
        self._consecutive_losses: int = 0
        self._trade_count: int = 0
        self._halted: bool = False
        self._halt_reason: str = ""

    @property
    def tier(self) -> RiskTier:
        return RiskTier.HALT if self._halted else self._tier

    @property
    def risk_pct(self) -> float:
        """Risk percentage for current tier."""
        return TIER_RISK_PCT[self.tier]

    @property
    def risk_amount(self) -> float:
        """Risk amount in INR for current tier."""
        return self._capital * self.risk_pct

    @property
    def daily_pnl_r(self) -> float:
        return self._daily_pnl_r

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    def get_state(self) -> TierState:
        """Get immutable state snapshot."""
        return TierState(
            tier=self.tier,
            risk_pct=self.risk_pct,
            daily_pnl_r=self._daily_pnl_r,
            consecutive_losses=self._consecutive_losses,
            trade_count=self._trade_count,
            is_halted=self._halted,
            halt_reason=self._halt_reason,
        )

    def record_trade(
        self, pnl_r: float, premium_check: TierAPremiumCheck | None = None
    ) -> TierState:
        """Record a trade result and update tier.

        Args:
            pnl_r: Trade result in R-multiples (positive = win, negative = loss)
            premium_check: Optional premium setup check for Tier A unlock

        Returns:
            Updated TierState
        """
        self._trade_count += 1
        self._daily_pnl_r += pnl_r

        # Update consecutive losses
        if pnl_r < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # Check HALT
        if self._consecutive_losses >= self._max_consecutive_losses:
            self._halted = True
            self._halt_reason = (
                f"3-loss circuit breaker: {self._consecutive_losses} consecutive losses"
            )
            logger.critical(
                "RISK TIER: HALT — %d consecutive losses (daily_pnl=%.2fR)",
                self._consecutive_losses,
                self._daily_pnl_r,
            )
            return self.get_state()

        # Tier transition logic
        if self._daily_pnl_r >= TIER_A_UNLOCK_R:
            # Check premium setup requirements for Tier A
            if premium_check and premium_check.is_premium:
                if self._tier != RiskTier.A:
                    logger.info(
                        "RISK TIER: %s → A (daily_pnl=%.2fR, premium setup confirmed)",
                        self._tier.value,
                        self._daily_pnl_r,
                    )
                self._tier = RiskTier.A
            else:
                # Not premium — stay at B
                if self._tier != RiskTier.B:
                    logger.info(
                        "RISK TIER: %s → B (daily_pnl=%.2fR, premium not met)",
                        self._tier.value,
                        self._daily_pnl_r,
                    )
                self._tier = RiskTier.B
        elif self._daily_pnl_r >= TIER_B_UNLOCK_R:
            if self._tier != RiskTier.B:
                logger.info(
                    "RISK TIER: %s → B (daily_pnl=%.2fR)",
                    self._tier.value,
                    self._daily_pnl_r,
                )
            self._tier = RiskTier.B
        else:
            # Check if we need to downgrade from A or B
            if self._tier == RiskTier.A and self._daily_pnl_r < TIER_A_DOWNGRADE_R:
                logger.info(
                    "RISK TIER: A → B (daily_pnl=%.2fR < %.1fR threshold)",
                    self._daily_pnl_r,
                    TIER_A_DOWNGRADE_R,
                )
                self._tier = RiskTier.B
            elif self._tier == RiskTier.B and self._daily_pnl_r < TIER_B_DOWNGRADE_R:
                logger.info(
                    "RISK TIER: B → C (daily_pnl=%.2fR < %.1fR threshold)",
                    self._daily_pnl_r,
                    TIER_B_DOWNGRADE_R,
                )
                self._tier = RiskTier.C
            # else: stay at current tier

        return self.get_state()

    def daily_reset(self) -> None:
        """Reset at session close. Called at 15:15 NSE / 23:15 MCX."""
        prev_tier = self._tier
        self._tier = RiskTier.C
        self._daily_pnl_r = 0.0
        self._consecutive_losses = 0
        self._halted = False
        self._halt_reason = ""
        logger.info(
            "RISK TIER: daily reset — %s → C (pnl=%.2fR → 0)",
            prev_tier.value,
            self._daily_pnl_r,
        )

    def can_trade(self) -> bool:
        """Check if new trade is allowed."""
        if self._halted:
            return False
        if self._consecutive_losses >= self._max_consecutive_losses:
            self._halted = True
            self._halt_reason = (
                f"3-loss circuit breaker: {self._consecutive_losses} consecutive losses"
            )
            return False
        return self.tier != RiskTier.HALT

    def to_dict(self) -> dict:
        """Serialize for crash-safe persistence."""
        return {
            "tier": self._tier.value,
            "daily_pnl_r": self._daily_pnl_r,
            "consecutive_losses": self._consecutive_losses,
            "trade_count": self._trade_count,
            "halted": self._halted,
        }

    def load_from_dict(self, data: dict) -> None:
        """Restore from persisted dict."""
        self._tier = RiskTier(data.get("tier", "C"))
        self._daily_pnl_r = data.get("daily_pnl_r", 0.0)
        self._consecutive_losses = data.get("consecutive_losses", 0)
        self._trade_count = data.get("trade_count", 0)
        self._halted = data.get("halted", False)
