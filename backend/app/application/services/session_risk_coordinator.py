"""Session Risk Coordinator — Manages session-level risk.

Responsibilities:
- Session risk manager integration
- Risk state tracking
- Risk-based decisions
- System risk aggregation
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.trading.services.risk_manager import RiskManager
from app.domain.fabio_ai.services.session_risk_manager import SessionRiskManager

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Signal
    from app.domain.trading.models.aggregates import Portfolio

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
    drift_alert: bool
    drift_message: str


class SessionRiskCoordinator:
    """Coordinates session-level risk management.
    
    This module encapsulates all session-level risk management logic,
    providing a single source of truth for risk decisions across the codebase.
    """

    def __init__(self, storage=None):
        self._risk_managers: dict[str, RiskManager] = {}
        self._session_risk_managers: dict[str, SessionRiskManager] = {}
        self._session_creation_lock = threading.Lock()
        self._storage = storage

    def _get_risk_manager(self, symbol: str) -> RiskManager:
        """Return per-symbol RiskManager, creating one if needed.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            RiskManager for the symbol
        """
        with self._session_creation_lock:
            if symbol not in self._risk_managers:
                self._risk_managers[symbol] = RiskManager()
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
                if self._storage and hasattr(self._storage, 'kv_get'):
                    try:
                        import json
                        from datetime import date
                        saved = self._storage.kv_get(f"risk_state_{symbol}_{date.today().isoformat()}")
                        if saved:
                            srm.load_from_dict(json.loads(saved))
                            logger.info("Restored risk state for %s: tier=%s, pnl=%.2f",
                                        symbol, srm.risk_tier.name, srm.session_pnl)
                    except Exception:
                        logger.debug("Could not load risk state for %s", symbol, exc_info=True)
                self._session_risk_managers[symbol] = srm
            return self._session_risk_managers[symbol]

    def validate_entry(self, symbol: str, signal: Signal, portfolio: Portfolio) -> bool:
        """Validate entry against risk limits.
        
        Args:
            symbol: Trading symbol
            signal: Trade signal
            portfolio: Portfolio
        
        Returns:
            True if entry is valid
        """
        risk_manager = self._get_risk_manager(symbol)
        return risk_manager.validate(signal, portfolio)

    def record_trade_result(self, symbol: str, pnl: float, portfolio: Portfolio) -> None:
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
        return risk_manager.is_halted

    def halt_trading(self) -> None:
        """Activate the global emergency kill switch."""
        RiskManager.halt_trading()

    def resume_trading(self) -> None:
        """Clear the global emergency kill switch."""
        RiskManager.resume_trading()

    def get_system_risk_state(self) -> SystemRiskState:
        """Return an aggregated system-wide view of runtime risk state.
        
        Returns:
            SystemRiskState with aggregated risk information
        """
        with self._session_creation_lock:
            managers = list(self._risk_managers.values())

        if not managers:
            return SystemRiskState(
                halted=RiskManager._global_halt,
                halt_reason="Emergency kill switch active" if RiskManager._global_halt else "",
                daily_drawdown_pct=0.0,
                consecutive_losses=0,
                peak_equity=0.0,
                current_equity=0.0,
                drift_alert=False,
                drift_message="",
            )

        peak_equity = max((rm.daily_state.peak_equity for rm in managers), default=0.0)
        current_equity = sum(rm.daily_state.current_equity for rm in managers)
        consecutive_losses = max((rm.daily_state.consecutive_losses for rm in managers), default=0)
        drift_alert = any(getattr(rm, "_drift_alert", False) for rm in managers)
        drift_messages = [
            getattr(rm, "_drift_message", "")
            for rm in managers
            if getattr(rm, "_drift_message", "")
        ]
        halted_manager = next((rm for rm in managers if rm.is_halted), None)

        if RiskManager._global_halt:
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

        return SystemRiskState(
            halted=halted,
            halt_reason=halt_reason,
            daily_drawdown_pct=daily_drawdown_pct,
            consecutive_losses=consecutive_losses,
            peak_equity=peak_equity,
            current_equity=current_equity,
            drift_alert=drift_alert,
            drift_message=" | ".join(drift_messages[:3]),
        )

    def persist_risk_state(self, symbol: str) -> None:
        """Persist risk state to storage.
        
        Args:
            symbol: Trading symbol
        """
        if not self._storage or not hasattr(self._storage, 'kv_set'):
            return
        
        try:
            import json
            from datetime import date
            srm = self._session_risk_managers.get(symbol)
            if srm:
                self._storage.kv_set(
                    f"risk_state_{symbol}_{date.today().isoformat()}",
                    json.dumps(srm.to_dict()),
                )
        except Exception:
            logger.debug("Could not persist risk state", exc_info=True)

    def get_risk_manager_count(self) -> int:
        """Get count of active risk managers.
        
        Returns:
            Number of active risk managers
        """
        return len(self._risk_managers)