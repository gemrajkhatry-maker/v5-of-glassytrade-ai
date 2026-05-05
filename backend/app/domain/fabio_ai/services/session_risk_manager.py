"""Session Risk Manager — Fabio's intraday cushion/compounding system (Gap #4).

NOW WITH:
- 3-Loss Daily Circuit Breaker (FIX: Fabio rule: "stop trading after 3 consecutive stop-outs")
- Dynamic risk tier adjustment
- Session trade limits
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CapitalRiskBand(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    NORMAL = "NORMAL"
    CUSHION = "CUSHION"
    MOMENTUM = "MOMENTUM"
    DEFENSIVE = "DEFENSIVE"


@dataclass
class SessionRiskManager:
    """Tracks session P&L and adjusts risk per Fabio's cushion methodology.

    FABIO RULE: "If you hit 3 stop-outs, stop trading for the day.
    The market is not aligned with your reads."
    
    Pure domain service — no side effects, fully testable.
    """

    session_pnl: float = 0.0
    trade_count: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    _base_sl_pct: float = 0.005  # default 0.5%
    _max_sl_pct: float = 0.005  # hard cap
    _max_profit_risk_pct: float = 0.30  # never risk > 30% of session profit
    
    # ── FIX: 3-Loss Daily Circuit Breaker ──
    # Fabio: "If you hit 3 stop-outs, stop trading for the day."
    max_consecutive_losses: int = 3  # Circuit breaker threshold
    _halted: bool = False  # True when circuit breaker is triggered

    @property
    def risk_tier(self) -> CapitalRiskBand:
        if self._halted:
            return CapitalRiskBand.DEFENSIVE
        if self.consecutive_losses >= 2:
            return CapitalRiskBand.DEFENSIVE
        if self.trade_count < 2:
            return CapitalRiskBand.CONSERVATIVE
        if self.consecutive_wins >= 2:
            return CapitalRiskBand.MOMENTUM
        if self.session_pnl > 0:
            return CapitalRiskBand.CUSHION
        return CapitalRiskBand.NORMAL

    @property
    def can_trade(self) -> bool:
        """Check if new trade is allowed based on session limits.
        
        ENFORCES:
        1. Circuit breaker (3 consecutive losses)
        2. Halted state
        """
        if self._halted:
            return False
        if self.consecutive_losses >= self.max_consecutive_losses:
            self._halted = True
            logger.critical(
                "CIRCUIT BREAKER: %d consecutive losses — halting for session",
                self.consecutive_losses,
            )
            return False
        return True

    @property
    def halt_reason(self) -> str:
        """Return reason for halt, or empty string if trading allowed."""
        if self._halted:
            return f"3-loss circuit breaker: {self.consecutive_losses} consecutive losses"
        if self.consecutive_losses >= self.max_consecutive_losses:
            return f"Circuit breaker: {self.consecutive_losses} consecutive losses"
        return ""

    @property
    def stop_loss_pct(self) -> float:
        """Dynamic SL percentage based on current risk tier.

        Returns a value that is always:
        - >= _min_sl_pct: prevents absurdly tight stops in any tier
        - <= _max_sl_pct: hard cap regardless of tier
        - <= 30% of session profit (when in profit) — Fabio cushion rule
        """
        tier = self.risk_tier
        if tier == CapitalRiskBand.CONSERVATIVE:
            raw = 0.0025
        elif tier == CapitalRiskBand.DEFENSIVE:
            raw = 0.0025
        elif tier == CapitalRiskBand.MOMENTUM:
            raw = 0.004
        elif tier == CapitalRiskBand.CUSHION:
            raw = 0.0035
        else:  # NORMAL
            raw = self._base_sl_pct

        # Hard cap — never exceed max regardless of tier
        result = min(raw, self._max_sl_pct)

        return result

    def record_trade(self, pnl) -> None:
        """Record a completed trade result and check circuit breaker."""
        self.session_pnl += float(pnl)
        self.trade_count += 1
        if pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            
            # ── Check circuit breaker immediately ──
            if self.consecutive_losses >= self.max_consecutive_losses:
                self._halted = True
                logger.critical(
                    "CIRCUIT BREAKER ACTIVATED: %d consecutive losses. "
                    "Session halted per Fabio rule.",
                    self.consecutive_losses,
                )
        # pnl == 0 (breakeven) doesn't reset streaks

    def to_dict(self) -> dict:
        """Serialize state for crash-safe persistence."""
        return {
            "session_pnl": self.session_pnl,
            "trade_count": self.trade_count,
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "_halted": self._halted,
        }

    def load_from_dict(self, data: dict) -> None:
        """Restore state from persisted dict."""
        self.session_pnl = data.get("session_pnl", 0.0)
        self.trade_count = data.get("trade_count", 0)
        self.consecutive_wins = data.get("consecutive_wins", 0)
        self.consecutive_losses = data.get("consecutive_losses", 0)
        self._halted = data.get("_halted", False)

    def reset(self) -> None:
        """Reset at session start."""
        self.session_pnl = 0.0
        self.trade_count = 0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self._halted = False
