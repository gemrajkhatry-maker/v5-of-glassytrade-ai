"""Hard non-overridable circuit breakers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class BreakerReason(str, Enum):
    NONE = "NONE"
    CONSECUTIVE_LOSS = "CONSECUTIVE_LOSS"
    DAILY_DRAWDOWN = "DAILY_DRAWDOWN"
    PROFIT_TARGET = "PROFIT_TARGET"
    ACCOUNT_LOSS_ABSOLUTE = "ACCOUNT_LOSS_ABSOLUTE"


@dataclass(frozen=True)
class BreakerResult:
    is_locked: bool
    reason: BreakerReason
    detail: str


class CircuitBreakers:
    """Hard circuit breakers for trading operation and risk."""

    def __init__(
        self,
        equity: float = 1_000_000.0,
        max_consecutive_losses: int = 3,
        max_consecutive_losses_winning: int = 5,
        max_daily_dd_pct: float = 0.005,
        daily_profit_target: float | None = None,
        account_max_loss: float = 30_000.0,
    ) -> None:
        self._equity = equity
        self._max_consec_loss = max_consecutive_losses
        self._max_consec_loss_winning = max_consecutive_losses_winning
        self._max_daily_dd = equity * max_daily_dd_pct
        self._profit_target = daily_profit_target
        self._account_max_loss = account_max_loss

    def evaluate(
        self,
        consecutive_losses: int,
        session_pnl: float,
        cumulative_account_pnl: float = 0.0,
    ) -> BreakerResult:
        if cumulative_account_pnl <= -abs(self._account_max_loss):
            logger.critical(
                "ACCOUNT loss hard cap breached: cumulative %.0f >= %0.f",
                cumulative_account_pnl,
                self._account_max_loss,
            )
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.ACCOUNT_LOSS_ABSOLUTE,
                detail=(
                    f"Hard account loss cap reached (₹{self._account_max_loss:,.0f}) "
                    f"with cumulative pnl {cumulative_account_pnl:,.0f}"
                ),
            )

        if self._profit_target is not None and session_pnl >= self._profit_target:
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.PROFIT_TARGET,
                detail=f"Profit target reached: {session_pnl:.0f} >= {self._profit_target:.0f}",
            )

        if session_pnl <= 0 and consecutive_losses >= self._max_consec_loss:
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.CONSECUTIVE_LOSS,
                detail=f"{consecutive_losses} consecutive losses with flat/negative pnl.",
            )
        if session_pnl > 0 and consecutive_losses >= self._max_consec_loss_winning:
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.CONSECUTIVE_LOSS,
                detail=f"{consecutive_losses} consecutive losses with positive pnl.",
            )

        if session_pnl <= -self._max_daily_dd:
            return BreakerResult(
                is_locked=True,
                reason=BreakerReason.DAILY_DRAWDOWN,
                detail=f"Daily drawdown {abs(session_pnl):.0f} >= {self._max_daily_dd:.0f}.",
            )

        return BreakerResult(
            is_locked=False,
            reason=BreakerReason.NONE,
            detail="All circuit breakers pass",
        )

    def reset_loss_counter(self) -> None:
        """Compatibility no-op for legacy callers that expect this hook."""
        return None

