"""Circuit Breakers — hard system locks for risk protection.

CHANGE 8: Non-overridable circuit breakers.

CONSECUTIVE LOSS RULE:
  consecutive_losses >= 3 AND session_pnl <= 0 → STOP, lock trading
  consecutive_losses >= 5 AND session_pnl > 0  → STOP, lock trading
  On any WIN → reset consecutive_losses = 0

DAILY MAX DRAWDOWN:
  max_daily_loss = equity × 0.005 (0.5% = ₹5,000 on ₹10L account per Fabio guideline)
  IF daily_pnl <= -max_daily_loss → CIRCUIT BREAKER
  Close all open positions immediately. No new trades for the day.

PROFIT TARGET LOCK:
  IF session_pnl >= configured daily profit target → STOP trading

ACCOUNT LOSS ABSOLUTE (Fabio's AMT Strategy):
  Hard cap of ₹30,000 cumulative loss across all sessions/symbols.
  IF cumulative_account_pnl <= -₹30,000 → CIRCUIT BREAKER
  This is NON-OVERRIDABLE and takes highest priority.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from quant.contracts.constants import ACCOUNT_MAX_LOSS_ABSOLUTE

logger = logging.getLogger(__name__)


class BreakerReason(str, Enum):
    NONE = "NONE"
    CONSECUTIVE_LOSS = "CONSECUTIVE_LOSS"
    DAILY_DRAWDOWN = "DAILY_DRAWDOWN"
    PROFIT_TARGET = "PROFIT_TARGET"
    ACCOUNT_LOSS_ABSOLUTE = "ACCOUNT_LOSS_ABSOLUTE"


@dataclass(frozen=True)
class BreakerResult:
    """Result of circuit breaker evaluation."""

    is_locked: bool
    reason: BreakerReason
    detail: str


class CircuitBreakers:
    """Hard circuit breakers for risk protection.

    These are NON-OVERRIDABLE. Once triggered, trading stops immediately.
    """

    def __init__(
        self,
        equity: float = 1000000.0,
        max_consecutive_losses: int = 3,
        max_consecutive_losses_winning: int = 5,
        max_daily_dd_pct: float = 0.005,  # 0.5% of equity (Fabio guideline)
        daily_profit_target: float | None = None,
        account_max_loss: float | None = None,  # ₹30,000 hard cap (defaults to constant)
    ) -> None:
        self._equity = equity
        self._max_consec_loss = max_consecutive_losses
        self._max_consec_loss_winning = max_consecutive_losses_winning
        self._max_daily_dd = equity * max_daily_dd_pct
        self._profit_target = daily_profit_target
        # Non-overridable account loss cap (defaults to constant if not specified)
        self._account_max_loss = (
            account_max_loss if account_max_loss is not None else ACCOUNT_MAX_LOSS_ABSOLUTE
        )

    def evaluate(
        self,
        consecutive_losses: int,
        session_pnl: float,
        cumulative_account_pnl: float = 0.0,
    ) -> BreakerResult:
        """Evaluate all circuit breakers. Any triggered = locked.

        Args:
            consecutive_losses: Current consecutive loss count
            session_pnl: Session-level P&L (resets daily)
            cumulative_account_pnl: Cumulative account P&L across all sessions/symbols

        Returns:
            BreakerResult with locked status and reason
        """

        # HIGHEST PRIORITY: Account-level absolute loss cap
        # This check is NON-OVERRIDABLE and must be first
        if cumulative_account_pnl <= -self._account_max_loss:
            logger.critical(
                "ACCOUNT LOSS LIMIT BREACHED: ₹%.0f hard cap reached (cumulative P&L: ₹%.0f)",
                self._account_max_loss,
                cumulative_account_pnl,
            )
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.ACCOUNT_LOSS_ABSOLUTE,
                detail=f"ACCOUNT LOSS LIMIT BREACHED: ₹{self._account_max_loss:.0f} hard cap reached "
                f"(cumulative P&L: ₹{cumulative_account_pnl:.0f})",
            )

        # Profit target lock
        if self._profit_target is not None and session_pnl >= self._profit_target:
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.PROFIT_TARGET,
                detail=f"Daily profit target reached: {session_pnl:.0f} >= {self._profit_target:.0f}",
            )

        # Consecutive loss breaker
        if session_pnl <= 0 and consecutive_losses >= self._max_consec_loss:
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.CONSECUTIVE_LOSS,
                detail=f"{consecutive_losses} consecutive losses with negative PnL — CIRCUIT BREAKER",
            )
        elif session_pnl > 0 and consecutive_losses >= self._max_consec_loss_winning:
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.CONSECUTIVE_LOSS,
                detail=f"{consecutive_losses} consecutive losses with positive PnL — CIRCUIT BREAKER",
            )

        # Daily drawdown breaker
        if session_pnl <= -self._max_daily_dd:
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.DAILY_DRAWDOWN,
                detail=f"Daily DD {abs(session_pnl):.0f} >= {self._max_daily_dd:.0f} — CIRCUIT BREAKER",
            )

        return BreakerResult(
            is_locked=False,
            reason=BreakerReason.NONE,
            detail="All circuit breakers OK",
        )

    def reset_loss_counter(self) -> None:
        """Call after a WIN to reset consecutive loss counter."""
        pass  # Caller manages the counter
