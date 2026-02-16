"""Port for persistent storage — domain-to-infrastructure boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StoragePort(ABC):
    """Abstraction for persisting ticks, trades, and LLM decisions."""

    @abstractmethod
    def save_tick(self, symbol: str, tick_data: dict[str, Any]) -> None:
        """Persist a single tick."""

    @abstractmethod
    def save_trade(self, trade_data: dict[str, Any]) -> None:
        """Persist a closed trade."""

    @abstractmethod
    def save_llm_decision(self, decision_data: dict[str, Any]) -> None:
        """Persist an LLM analysis decision."""

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
    def query_llm_decisions(
        self, start: str | None = None, end: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query historical LLM decisions."""
