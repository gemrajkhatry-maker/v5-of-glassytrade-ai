"""Port for persistent storage — domain-to-infrastructure boundary.

Domain defines this port. Infrastructure provides the adapter.
Uses Protocol for structural typing (no inheritance required).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IKeyValueStorage(Protocol):
    """Simple key-value storage port for domain state persistence."""

    def persist(self, key: str, value: str | None) -> None:
        """Persist a key-value pair."""
        ...

    def load(self, key: str) -> str | None:
        """Load a persisted value by key."""
        ...


class ITickStorage(ABC):
    @abstractmethod
    def save_tick(self, symbol: str, tick_data: dict[str, Any]) -> None: ...
    @abstractmethod
    def query_ticks(self, symbol: str, start: str | None = None, end: str | None = None, limit: int = 1000) -> list[dict[str, Any]]: ...


class ITradeStorage(ABC):
    @abstractmethod
    def save_trade(self, trade_data: dict[str, Any]) -> None: ...
    @abstractmethod
    def query_trades(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]: ...


class IDecisionStorage(ABC):
    @abstractmethod
    def save_llm_decision(self, decision_data: dict[str, Any]) -> None: ...
    @abstractmethod
    def query_llm_decisions(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]: ...


class IOpenPositionStorage(ABC):
    @abstractmethod
    def save_open_position(self, position: dict[str, Any]) -> None: ...
    @abstractmethod
    def delete_open_position(self, position_id: str) -> None: ...
    @abstractmethod
    def load_open_positions(self) -> list[dict[str, Any]]: ...
    @abstractmethod
    def clear_all_open_positions(self) -> int: ...


class IPositionEventStorage(ABC):
    @abstractmethod
    def save_position_event(self, event: dict[str, Any]) -> None: ...
    @abstractmethod
    def query_position_events(
        self, position_id: str | None = None, symbol: str | None = None,
    ) -> list[dict[str, Any]]: ...


class IStorage(
    ITickStorage,
    ITradeStorage,
    IDecisionStorage,
    IOpenPositionStorage,
    IPositionEventStorage,
):
    """Composite storage port — all sub-ports in one interface."""

    @abstractmethod
    def save_performance_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Persist an equity/performance snapshot."""
        ...

    @abstractmethod
    def save_session_profile(self, profile_data: dict[str, Any]) -> None:
        """Persist end-of-session volume profile."""
        ...

    @abstractmethod
    def get_previous_session_profile(
        self, symbol: str, market: str = "NSE",
    ) -> dict[str, Any] | None:
        """Retrieve the most recent completed session profile."""
        ...

    @abstractmethod
    def get_recent_trades(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve the most recent closed trades (newest first)."""
        ...
