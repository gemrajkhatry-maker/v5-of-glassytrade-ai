from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    daily_loss_limit: float = 5000.0
    max_trades: int = 20
    cooldown_sec: float = 300.0


class SessionRisk:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self.realized = 0.0
        self.trades = 0
        self.halt: str | None = None
        self.cooldown_until = 0.0

    def record_fill(self, pnl: float, now: float) -> None:
        self.realized += pnl
        self.trades += 1
        if pnl < 0:
            self.cooldown_until = now + self.limits.cooldown_sec
        if self.realized <= -abs(self.limits.daily_loss_limit):
            self.halt = "DAILY_LOSS"
        elif self.trades >= self.limits.max_trades:
            self.halt = "MAX_TRADES"

    def can_trade(self, now: float) -> tuple[bool, str]:
        if self.halt is not None:
            return False, self.halt
        if now < self.cooldown_until:
            return False, "COOLDOWN"
        return True, ""

    def cooldown_s(self, now: float) -> float:
        return max(0.0, self.cooldown_until - now)