"""Port for persistent storage — domain-to-infrastructure boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# KeyValue Storage Port (Protocol for simple persistence)
# ---------------------------------------------------------------------------


@runtime_checkable
class IKeyValueStorage(Protocol):
    """Simple key-value storage port for domain state persistence.

    This Protocol replaces the untyped persist_fn callback pattern.
    Domain services use this interface; application layer provides
    concrete implementation (e.g., database-backed storage).

    Example usage in LossTracker:
        def __init__(self, storage: IKeyValueStorage | None = None):
            self._storage = storage

        def save(self):
            if self._storage:
                self._storage.persist("daily_losses", json.dumps(data))
    """

    def persist(self, key: str, value: str | None) -> None:
        """Persist a key-value pair.

        Args:
            key: Storage key (e.g., "daily_losses_v2").
            value: JSON string to store, or None to delete.
        """
        ...

    def load(self, key: str) -> str | None:
        """Load a persisted value by key.

        Args:
            key: Storage key to retrieve.

        Returns:
            Stored JSON string, or None if not found.
        """
        ...


# ---------------------------------------------------------------------------


class IStorage(ABC):
    """Abstraction for persisting ticks, trades, and positions."""

    @abstractmethod
    def save_tick(self, symbol: str, tick_data: dict[str, Any]) -> None:
        """Persist a single tick."""

    @abstractmethod
    def save_trade(self, trade_data: dict[str, Any]) -> None:
        """Persist a closed trade."""

    @abstractmethod
    def save_performance_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Persist an equity/performance snapshot."""

    @abstractmethod
    def query_ticks(
        self, symbol: str, start: str | None = None, end: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query historical ticks."""

    @abstractmethod
    def query_trades(
        self, start: str | None = None, end: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query historical trades."""

    @abstractmethod
    def save_session_profile(self, profile_data: dict[str, Any]) -> None:
        """Persist end-of-session volume profile (VAH/VAL/POC/date/symbol)."""

    @abstractmethod
    def get_previous_session_profile(
        self, symbol: str, market: str = "NSE",
    ) -> dict[str, Any] | None:
        """Retrieve the most recent completed session profile for gap analysis."""

    @abstractmethod
    def get_recent_trades(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve the most recent closed trades (newest first)."""

    def save_fill(self, fill: dict[str, Any]) -> None:
        """Persist one idempotent fill-ledger record."""
        raise NotImplementedError

    def load_fills(
        self, *, position_id: str | None = None, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        """Load fill-ledger records in event order."""
        raise NotImplementedError

    @abstractmethod
    def save_position_event(self, event: dict[str, Any]) -> None:
        """Persist an append-only position lifecycle event."""

    @abstractmethod
    def query_position_events(
        self, position_id: str | None = None, symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query append-only position lifecycle events."""
