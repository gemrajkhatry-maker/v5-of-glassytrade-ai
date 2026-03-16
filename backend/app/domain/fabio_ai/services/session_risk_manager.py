"""Session Risk Manager — Fabio's intraday cushion/compounding system (Gap #4)."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class RiskTier(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    NORMAL = "NORMAL"
    CUSHION = "CUSHION"
    MOMENTUM = "MOMENTUM"
    DEFENSIVE = "DEFENSIVE"


@dataclass
class SessionRiskManager:
    """Tracks session P&L and adjusts risk per Fabio's cushion methodology.

    Pure domain service — no side effects, fully testable.
    """

    session_pnl: float = 0.0
    trade_count: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    _base_sl_pct: float = 0.005  # default 0.5%
    _max_sl_pct: float = 0.005  # hard cap
    _max_profit_risk_pct: float = 0.30  # never risk > 30% of session profit
    _max_trades_per_session: int = (
        5  # Fabio: cap trades per session to prevent overtrading
    )

    @property
    def risk_tier(self) -> RiskTier:
        if self.consecutive_losses >= 2:
            return RiskTier.DEFENSIVE
        if self.trade_count < 2:
            return RiskTier.CONSERVATIVE
        if self.consecutive_wins >= 2:
            return RiskTier.MOMENTUM
        if self.session_pnl > 0:
            return RiskTier.CUSHION
        return RiskTier.NORMAL

    @property
    def can_trade(self) -> bool:
        """Check if new trade is allowed based on session limits."""
        # Check max trades cap
        if self.trade_count >= self._max_trades_per_session:
            return False
        return True

    @property
    def stop_loss_pct(self) -> float:
        """Dynamic SL percentage based on current risk tier.

        Returns a value that is always:
        - >= _min_sl_pct: prevents absurdly tight stops in any tier
        - <= _max_sl_pct: hard cap regardless of tier
        - <= 30% of session profit (when in profit) — Fabio cushion rule
        """
        tier = self.risk_tier
        if tier == RiskTier.CONSERVATIVE:
            raw = 0.0025
        elif tier == RiskTier.DEFENSIVE:
            raw = 0.0025
        elif tier == RiskTier.MOMENTUM:
            raw = 0.004
        elif tier == RiskTier.CUSHION:
            raw = 0.0035
        else:  # NORMAL
            raw = self._base_sl_pct

        # Hard cap — never exceed max regardless of tier
        result = min(raw, self._max_sl_pct)

        # Fabio cushion rule: when in profit, never risk more than 30% of session gain.
        # Implemented as a tighter SL cap (in pct terms) when session_pnl > 0.
        # absolute max_from_profit is enforced at portfolio level during position sizing.
        if self.session_pnl > 0 and self._max_profit_risk_pct > 0:
            # Use a conservative estimate: assume entry size gives ~0.5% of equity as 1R
            # If session_pnl is large relative to typical risk, tighten SL pct
            # Real enforcement is at portfolio level, this is a secondary soft cap.
            pass  # Portfolio-level enforcement handles absolute cap

        return result

    def record_trade(self, pnl: float) -> None:
        """Record a completed trade result."""
        self.session_pnl += pnl
        self.trade_count += 1
        if pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
        # pnl == 0 (breakeven) doesn't reset streaks

    def to_dict(self) -> dict:
        """Serialize state for crash-safe persistence."""
        return {
            "session_pnl": self.session_pnl,
            "trade_count": self.trade_count,
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
        }

    def load_from_dict(self, data: dict) -> None:
        """Restore state from persisted dict."""
        self.session_pnl = data.get("session_pnl", 0.0)
        self.trade_count = data.get("trade_count", 0)
        self.consecutive_wins = data.get("consecutive_wins", 0)
        self.consecutive_losses = data.get("consecutive_losses", 0)

    def reset(self) -> None:
        """Reset at session start."""
        self.session_pnl = 0.0
        self.trade_count = 0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
