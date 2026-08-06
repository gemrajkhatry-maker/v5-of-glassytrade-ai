"""Session Risk Coordinator — Manages session-level risk.

Responsibilities:
- Session risk manager integration
- Risk state tracking
- Risk-based decisions
- System risk aggregation
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from app.core.async_boundary import ensure_sync_adapter_result

from quant.execution.risk_manager import RiskManager
from quant.execution.kill_switch import KillSwitch
from quant.execution.session_risk_manager import SessionRiskManager
from quant.execution.risk_tier import RiskTierEngine, TierAPremiumCheck
from quant.execution.circuit_breakers import CircuitBreakers, BreakerReason, BreakerResult
from quant.contracts.constants import ACCOUNT_MAX_LOSS_ABSOLUTE
from quant.contracts.constants import MIN_GRADE_SCORE_THRESHOLD

if TYPE_CHECKING:
    from quant.contracts.entities import Signal
    from quant.contracts.aggregates import Portfolio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemRiskState:
    """Aggregated system-wide risk and halt state for control-plane endpoints."""

    halted: bool
    halt_reason: str
    daily_drawdown_pct: float
    consecutive_losses: int
    peak_equity: float
    current_equity: float
    cumulative_account_pnl: float  # Added for account-level loss tracking
    drift_alert: bool
    drift_message: str


class SessionRiskCoordinator:
    """Coordinates session-level risk management.

    This module encapsulates all session-level risk management logic,
    providing a single source of truth for risk decisions across the codebase.
    """

    def __init__(
        self,
        storage=None,
        capital: float = 5000000.0,
        use_risk_tier_engine: bool = False,
        trade_manager=None,
        min_grade_score: int | None = None,
        kill_switch: KillSwitch | None = None,
    ):
        self._risk_managers: dict[str, RiskManager] = {}
        self._session_risk_managers: dict[str, SessionRiskManager] = {}
        self._risk_tier_engines: dict[str, RiskTierEngine] = {}
        self._use_risk_tier_engine = use_risk_tier_engine
        self._capital = capital
        self._session_creation_lock = threading.Lock()
        self._storage = storage
        self._trade_manager = trade_manager
        self._kill_switch = kill_switch or KillSwitch()
        self._min_grade_score = (
            min_grade_score if min_grade_score is not None else MIN_GRADE_SCORE_THRESHOLD
        )
        # Circuit breakers for account-level risk limits
        self._circuit_breakers = CircuitBreakers(equity=capital)

    def _get_risk_manager(self, symbol: str) -> RiskManager:
        """Return per-symbol RiskManager, creating one if needed.

        Args:
            symbol: Trading symbol

        Returns:
            RiskManager for the symbol
        """
        with self._session_creation_lock:
            if symbol not in self._risk_managers:
                self._risk_managers[symbol] = RiskManager(kill_switch=self._kill_switch)
            return self._risk_managers[symbol]

    def get_session_risk_manager(self, symbol: str) -> SessionRiskManager:
        """Get or create SessionRiskManager for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            SessionRiskManager for the symbol
        """
        with self._session_creation_lock:
            if symbol not in self._session_risk_managers:
                srm = SessionRiskManager()
                # Try to restore from storage
                if self._storage and hasattr(self._storage, "kv_get"):
                    try:
                        saved = ensure_sync_adapter_result(
                            "storage.kv_get",
                            self._storage.kv_get,
                            f"risk_state_{symbol}_{date.today().isoformat()}",
                        )
                        if saved:
                            srm.load_from_dict(json.loads(saved))
                            logger.info(
                                "Restored risk state for %s: tier=%s, pnl=%.2f",
                                symbol,
                                srm.risk_tier.name,
                                srm.session_pnl,
                            )
                    except json.JSONDecodeError:
                        logger.debug(
                            "Could not load risk state for %s", symbol, exc_info=True
                        )
                self._session_risk_managers[symbol] = srm

                # Create RiskTierEngine if feature flag enabled
                if self._use_risk_tier_engine:
                    engine = RiskTierEngine(capital=self._capital)
                    # Restore engine state if available
                    if self._storage and hasattr(self._storage, "kv_get"):
                        try:
                            saved = ensure_sync_adapter_result(
                                "storage.kv_get",
                                self._storage.kv_get,
                                f"rte_state_{symbol}_{date.today().isoformat()}",
                            )
                            if saved:
                                engine.load_from_dict(json.loads(saved))
                                logger.info(
                                    "Restored RiskTierEngine for %s: tier=%s",
                                    symbol,
                                    engine.tier.value,
                                )
                        except json.JSONDecodeError:
                            logger.debug("Failed to restore RiskTierEngine state for %s", symbol, exc_info=True)
                    self._risk_tier_engines[symbol] = engine
                    logger.info(
                        "RiskTierEngine enabled for %s (capital=%.0f)",
                        symbol,
                        self._capital,
                    )

            return self._session_risk_managers[symbol]

    def get_risk_tier_engine(self, symbol: str) -> RiskTierEngine | None:
        """Get RiskTierEngine for a symbol (if feature flag enabled)."""
        return self._risk_tier_engines.get(symbol)

    def record_trade_with_engine(
        self,
        symbol: str,
        pnl_r: float,
        premium_check: TierAPremiumCheck | None = None,
    ) -> None:
        """Record a trade in the RiskTierEngine (if enabled) and SRM (always)."""
        srm = self.get_session_risk_manager(symbol)
        srm.record_trade(pnl_r)  # Always record in SRM

        engine = self._risk_tier_engines.get(symbol)
        if engine:
            engine.record_trade(pnl_r, premium_check)

    def _get_cumulative_account_pnl(self) -> float:
        """Compute cumulative account P&L across all sessions/symbols.

        Returns:
            Cumulative P&L (negative = loss, positive = profit)
        """
        with self._session_creation_lock:
            managers = list(self._risk_managers.values())

        if not managers:
            return 0.0

        # Cumulative P&L is the sum of realized P&L across all symbols
        return sum(rm.daily_state.realized_pnl for rm in managers)

    def check_account_loss_limit(self) -> BreakerResult:
        """Check if account-level absolute loss limit has been breached.

        This is the HIGHEST PRIORITY circuit breaker - checked before all others.

        Returns:
            BreakerResult with locked status and reason
        """
        cumulative_pnl = self._get_cumulative_account_pnl()
        return self._circuit_breakers.evaluate(
            consecutive_losses=0,  # Not relevant for account-level check
            session_pnl=0.0,  # Not relevant for account-level check
            cumulative_account_pnl=cumulative_pnl,
        )

    def validate_entry(self, symbol: str, signal: Signal, portfolio: Portfolio) -> bool:
        """Validate entry against risk limits.

        Checks five independent guards (in priority order):
        0. Account-level absolute loss limit (₹30,000 hard cap) — HIGHEST PRIORITY
        1. Signal confluence grade score (must meet minimum threshold)
        2. SessionRiskManager — 3-loss circuit breaker
        3. TradeManager — daily loss limit per symbol / global
        4. RiskManager — position sizing, exposure, drawdown

        Returns:
            True if entry is valid
        """
        # Guard 0: Account-level absolute loss limit (HIGHEST PRIORITY)
        account_breaker = self.check_account_loss_limit()
        if account_breaker.is_locked:
            logger.warning(
                "Entry BLOCKED — Account loss limit: %s", account_breaker.detail
            )
            return False

        # Guard 1: Confluence grade score floor
        meta = getattr(signal, "metadata", None) or {}
        grade_score = meta.get("grade_score")
        if grade_score is not None and grade_score < self._min_grade_score:
            logger.warning(
                "Entry BLOCKED — insufficient confluence: grade_score=%d "
                "(minimum=%d) for %s",
                grade_score,
                self._min_grade_score,
                symbol,
            )
            return False

        # Guard 2: Session circuit breaker (3 consecutive losses)
        srm = self.get_session_risk_manager(symbol)
        if not srm.can_trade:
            logger.warning(
                "Entry BLOCKED — SRM circuit breaker: %s", srm.halt_reason
            )
            return False

        # Guard 3: Daily loss limit (per-symbol or global)
        if self._trade_manager and self._trade_manager.is_daily_limit_reached(symbol):
            logger.warning(
                "Entry BLOCKED — TradeManager daily loss limit reached for %s", symbol
            )
            return False

        # Guard 4: Standard risk manager (position sizing, exposure)
        risk_manager = self._get_risk_manager(symbol)
        return risk_manager.validate(signal, portfolio)

    def record_trade_result(
        self, symbol: str, pnl: float, portfolio: Portfolio
    ) -> None:
        """Record a trade result for risk tracking.

        Args:
            symbol: Trading symbol
            pnl: Profit/loss amount
            portfolio: Portfolio
        """
        risk_manager = self._get_risk_manager(symbol)
        risk_manager.record_trade_result(pnl, portfolio)

    def is_halted(self, symbol: str) -> bool:
        """Check if trading is halted for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            True if trading is halted
        """
        risk_manager = self._get_risk_manager(symbol)
        if risk_manager.is_halted:
            return True

        # Also check RiskTierEngine if active
        engine = self._risk_tier_engines.get(symbol)
        if engine and engine.is_halted:
            return True

        return False

    def halt_trading(self) -> None:
        """Activate the global emergency kill switch."""
        self._kill_switch.halt()

    def resume_trading(self) -> None:
        """Clear the global emergency kill switch."""
        self._kill_switch.resume()

    def get_system_risk_state(self) -> SystemRiskState:
        """Return an aggregated system-wide view of runtime risk state.

        Returns:
            SystemRiskState with aggregated risk information
        """
        with self._session_creation_lock:
            managers = list(self._risk_managers.values())

        if not managers:
            return SystemRiskState(
                halted=self._kill_switch.is_halted,
                halt_reason="Emergency kill switch active"
                if self._kill_switch.is_halted
                else "",
                daily_drawdown_pct=0.0,
                consecutive_losses=0,
                peak_equity=0.0,
                current_equity=0.0,
                cumulative_account_pnl=0.0,
                drift_alert=False,
                drift_message="",
            )

        peak_equity = max((rm.daily_state.peak_equity for rm in managers), default=0.0)
        current_equity = sum(rm.daily_state.current_equity for rm in managers)
        consecutive_losses = max(
            (rm.daily_state.consecutive_losses for rm in managers), default=0
        )
        drift_alert = any(getattr(rm, "_drift_alert", False) for rm in managers)
        drift_messages = [
            getattr(rm, "_drift_message", "")
            for rm in managers
            if getattr(rm, "_drift_message", "")
        ]
        halted_manager = next((rm for rm in managers if rm.is_halted), None)

        if self._kill_switch.is_halted:
            halted = True
            halt_reason = "Emergency kill switch active"
        elif halted_manager is not None:
            halted = True
            halt_reason = halted_manager.halt_reason
        else:
            halted = False
            halt_reason = ""

        if peak_equity > 0 and math.isfinite(current_equity):
            daily_drawdown_pct = max(0.0, (peak_equity - current_equity) / peak_equity)
        else:
            daily_drawdown_pct = 0.0

        # Compute cumulative account P&L by summing realized P&L
        cumulative_account_pnl = sum(rm.daily_state.realized_pnl for rm in managers)

        return SystemRiskState(
            halted=halted,
            halt_reason=halt_reason,
            daily_drawdown_pct=daily_drawdown_pct,
            consecutive_losses=consecutive_losses,
            peak_equity=peak_equity,
            current_equity=current_equity,
            cumulative_account_pnl=cumulative_account_pnl,
            drift_alert=drift_alert,
            drift_message=" | ".join(drift_messages[:3]),
        )

    def persist_risk_state(self, symbol: str) -> None:
        """Persist risk state to storage.

        Args:
            symbol: Trading symbol
        """
        if not self._storage or not hasattr(self._storage, "kv_set"):
            return

        try:
            srm = self._session_risk_managers.get(symbol)
            if srm:
                ensure_sync_adapter_result(
                    "storage.kv_set",
                    self._storage.kv_set,
                    f"risk_state_{symbol}_{date.today().isoformat()}",
                    json.dumps(srm.to_dict()),
                )
        except (TypeError, ValueError):
            logger.debug("Could not persist risk state", exc_info=True)

    def get_risk_manager_count(self) -> int:
        """Get count of active risk managers.

        Returns:
            Number of active risk managers
        """
        return len(self._risk_managers)
