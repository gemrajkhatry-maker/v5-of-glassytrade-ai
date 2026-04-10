"""NPOC Tracker — Naked Point of Control tracking.

NPOC = POC from a previous session that has NOT been revisited.
These act as secondary targets / magnets for price.

Fabio's AMT:
- NPOC above current price = bullish target
- NPOC below current price = bearish target
- NPOC is "filled" when price trades through it
- Only track NPOCs from the last 5 sessions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NPOC:
    """Naked Point of Control."""
    price: float
    session_date: str  # ISO date string
    is_filled: bool = False
    fill_date: str = ""

    @property
    def is_active(self) -> bool:
        return not self.is_filled


class NPOCTracker:
    """Tracks naked POCs across sessions.

    Usage:
        tracker = NPOCTracker(max_sessions=5)
        tracker.register_session_poc("2024-01-15", poc=100.0)
        tracker.update(price=101.0)  # Check if any NPOCs are filled
        active_npocs = tracker.get_active(direction="LONG")
    """

    def __init__(self, max_sessions: int = 5):
        self._max_sessions = max_sessions
        self._npocs: list[NPOC] = []
        self._current_session_poc: float = 0.0
        self._current_session_vah: float = 0.0
        self._current_session_val: float = 0.0

    def register_session_poc(
        self,
        session_date: str,
        poc: float,
        vah: float = 0.0,
        val: float = 0.0,
    ) -> None:
        """Register a completed session's POC as a potential NPOC."""
        if poc <= 0:
            return

        # Remove any NPOC at the same price (duplicate)
        self._npocs = [n for n in self._npocs if abs(n.price - poc) > 0.01]

        npoc = NPOC(price=poc, session_date=session_date)
        self._npocs.append(npoc)

        # Trim to max sessions
        if len(self._npocs) > self._max_sessions:
            self._npocs = self._npocs[-self._max_sessions:]

        logger.info("NPOC registered: %.2f (session: %s)", poc, session_date)

    def update(self, current_price: float) -> list[NPOC]:
        """Check if any active NPOCs have been filled.

        An NPOC is filled when price moves beyond it.
        Returns list of newly filled NPOCs.
        """
        newly_filled = []

        for npoc in self._npocs:
            if npoc.is_filled:
                continue

            # Simple fill: price moved beyond the NPOC level
            if current_price > npoc.price:
                self._fill_npoc(npoc)
                newly_filled.append(npoc)

        return newly_filled

    def _fill_npoc(self, npoc: NPOC) -> None:
        """Mark an NPOC as filled."""
        from datetime import datetime, timezone
        fill_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Create new NPOC with filled status (frozen dataclass)
        idx = self._npocs.index(npoc)
        self._npocs[idx] = NPOC(
            price=npoc.price,
            session_date=npoc.session_date,
            is_filled=True,
            fill_date=fill_date,
        )

        logger.info("NPOC FILLED: %.2f (session: %s)", npoc.price, npoc.session_date)

    def get_active(self, direction: str = "") -> list[NPOC]:
        """Get active (unfilled) NPOCs.

        Args:
            direction: "LONG" = NPOCs above price (targets),
                       "SHORT" = NPOCs below price (targets),
                       "" = all active
        """
        active = [n for n in self._npocs if not n.is_filled]

        if direction == "LONG":
            # For LONG trades, NPOCs above are targets
            return sorted(active, key=lambda n: n.price)
        elif direction == "SHORT":
            # For SHORT trades, NPOCs below are targets
            return sorted(active, key=lambda n: -n.price)
        return active

    def get_nearest(self, current_price: float, direction: str = "") -> NPOC | None:
        """Get the nearest active NPOC."""
        active = self.get_active(direction)
        if not active:
            return None

        return min(active, key=lambda n: abs(n.price - current_price))

    def set_current_session(self, poc: float, vah: float = 0.0, val: float = 0.0) -> None:
        """Set current session's levels for fill detection context."""
        self._current_session_poc = poc
        self._current_session_vah = vah
        self._current_session_val = val

    @property
    def active_count(self) -> int:
        return sum(1 for n in self._npocs if not n.is_filled)

    @property
    def filled_count(self) -> int:
        return sum(1 for n in self._npocs if n.is_filled)

    @property
    def all_npocs(self) -> list[NPOC]:
        return list(self._npocs)

    def reset(self) -> None:
        self._npocs.clear()
        self._current_session_poc = 0.0
        self._current_session_vah = 0.0
        self._current_session_val = 0.0
