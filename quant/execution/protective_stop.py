"""Single-owner protective stop state.
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


def resolve_protective_stop(submitted_sl: float, breakeven_floor: float | None,
                            trail_stop: float | None, side: str) -> tuple[float, str]:
    """Resolve the effective stop and reason for both bar and tick paths."""
    long = str(side).upper() == "LONG"
    effective = float(submitted_sl or 0.0)
    reason = "SL"
    if trail_stop is not None and ((long and trail_stop > effective) or (not long and trail_stop < effective)):
        effective, reason = float(trail_stop), "TRAIL"
    if breakeven_floor is not None and ((long and breakeven_floor > effective) or (not long and breakeven_floor < effective)):
        effective, reason = float(breakeven_floor), "BREAKEVEN"
    return effective, reason
