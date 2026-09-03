"""Sole reconnect/backoff math. (REF-07)

Every retry loop delegates here with its OWN base/cap/attempts — the curves
are preserved byte-for-byte; only the formula has one owner.
"""
from __future__ import annotations

from dataclasses import dataclass

from shared.net_policy import capped_exp_delay

__all__ = ["ReconnectPolicy"]


@dataclass(frozen=True)
class ReconnectPolicy:
    base: float
    cap: float
    max_attempts: int

    def delay_for(self, attempt: int) -> float:
        """Delay before retry number `attempt` (0-based): min(base*2^attempt, cap)."""
        return capped_exp_delay(attempt, base=self.base, cap=self.cap)

    def should_retry(self, count: int) -> bool:
        """True while `count` completed attempts is below the budget."""
        return count < self.max_attempts
