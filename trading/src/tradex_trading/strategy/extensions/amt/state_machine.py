"""Triple-A phase machine from the archived AMT proposal."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tradex_trading.strategy.extensions.amt.model import AMTPhase, AMTSnapshot


@dataclass(frozen=True, slots=True)
class TripleAResult:
    phase: AMTPhase
    direction: str | None = None


class TripleAStateMachine:
    def __init__(self, accumulation_bars: int = 2, max_absorption_age: int = 5) -> None:
        if accumulation_bars < 1:
            raise ValueError("accumulation_bars must be positive")
        if max_absorption_age < 0:
            raise ValueError("max_absorption_age cannot be negative")
        self._required = accumulation_bars
        self._max_absorption_age = max_absorption_age
        self._phase = AMTPhase.WAITING
        self._side: str | None = None
        self._near_poc = 0
        self._last_direction: str | None = None

    @property
    def phase(self) -> AMTPhase:
        return self._phase

    @property
    def last_direction(self) -> str | None:
        return self._last_direction

    def reset(self) -> None:
        self._phase = AMTPhase.WAITING
        self._side = None
        self._near_poc = 0
        self._last_direction = None

    def update(self, snapshot: AMTSnapshot) -> TripleAResult:
        """Advance exactly one phase using one closed-bar snapshot."""
        if self._phase is AMTPhase.AGGRESSION:
            self.reset()

        fresh = (
            snapshot.absorption_side in {"BUY", "SELL"}
            and snapshot.absorption_strength > 0
            and (
                snapshot.absorption_age is None
                or                snapshot.absorption_age <= self._max_absorption_age

            )
        )
        near_poc = (
            snapshot.poc is not None
            and abs(snapshot.close - snapshot.poc) <= Decimal("1")
        )
        if self._phase is AMTPhase.WAITING:
            if fresh:
                self._phase = AMTPhase.ABSORBING
                self._side = snapshot.absorption_side
                self._near_poc = 1 if near_poc else 0
            return TripleAResult(self._phase)

        if self._phase is AMTPhase.ABSORBING:
            if fresh and self._side is None:
                self._side = snapshot.absorption_side
            if near_poc:
                self._near_poc += 1
            else:
                self._near_poc = 0
            if self._near_poc >= self._required:
                self._phase = AMTPhase.ACCUMULATING
            return TripleAResult(self._phase)

        if self._phase is AMTPhase.ACCUMULATING:
            side = self._side
            if side == "BUY" and snapshot.close > snapshot.upper_1:
                self._phase = AMTPhase.AGGRESSION
                self._last_direction = "LONG"
            elif side == "SELL" and snapshot.close < snapshot.lower_1:
                self._phase = AMTPhase.AGGRESSION
                self._last_direction = "SHORT"
            return TripleAResult(self._phase, self._last_direction)

        return TripleAResult(self._phase, self._last_direction)
