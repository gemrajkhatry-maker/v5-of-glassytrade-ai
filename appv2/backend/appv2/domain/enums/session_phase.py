"""Session phase enum — NSE & MCX session tracking."""

from __future__ import annotations

from enum import Enum


class SessionPhase(str, Enum):
    """Trading session phases.

    NSE:
      PRE_MARKET    — before 09:15
      OPENING       — 09:15–09:30 (NO TRADE)
      PRIMARY       — 09:30–11:30 (ALL MODELS)
      MIDDAY        — 11:30–14:00 (REVERSION ONLY)
      POWER_HOUR    — 14:00–15:15 (ALL MODELS)
      CLOSE         — 15:15–15:30 (EXIT ONLY)
      POST_MARKET   — after 15:30

    MCX:
      PRE_OPEN      — 09:00–09:15
      MORNING       — 09:15–14:00
      AFTERNOON     — 14:00–18:00
      EVENING       — 18:00–23:00
      CLOSE         — 23:00–23:30
    """

    PRE_MARKET = "PRE_MARKET"
    OPENING = "OPENING"
    PRIMARY = "PRIMARY"
    MIDDAY = "MIDDAY"
    POWER_HOUR = "POWER_HOUR"
    CLOSE = "CLOSE"
    POST_MARKET = "POST_MARKET"
    # MCX-specific
    PRE_OPEN = "PRE_OPEN"
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"

    @property
    def allows_entry(self) -> bool:
        return self in (
            self.PRIMARY, self.MIDDAY, self.POWER_HOUR,
            self.MORNING, self.AFTERNOON, self.EVENING,
        )

    @property
    def allows_trend(self) -> bool:
        return self in (self.PRIMARY, self.POWER_HOUR, self.MORNING, self.AFTERNOON, self.EVENING)

    @property
    def allows_reversion(self) -> bool:
        return self in (self.PRIMARY, self.MIDDAY, self.POWER_HOUR, self.MORNING, self.AFTERNOON, self.EVENING)

    @property
    def forces_exit(self) -> bool:
        return self in (self.CLOSE,)
