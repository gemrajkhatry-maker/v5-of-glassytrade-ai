"""NPOC Adapter — wraps domain NPOCTracker to INPOC port."""

from __future__ import annotations

from app.domain.shared.port.npoc import INPOC, NPOCResult
from app.domain.amt.service.npoc_tracker import NPOCTracker


class _NullNPOCStorage:
    """Minimal no-op storage fallback when persistence is unavailable."""

    def save_npoc(self, underlying: str, date: str, poc: float) -> None:
        return None

    def mark_npoc_filled(self, underlying: str, date: str, filled_at: str) -> None:
        return None

    def get_active_npocs(self, underlying: str) -> list:
        return []


class NPOCAdapter(INPOC):
    """Adapter for INPOC using the shared-domain NPOCTracker."""

    def __init__(self, storage_port=None) -> None:
        if storage_port is None:
            storage_port = _NullNPOCStorage()
        self._tracker = NPOCTracker(storage_port=storage_port)

    def add_session_poc(self, underlying: str, date: str, poc: float) -> None:
        self._tracker.add_session_poc(underlying, date, poc)

    def check_and_fill(self, underlying: str, current_price: float, tick_size: float) -> list[str]:
        return self._tracker.check_and_fill(underlying, current_price, tick_size)

    def get_active_npocs(
        self, underlying: str, current_price: float, lookback_days: int = 5
    ) -> NPOCResult:
        return self._tracker.get_active_npocs(underlying, current_price, lookback_days)

    def load_from_storage(self, underlying: str) -> None:
        self._tracker.load_from_storage(underlying)
