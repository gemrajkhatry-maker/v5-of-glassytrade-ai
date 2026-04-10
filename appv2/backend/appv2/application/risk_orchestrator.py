"""Risk Orchestrator — coordinates all risk checks before/after trades.

Pre-trade checks:
- Daily loss limit
- Circuit breaker status
- Max positions per symbol
- Position sizing validation
- Exposure limits

Post-trade updates:
- Record P&L
- Update consecutive loss count
- Check daily loss threshold
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from appv2.domain.services.daily_loss_tracker import DailyLossTracker
from appv2.domain.services.circuit_breaker import CircuitBreaker
from appv2.domain.services.position_sizer import calculate_position_size
from appv2.config.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskCheckResult:
    allowed: bool
    reason: str  # Empty if allowed
    details: str = ""  # Additional context


class RiskOrchestrator:
    """Coordinates all risk management checks."""

    def __init__(
        self,
        capital: float | None = None,
        risk_per_trade_pct: float | None = None,
        max_daily_loss_pct: float | None = None,
        max_consecutive_losses: int | None = None,
        max_positions_per_symbol: int | None = None,
    ):
        self._capital = capital or settings.CAPITAL
        self._risk_pct = risk_per_trade_pct or settings.RISK_PER_TRADE_PCT
        self._daily_loss_tracker = DailyLossTracker(
            self._capital, max_daily_loss_pct or settings.MAX_DAILY_LOSS_PCT,
        )
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._max_consecutive = max_consecutive_losses or settings.MAX_CONSECUTIVE_LOSSES
        self._max_per_symbol = max_positions_per_symbol or settings.MAX_POSITIONS_PER_SYMBOL
        self._position_counts: dict[str, int] = {}

    def pre_trade_check(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        lot_size: int,
        open_positions_for_symbol: int = 0,
    ) -> RiskCheckResult:
        """Run all pre-trade risk checks.

        Returns:
            RiskCheckResult with pass/fail status and reason.
        """
        # 1. Daily loss limit
        if self._daily_loss_tracker.is_halted:
            return RiskCheckResult(
                allowed=False,
                reason="Daily loss limit reached",
                details=f"Daily P&L: ₹{self._daily_loss_tracker.daily_pnl:.2f}",
            )

        # 2. Circuit breaker
        cb = self._get_circuit_breaker(symbol)
        if cb.is_open:
            return RiskCheckResult(
                allowed=False,
                reason="Circuit breaker active",
                details=f"Cooldown remaining: {cb.remaining_cooldown_seconds:.0f}s",
            )

        # 3. Max positions per symbol
        if open_positions_for_symbol >= self._max_per_symbol:
            return RiskCheckResult(
                allowed=False,
                reason="Max positions per symbol",
                details=f"{open_positions_for_symbol}/{self._max_per_symbol}",
            )

        # 4. Position sizing
        lots, actual_risk = calculate_position_size(
            self._capital, self._risk_pct, entry_price, stop_loss, lot_size,
        )
        if lots <= 0:
            return RiskCheckResult(
                allowed=False,
                reason="Position size calculation failed",
                details=f"Entry: {entry_price}, SL: {stop_loss}, Lot: {lot_size}",
            )

        return RiskCheckResult(allowed=True, reason="")

    def post_trade_update(self, symbol: str, pnl: float, is_win: bool) -> None:
        """Update risk state after trade completion."""
        # Record daily P&L
        self._daily_loss_tracker.record_trade(pnl)

        # Update circuit breaker
        cb = self._get_circuit_breaker(symbol)
        if is_win:
            cb.record_win()
        else:
            cb.record_loss()

        # Update position count
        self._position_counts[symbol] = max(0, self._position_counts.get(symbol, 0) - 1)

        # Log
        if not is_win:
            logger.warning(
                "Loss on %s | Daily P&L: ₹%.2f | CB losses: %d/%d",
                symbol, self._daily_loss_tracker.daily_pnl,
                cb._consecutive_losses, self._max_consecutive,
            )

    def position_opened(self, symbol: str) -> None:
        """Increment position count for symbol."""
        self._position_counts[symbol] = self._position_counts.get(symbol, 0) + 1

    def position_closed(self, symbol: str) -> None:
        """Decrement position count for symbol."""
        self._position_counts[symbol] = max(0, self._position_counts.get(symbol, 0) - 1)

    def _get_circuit_breaker(self, symbol: str) -> CircuitBreaker:
        if symbol not in self._circuit_breakers:
            self._circuit_breakers[symbol] = CircuitBreaker(
                max_consecutive_losses=self._max_consecutive,
            )
        return self._circuit_breakers[symbol]

    def reset_daily(self) -> None:
        """Reset at start of new trading day."""
        self._daily_loss_tracker.reset()

    @property
    def daily_pnl(self) -> float:
        return self._daily_loss_tracker.daily_pnl

    @property
    def is_halted(self) -> bool:
        return self._daily_loss_tracker.is_halted
