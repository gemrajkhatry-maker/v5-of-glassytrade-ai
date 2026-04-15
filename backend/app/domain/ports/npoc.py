"""Port for Naked POC (NPOC) tracking — domain-to-infrastructure boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class NPOCRecord:
    """A single naked (unfilled) POC from a previous session."""

    price: float
    session_date: str
    underlying: str
    is_filled: bool
    filled_at: str | None = None


@dataclass(frozen=True)
class NPOCResult:
    """Result of querying active NPOCs relative to current price."""

    nearest_above: NPOCRecord | None
    nearest_below: NPOCRecord | None
    all_active: tuple[NPOCRecord, ...]


class INPOC(ABC):
    """Interface for tracking naked (unfilled) previous session POCs.

    Per Fabio methodology, previous session POCs that haven't been revisited
    act as magnets and potential secondary targets for P3 trailing.
    """

    @abstractmethod
    def add_session_poc(self, underlying: str, date: str, poc: float) -> None:
        """Record a session's POC as a new NPOC.

        Called at session close to save the POC for future tracking.
        """

    @abstractmethod
    def check_and_fill(self, underlying: str, current_price: float, tick_size: float) -> list[str]:
        """Check all active NPOCs and mark as filled if price is within 2 ticks.

        Returns list of session dates whose NPOCs were just filled.
        """

    @abstractmethod
    def get_active_npocs(self, underlying: str, current_price: float, lookback_days: int = 5) -> NPOCResult:
        """Return nearest unfilled NPOCs above and below current price."""

    @abstractmethod
    def load_from_storage(self, underlying: str) -> None:
        """Load active NPOCs from persistent storage on startup."""
