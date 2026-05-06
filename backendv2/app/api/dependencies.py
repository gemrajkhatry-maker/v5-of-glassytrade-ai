"""API-level dependency helpers for lightweight v2 endpoint parity."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.infrastructure.storage import SQLiteStorageAdapter


def get_storage(request: Request) -> SQLiteStorageAdapter | None:
    """Return the application storage adapter if available."""
    storage = getattr(request.app.state, "storage", None)
    if isinstance(storage, SQLiteStorageAdapter):
        return storage
    return None


def get_active_symbols(request: Request) -> list[str]:
    """Return known active symbols from orchestrator or recent LLM decisions."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is not None:
        active = getattr(orchestrator, "get_active_symbols", None)
        if callable(active):
            try:
                return list(active())
            except Exception:
                pass

    storage = get_storage(request)
    if storage is None:
        return []

    try:
        rows = storage.query_llm_decisions(start=None, end=None)
        symbols = []
        seen: set[str] = set()
        for row in rows:
            symbol = str(row.get("symbol", "")).strip()
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
        return symbols
    except Exception:
        return []


def get_gen_ai_service() -> Any:
    """Placeholder dependency for compatibility.

    The historical v1 dependency chain expects a GenerativeAIService object.
    In v2 this service is still under construction, so callers should handle
    the fallback path when this returns ``None``.
    """
    return None


@dataclass
class _TradeJournalProxy:
    """Null-object style journal adapter for compatibility endpoints."""

    def read_entries(self, date: str | None = None, run_id: str | None = None):
        return []

    def get_completed_trades(self, date: str | None = None, run_id: str | None = None):
        return []

    def summary(self, date: str | None = None, run_id: str | None = None):
        return {
            "status": "disabled",
            "message": "trade journal not mounted",
            "date": date,
            "runId": run_id,
        }

    def compare_runs(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        run_ids: list[str] | None = None,
    ):
        return {
            "status": "disabled",
            "message": "trade journal not mounted",
            "startDate": start_date,
            "endDate": end_date,
            "runIds": run_ids,
        }

    def assess_promotion(self, **kwargs: Any):
        return {
            "status": "disabled",
            "message": "trade journal not mounted",
            "criteria": kwargs,
        }


def get_trade_journal() -> _TradeJournalProxy:
    """Return a compatibility journal facade."""
    return _TradeJournalProxy()

