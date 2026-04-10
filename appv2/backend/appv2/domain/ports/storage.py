"""Storage Port — abstract interface for persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod


class StoragePort(ABC):
    """Abstract interface for data persistence."""

    @abstractmethod
    async def save_trade(self, trade_data: dict) -> str:
        """Save trade record. Returns trade_id."""

    @abstractmethod
    async def update_trade(self, trade_id: str, updates: dict) -> None:
        """Update trade record."""

    @abstractmethod
    async def get_trade(self, trade_id: str) -> dict | None:
        """Get trade by ID."""

    @abstractmethod
    async def get_open_trades(self, symbol: str = "") -> list[dict]:
        """Get all open trades, optionally filtered by symbol."""

    @abstractmethod
    async def get_trades_by_date(self, date_str: str) -> list[dict]:
        """Get all trades for a specific date."""

    @abstractmethod
    async def save_signal(self, signal_data: dict) -> str:
        """Save signal record."""

    @abstractmethod
    async def kv_set(self, key: str, value: str) -> None:
        """Set key-value pair (for crash recovery state)."""

    @abstractmethod
    async def kv_get(self, key: str) -> str | None:
        """Get key-value pair."""

    @abstractmethod
    async def kv_delete(self, key: str) -> None:
        """Delete key-value pair."""

    @abstractmethod
    async def save_daily_pnl(self, date_str: str, pnl: float) -> None:
        """Save daily P&L snapshot."""

    @abstractmethod
    async def get_daily_pnl(self, date_str: str) -> float:
        """Get daily P&L."""
