"""LLM overseer handler scaffold.

The v1 project has a full active-position overseer implementation.
This compatibility layer keeps the same call surface so callers can invoke
overseer checks without breaking imports while limiting side effects in v2.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

OVERSEER_COOLDOWN = 3.0


class LLMOverseerHandler:
    """Active position overseer interface used by runtime orchestration."""

    def __init__(self, *args, **kwargs):
        self._last_run: dict[str, float] = {}
        self._gen_ai_service = kwargs.get("gen_ai_service")
        self._trade_manager = kwargs.get("trade_manager")

    def should_run(
        self,
        last_overseer_time: float,
        overseer_running: bool,
        ai_running: bool,
        has_position: bool,
    ) -> bool:
        if not has_position:
            return False
        if overseer_running or ai_running:
            return False
        if self._gen_ai_service is not None and hasattr(self._gen_ai_service, "is_ready"):
            if not self._gen_ai_service.is_ready():
                return False
        return (time.time() - float(last_overseer_time)) >= OVERSEER_COOLDOWN

    def run_overseer(
        self,
        session,
        symbol: str,
        tick,
        amt_result=None,
        session_info=None,
        footprint_candle=None,
    ) -> None:
        if session is None or not symbol:
        # Guard clauses for incomplete session state.
            return

        try:
            with session._lock:
                session._last_overseer_time = time.time()
                session._overseer_running = True
        except Exception:
            pass

        self._last_run[symbol] = time.time()
        self._resolve_placeholder(session, symbol, tick)

        try:
            with session._lock:
                session._overseer_running = False
        except Exception:
            pass

    def _resolve_placeholder(self, session, symbol: str, tick) -> None:
        if not getattr(session, "_open_positions", None):
            return
        for position in getattr(session._open_positions, "values", lambda: [])():
            if getattr(position, "symbol", None) != symbol:
                continue
            if hasattr(self._trade_manager, "evaluate"):
                try:
                    self._trade_manager.evaluate(position)
                except Exception:
                    logger.debug("Overseer trade manager evaluate failed", exc_info=True)
            logger.debug("Overseer placeholder evaluated symbol=%s position=%s", symbol, position.id if hasattr(position, "id") else "?")
