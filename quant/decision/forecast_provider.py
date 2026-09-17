"""Forecast access for exits/UI — NOT an entry authority (decision 2026-09-17)."""
from __future__ import annotations

from typing import Any


def fresh_forecast(advisor: Any, strategy: Any, *, symbol: str, bar_index: int) -> Any | None:
    """Return the latest TimesFM forecast for ``symbol``, or None.

    Order: the advisor's native engine cache (single inference per bar, shared
    with the UI), then the strategy's cache (transitional), else None. The
    caller applies the staleness rule (bar_index - asof_bar <= 1).
    """
    engine = getattr(advisor, "_native_engine", None) if advisor is not None else None
    if engine is not None:
        getter = getattr(engine, "last_forecast_for", None)
        if callable(getter):
            fc = getter(symbol)
            if fc is not None:
                return fc
    getter = getattr(strategy, "get_latest_forecast", None) if strategy is not None else None
    if callable(getter):
        return getter(symbol)
    return None


__all__ = ["fresh_forecast"]
