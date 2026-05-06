"""Session-level risk accounting and circuit-breaker policy."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CapitalRiskBand(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    NORMAL = "NORMAL"
    CUSHION = "CUSHION"
    MOMENTUM = "MOMENTUM"
    DEFENSIVE = "DEFENSIVE"


@dataclass
class SessionRiskManager:
    session_pnl: float = 0.0
    trade_count: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    _base_sl_pct: float = 0.005
    _max_sl_pct: float = 0.005
    _max_profit_risk_pct: float = 0.30
    max_consecutive_losses: int = 3
    _halted: bool = False

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
        if self._halted:
            return False
        if self.consecutive_losses >= self.max_consecutive_losses:
            self._halted = True
            return False
        return True

    @property
    def halt_reason(self) -> str:
        if self._halted:
            return f"3-loss circuit breaker: {self.consecutive_losses} consecutive losses"
        if self.consecutive_losses >= self.max_consecutive_losses:
            return f"Circuit breaker: {self.consecutive_losses} consecutive losses"
        return ""

    @property
    def stop_loss_pct(self) -> float:
        tier = self.risk_tier
        if tier in {CapitalRiskBand.CONSERVATIVE, CapitalRiskBand.DEFENSIVE}:
            raw = 0.0025
        elif tier == CapitalRiskBand.MOMENTUM:
            raw = 0.004
        elif tier == CapitalRiskBand.CUSHION:
            raw = 0.0035
        else:
            raw = self._base_sl_pct
        return min(raw, self._max_sl_pct)

    def record_trade(self, pnl: float) -> None:
        self.session_pnl += float(pnl)
        self.trade_count += 1
        if pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            if self.consecutive_losses >= self.max_consecutive_losses:
                self._halted = True

    def to_dict(self) -> dict:
        return {
            "session_pnl": self.session_pnl,
            "trade_count": self.trade_count,
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "_halted": self._halted,
        }

    def load_from_dict(self, data: dict) -> None:
        self.session_pnl = float(data.get("session_pnl", 0.0))
        self.trade_count = int(data.get("trade_count", 0))
        self.consecutive_wins = int(data.get("consecutive_wins", 0))
        self.consecutive_losses = int(data.get("consecutive_losses", 0))
        self._halted = bool(data.get("_halted", False))

    def reset(self) -> None:
        self.session_pnl = 0.0
        self.trade_count = 0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self._halted = False
