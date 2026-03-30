"""Exit Engine — deterministic POC target + theta validation exit logic.

CHANGE 7: All exit decisions are 100% deterministic, no LLM.

PRIMARY EXIT: Close FULL position when underlying reaches POC.
This is NON-NEGOTIABLE for the base model.

SECONDARY SAFETY EXITS (whichever hits first):
  a. Underlying stop level hit
  b. Option premium drops 30% from entry (IV crush protection)
  c. Max hold time exceeded: 30 min (scalp), 120 min (momentum)
  d. Phase 5 starts (15:15 IST) — close everything, no exceptions

THETA VALIDATION before entry:
  daily_theta = option chain theta per unit per day
  per_minute_theta = daily_theta / 375
  holding_cost = per_minute_theta × expected_hold_minutes × lots × lot_size
  IF holding_cost > 0.20 × expected_profit → SKIP, theta kills edge
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


class ExitAction(str, Enum):
    HOLD = "HOLD"
    CLOSE_FULL = "CLOSE_FULL"
    CLOSE_PARTIAL = "CLOSE_PARTIAL"


class ExitReason(str, Enum):
    POC_REACHED = "POC_REACHED"
    STOP_HIT = "STOP_HIT"
    PREMIUM_DROP = "PREMIUM_DROP"  # 30% premium drop
    TIME_STOP = "TIME_STOP"  # max hold time exceeded
    PHASE_5 = "PHASE_5"  # close protection phase
    THETA_KILL = "THETA_KILL"  # theta cost kills edge


@dataclass(frozen=True)
class ExitResult:
    """Result of exit engine evaluation."""

    action: ExitAction
    reason: ExitReason
    exit_price: float
    detail: str
    remaining_pct: float = 0.0  # 0 = full exit, >0 = partial


@dataclass(frozen=True)
class ThetaResult:
    """Result of theta validation."""

    allowed: bool
    holding_cost: float
    expected_profit: float
    theta_ratio: float  # holding_cost / expected_profit
    reason: str


class ExitEngine:
    """Deterministic exit engine.

    Evaluates all exit conditions and returns the first triggered action.
    No LLM involvement.
    """

    def __init__(
        self,
        max_hold_minutes_scalp: int = 30,
        max_hold_minutes_momentum: int = 120,
        premium_drop_pct: float = 0.30,  # 30% premium drop = exit
        theta_edge_threshold: float = 0.20,  # theta cost < 20% of expected profit
    ) -> None:
        self._max_hold_scalp = max_hold_minutes_scalp
        self._max_hold_momentum = max_hold_minutes_momentum
        self._premium_drop = premium_drop_pct
        self._theta_threshold = theta_edge_threshold

    def evaluate_exits(
        self,
        direction: str,
        entry_price: float,
        current_underlying: float,
        stop_price: float,
        target_price: float,
        entry_premium: float,
        current_premium: float,
        hold_minutes: float,
        is_phase_5: bool,
        setup_type: str,  # "scalp" or "momentum"
        tick_size: float,
    ) -> ExitResult:
        """Evaluate all exit conditions. First triggered wins."""
        is_long = direction == "LONG"

        # 1. Phase 5 — close everything
        if is_phase_5:
            return ExitResult(
                action=ExitAction.CLOSE_FULL,
                reason=ExitReason.PHASE_5,
                exit_price=current_underlying,
                detail="Phase 5 (close protection) — forced exit",
            )

        # 2. Stop hit
        if (is_long and current_underlying <= stop_price) or (
            not is_long and current_underlying >= stop_price
        ):
            return ExitResult(
                action=ExitAction.CLOSE_FULL,
                reason=ExitReason.STOP_HIT,
                exit_price=current_underlying,
                detail=f"Stop hit: {current_underlying:.2f} vs SL {stop_price:.2f}",
            )

        # 3. Premium 30% drop (IV crush protection)
        if entry_premium > 0:
            premium_drop = (entry_premium - current_premium) / entry_premium
            if premium_drop >= self._premium_drop:
                return ExitResult(
                    action=ExitAction.CLOSE_FULL,
                    reason=ExitReason.PREMIUM_DROP,
                    exit_price=current_underlying,
                    detail=f"Premium dropped {premium_drop:.1%} from entry",
                )

        # 4. Time stop
        max_hold = (
            self._max_hold_scalp if setup_type == "scalp" else self._max_hold_momentum
        )
        if hold_minutes >= max_hold:
            return ExitResult(
                action=ExitAction.CLOSE_FULL,
                reason=ExitReason.TIME_STOP,
                exit_price=current_underlying,
                detail=f"Time stop: {hold_minutes:.0f} min >= {max_hold} min",
            )

        # 5. POC target reached
        if (is_long and current_underlying >= target_price) or (
            not is_long and current_underlying <= target_price
        ):
            return ExitResult(
                action=ExitAction.CLOSE_FULL,
                reason=ExitReason.POC_REACHED,
                exit_price=target_price,
                detail=f"POC target reached: {current_underlying:.2f} vs TP {target_price:.2f}",
            )

        return ExitResult(
            action=ExitAction.HOLD,
            reason=ExitReason.POC_REACHED,  # placeholder
            exit_price=0,
            detail="No exit condition triggered",
        )

    def validate_theta(
        self,
        daily_theta: float,
        expected_hold_minutes: float,
        expected_profit: float,
        lots: int,
        lot_size: int,
    ) -> ThetaResult:
        """Validate theta cost before entry.

        Returns whether the trade should be taken based on theta decay.
        """
        per_minute_theta = daily_theta / 375.0
        holding_cost = per_minute_theta * expected_hold_minutes * lots * lot_size

        if expected_profit <= 0:
            return ThetaResult(
                allowed=False,
                holding_cost=holding_cost,
                expected_profit=0,
                theta_ratio=float("inf"),
                reason="No expected profit — theta validation impossible",
            )

        theta_ratio = holding_cost / expected_profit

        if theta_ratio > self._theta_threshold:
            return ThetaResult(
                allowed=False,
                holding_cost=holding_cost,
                expected_profit=expected_profit,
                theta_ratio=theta_ratio,
                reason=f"Theta kills edge: {theta_ratio:.1%} > {self._theta_threshold:.0%} threshold",
            )

        return ThetaResult(
            allowed=True,
            holding_cost=holding_cost,
            expected_profit=expected_profit,
            theta_ratio=theta_ratio,
            reason=f"Theta OK: {theta_ratio:.1%} < {self._theta_threshold:.0%} threshold",
        )
