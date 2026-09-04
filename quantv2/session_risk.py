from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    daily_loss_limit: float = 5000.0
    max_trades: int = 20
    cooldown_sec: float = 300.0
    mdl_pct: float = 0.02
    max_consec_losses: int = 3
    cushion_frac: float = 0.40
    base_risk_pct: float = 0.0025


class SessionRisk:
    def __init__(self, limits: RiskLimits, starting_equity: float = 100000.0) -> None:
        self.limits = limits
        self.starting_equity = starting_equity
        self.realized = 0.0
        self.trades = 0
        self.consec_losses = 0
        self.halt: str | None = None
        self.cooldown_until = 0.0

    def _loss_limit(self) -> float:
        limit = abs(self.limits.daily_loss_limit)
        if self.limits.mdl_pct > 0:
            limit = min(limit, self.starting_equity * self.limits.mdl_pct)
        return limit

    def record_fill(self, pnl: float, now: float) -> None:
        self.realized += pnl
        self.trades += 1
        self.cooldown_until = now + self.limits.cooldown_sec
        if pnl < 0:
            self.consec_losses += 1
        else:
            self.consec_losses = 0
        if self.realized <= -self._loss_limit():
            self.halt = "DAILY_LOSS"
        elif self.limits.max_consec_losses > 0 and self.consec_losses >= self.limits.max_consec_losses:
            self.halt = "THREE_LOSSES"
        elif self.trades >= self.limits.max_trades:
            self.halt = "MAX_TRADES"

    def size_multiplier(self) -> float:
        if self.halt is not None:
            return 0.0
        base = self.starting_equity * self.limits.base_risk_pct
        if base <= 0:
            return 1.0
        if self.realized > 0:
            return 1.0 + self.limits.cushion_frac * self.realized / base
        remaining = self._loss_limit() + self.realized
        return min(base, max(remaining, 0.0)) / base

    def can_trade(self, now: float) -> tuple[bool, str]:
        if self.halt is not None:
            return False, self.halt
        if now < self.cooldown_until:
            return False, "COOLDOWN"
        return True, ""

    def cooldown_s(self, now: float) -> float:
        return max(0.0, self.cooldown_until - now)
