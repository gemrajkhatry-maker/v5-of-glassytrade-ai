"""Trade Journal port - Application service interface."""

from abc import ABC, abstractmethod
from typing import Any


class ITradeJournal(ABC):
    """Abstract interface for trade journal operations."""
    
    @abstractmethod
    def read_entries(self, date: str | None = None, run_id: str | None = None) -> list[dict]:
        """Read journal entries."""
        pass
    
    @abstractmethod
    def get_completed_trades(self, date: str | None = None, run_id: str | None = None) -> list[dict]:
        """Get completed trades."""
        pass
    
    @abstractmethod
    def summary(self, date: str | None = None, run_id: str | None = None) -> dict:
        """Get trade summary."""
        pass
    
    @abstractmethod
    def report(self, date: str | None = None, run_id: str | None = None) -> dict:
        """Get attribution and symbol-level report."""
        pass
    
    @abstractmethod
    def compare_runs(self, start_date: str | None, end_date: str | None, run_ids: list[str] | None) -> dict:
        """Compare runs."""
        pass
    
    @abstractmethod
    def assess_promotion(self, **kwargs) -> dict:
        """Assess run promotion."""
        pass