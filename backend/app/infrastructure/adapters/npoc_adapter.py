"""NPOC Adapter — Infrastructure adapter wrapping NPOCTracker domain service.

Bridges the INPOC port to the NPOCTracker domain implementation.
Accepts an IStorage instance and delegates all operations to NPOCTracker.
"""

from __future__ import annotations

from app.domain.ports.npoc import INPOC, NPOCRecord, NPOCResult
from app.domain.fabio_ai.services.npoc_tracker import NPOCTracker


class NPOCAdapter(INPOC):
    """Wraps NPOCTracker to satisfy the INPOC port contract.

    DI pattern: Port (INPOC) → Adapter (this class) → ServiceGraph injection.
    NPOCTracker requires a storage_port with save_npoc, mark_npoc_filled,
    and get_active_npocs methods (provided by SQLiteStorageAdapter).
    """

    def __init__(self, storage_port=None) -> None:
        """Initialise with an optional storage port.

        Args:
            storage_port: An IStorage-compatible object that implements
                save_npoc(), mark_npoc_filled(), and get_active_npocs().
                If None, a NullStorage stub is used (suitable for tests).
        """
        if storage_port is None:
            storage_port = _NullNPOCStorage()
        self._tracker = NPOCTracker(storage_port=storage_port)

    def add_session_poc(self, underlying: str, date: str, poc: float) -> None:
        """Record a session's POC as a new NPOC."""
        self._tracker.add_session_poc(underlying, date, poc)

    def check_and_fill(
        self, underlying: str, current_price: float, tick_size: float
    ) -> list[str]:
        """Check active NPOCs and mark as filled if price is within 2 ticks."""
        return self._tracker.check_and_fill(underlying, current_price, tick_size)

    def get_active_npocs(
        self, underlying: str, current_price: float, lookback_days: int = 5
    ) -> NPOCResult:
        """Return nearest unfilled NPOCs above and below current price."""
        return self._tracker.get_active_npocs(underlying, current_price, lookback_days)

    def load_from_storage(self, underlying: str) -> None:
        """Load active NPOCs from persistent storage on startup."""
        self._tracker.load_from_storage(underlying)


class _NullNPOCStorage:
    """Minimal no-op storage stub used when no storage is configured."""

    def save_npoc(self, underlying: str, date: str, poc: float) -> None:
        pass

    def mark_npoc_filled(self, underlying: str, date: str, filled_at: str) -> None:
        pass

    def get_active_npocs(self, underlying: str) -> list:
        return []
