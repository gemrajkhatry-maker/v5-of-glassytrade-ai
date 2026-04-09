"""Backward compatibility shim — use exit_engine.py directly.

All public names that previously lived here are re-exported from
``app.domain.fabio_ai.services.exit_engine``.

Do NOT add new logic to this file.  Update callers to import from
``exit_engine`` instead.
"""

from __future__ import annotations

from app.domain.fabio_ai.services.exit_engine import (  # noqa: F401
    CushionState,
    ExitDecision,
    ExitEngine,
    ExitEngine as TradeManager,
    ExitReason,
    ExitSignal,
    MarketStateCodec,
    TIME_STOP_TABLE,
    EXPIRY_TIME_STOP,
    TradeManagerConfig,
)
