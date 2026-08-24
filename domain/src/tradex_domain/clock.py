"""Clock vocabulary — deterministic time shared by every execution mode.

NautilusTrader-style timing discipline (P0-1): the same ``Clock`` API is used
in backtest, replay, paper, and live so strategies and engines reason about
time identically in every mode.

- :class:`Clock` — the structural protocol (``now() -> datetime``).
- :class:`SystemClock` — wall clock (real UTC time) for live/paper.
- :class:`TestClock` — deterministic, advanceable clock for backtest/replay:
  it is driven forward by the engine as events stream, so ``clock.now()``
  reflects the simulated instant instead of wall time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Deterministic clock abstraction.

    Satisfied structurally by any object with a ``now() -> datetime`` method.
    """

    def now(self) -> datetime: ...


class SystemClock:
    """Wall-clock implementation — real UTC time (live/paper modes)."""

    def now(self) -> datetime:
        """Return the current UTC instant."""
        return datetime.now(UTC)


class TestClock:
    """Deterministic, advanceable clock for backtests, replays, and tests.

    Starts at a fixed instant (defaults to the current UTC time) and only
    moves when the engine or test drives it — never on its own. ``advance_to``
    is monotonic (forward-only), matching ordered event-stream semantics: a
    replay tape never moves time backwards.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start if start is not None else datetime.now(UTC)

    def now(self) -> datetime:
        """Return the current simulated instant."""
        return self._now

    def set(self, value: datetime) -> None:
        """Set the clock to *value* unconditionally."""
        self._now = value

    def advance(self, delta: timedelta) -> None:
        """Advance the clock by *delta*."""
        self._now += delta

    def advance_to(self, value: datetime) -> None:
        """Advance the clock to *value* if it is in the future (monotonic).

        Robust to mixed aware/naive values: datalake tapes carry tz-naive IST
        timestamps while the default clock start is tz-aware UTC, so the
        forward-ness comparison falls back to wall-clock parts instead of
        raising; the clock then adopts *value*'s tzinfo on assignment.
        """
        try:
            ahead = value > self._now
        except TypeError:
            ahead = value.replace(tzinfo=None) > self._now.replace(tzinfo=None)
        if ahead:
            self._now = value


__all__ = ["Clock", "SystemClock", "TestClock"]
