"""Single-owner protective stop state.

This value object is intentionally pure and immutable. ExitEngine is the runtime
owner; calculators propose candidates, while ``tighten`` applies the one
monotonic policy shared by bar exits, tick exits, partial fills and replay.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

StopKind = Literal["TRAIL", "BREAKEVEN", "PYRAMID_BASE"]


@dataclass(frozen=True)
class ProtectiveStopState:
    submitted_sl: float = 0.0
    side: str = "LONG"
    breakeven_floor: float | None = None
    trail_stop: float | None = None
    authority: str = "SUBMITTED"
    updated_at_bar: int = -1

    @property
    def effective_stop(self) -> float:
        """Return the tightest currently active protective level."""
        candidates = [float(self.submitted_sl)]
        if self.breakeven_floor is not None:
            candidates.append(float(self.breakeven_floor))
        if self.trail_stop is not None:
            candidates.append(float(self.trail_stop))
        positive = [v for v in candidates if v > 0]
        if not positive:
            return 0.0
        return max(positive) if self.side.upper() == "LONG" else min(positive)

    def tighten(self, candidate: float, *, kind: StopKind, bar_index: int = -1) -> "ProtectiveStopState":
        """Apply a candidate only when it tightens the effective stop."""
        candidate = float(candidate)
        if candidate <= 0:
            return self
        current = self.effective_stop
        tighter = candidate > current if self.side.upper() == "LONG" else candidate < current
        if not tighter:
            return self
        if kind == "BREAKEVEN":
            return replace(self, breakeven_floor=candidate, authority=kind, updated_at_bar=bar_index)
        return replace(self, trail_stop=candidate, authority=kind, updated_at_bar=bar_index)
