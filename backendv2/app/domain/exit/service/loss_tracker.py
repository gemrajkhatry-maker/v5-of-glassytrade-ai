"""Daily loss tracking and circuit-breaker checks."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable

from app.domain.shared.port.storage import IKeyValueStorage

logger = logging.getLogger(__name__)


def _make_storage_adapter(
    persist_fn: Callable[[str, str | None], str | None],
) -> IKeyValueStorage:
    class _PersistFnAdapter:
        def __init__(self, fn):
            self._fn = fn

        def persist(self, key: str, value: str | None) -> None:
            self._fn(key, value)

        def load(self, key: str) -> str | None:
            return self._fn(key, None)

    return _PersistFnAdapter(persist_fn)


class LossTracker:
    """Tracks daily loss counts and consecutive losses."""

    MAX_DAILY_LOSSES = 3

    def __init__(
        self,
        storage: IKeyValueStorage | None = None,
        persist_fn: Callable[[str, str | None], str | None] | None = None,
        max_daily_losses: int = 3,
    ):
        self._lock = threading.RLock()
        if storage is not None:
            self._storage = storage
        elif persist_fn is not None:
            self._storage = _make_storage_adapter(persist_fn)
        else:
            self._storage = None

        self._max_daily_losses = max_daily_losses
        self._global_daily_losses = 0
        self._symbol_daily_losses: dict[str, int] = {}
        self._symbol_consecutive_losses: dict[str, int] = {}
        self._symbol_last_stop_price: dict[str, float] = {}
        self._session_realized_pnl = 0.0
        self._session_high_water_mark = 0.0
        self._session_circuit = -30000.0
        self._session_target = 15000.0
        self._last_exit_time: dict[str, float] = {}
        self._daily_loss_reset_time = self._next_midnight()
        self._load_daily_losses()

    @staticmethod
    def _next_midnight() -> float:
        now = datetime.now()
        nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return nxt.timestamp()

    def _load_daily_losses(self) -> None:
        if not self._storage:
            return
        raw = self._storage.load("daily_losses_v2")
        if not raw:
            return
        try:
            payload = json.loads(raw)
            if payload.get("date") == datetime.now().strftime("%Y-%m-%d"):
                self._global_daily_losses = payload.get("global_count", 0)
                self._symbol_daily_losses = payload.get("symbol_counts", {})
                logger.info(
                    "LossTracker restored: global=%d symbols=%s",
                    self._global_daily_losses,
                    self._symbol_daily_losses,
                )
        except Exception:
            logger.debug("LossTracker: failed to restore state", exc_info=True)

    def _save_daily_losses(self) -> None:
        if not self._storage:
            return
        try:
            payload = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "global_count": self._global_daily_losses,
                "symbol_counts": self._symbol_daily_losses,
            }
            self._storage.persist("daily_losses_v2", json.dumps(payload))
        except Exception:
            logger.debug("LossTracker: failed to persist state", exc_info=True)

    def _maybe_reset_daily(self) -> None:
        if time.time() >= self._daily_loss_reset_time:
            self._global_daily_losses = 0
            self._symbol_daily_losses = {}
            self._symbol_consecutive_losses = {}
            self._symbol_last_stop_price = {}
            self._daily_loss_reset_time = self._next_midnight()
            self._save_daily_losses()

    def record_loss(self, symbol: str, stop_price: float = 0.0) -> None:
        with self._lock:
            self._maybe_reset_daily()
            self._global_daily_losses += 1
            self._symbol_daily_losses[symbol] = self._symbol_daily_losses.get(symbol, 0) + 1
            self._symbol_consecutive_losses[symbol] = self._symbol_consecutive_losses.get(symbol, 0) + 1
            if stop_price > 0:
                self._symbol_last_stop_price[symbol] = float(stop_price)
            self._save_daily_losses()

    def record_win(self, symbol: str) -> None:
        with self._lock:
            self._maybe_reset_daily()
            if symbol in self._symbol_consecutive_losses:
                self._symbol_consecutive_losses[symbol] = 0

    def reset_consecutive_losses(self, symbol: str) -> None:
        with self._lock:
            self._symbol_consecutive_losses[symbol] = 0

    def record_exit_time(self, symbol: str, current_time: float | None = None) -> None:
        with self._lock:
            self._last_exit_time[symbol] = current_time if current_time is not None else time.time()

    def in_cooldown(self, symbol: str, current_time: float | None = None, cooldown_seconds: float = 30.0) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.time()
            last_exit = self._last_exit_time.get(symbol, 0.0)
            if last_exit <= 0.0:
                return False
            return (now - last_exit) < cooldown_seconds

    def is_daily_limit_reached(self, symbol: str, max_daily_losses: int | None = None) -> bool:
        with self._lock:
            self._maybe_reset_daily()
            max_losses = max_daily_losses if max_daily_losses is not None else self._max_daily_losses
            if self._global_daily_losses >= max_losses * 3:
                return True
            return self._symbol_daily_losses.get(symbol, 0) >= max_losses

    def is_daily_limit_reached_with_override(self, symbol: str, max_daily_losses: int) -> bool:
        with self._lock:
            self._maybe_reset_daily()
            if self._global_daily_losses >= max_daily_losses * 3:
                return True
            return self._symbol_daily_losses.get(symbol, 0) >= max_daily_losses

    def should_block_entry(self, symbol: str, current_price: float = 0.0, current_atr: float = 0.0) -> bool:
        if self.is_daily_limit_reached(symbol):
            return True
        with self._lock:
            cons = self._symbol_consecutive_losses.get(symbol, 0)
            if cons >= 2 and current_price > 0 and current_atr > 0:
                last_stop = self._symbol_last_stop_price.get(symbol, 0.0)
                if last_stop > 0 and abs(current_price - last_stop) < (1.5 * current_atr):
                    return True
        return False

    def should_block_entry_with_override(
        self,
        symbol: str,
        current_price: float = 0.0,
        current_atr: float = 0.0,
        max_daily_losses: int = 3,
    ) -> bool:
        if self.is_daily_limit_reached_with_override(symbol, max_daily_losses=max_daily_losses):
            return True
        with self._lock:
            cons = self._symbol_consecutive_losses.get(symbol, 0)
            if cons >= 2 and current_price > 0 and current_atr > 0:
                last_stop = self._symbol_last_stop_price.get(symbol, 0.0)
                if last_stop > 0 and abs(current_price - last_stop) < (1.5 * current_atr):
                    logger.warning(
                        "LossTracker: consecutive-loss circuit active for %s (distance %.2f < %.2f)",
                        symbol,
                        abs(current_price - last_stop),
                        1.5 * current_atr,
                    )
                    return True
        return False

    def get_state(self) -> dict:
        with self._lock:
            self._maybe_reset_daily()
            return {
                "global_daily_losses": self._global_daily_losses,
                "symbol_daily_losses": dict(self._symbol_daily_losses),
                "symbol_consecutive_losses": dict(self._symbol_consecutive_losses),
                "session_realized_pnl": self._session_realized_pnl,
                "session_status": self.get_session_status(),
            }

    def add_session_pnl(self, pnl: float) -> None:
        logger.debug("LossTracker: add_session_pnl is deprecated; use add_realized_pnl")
        self.add_realized_pnl(pnl)

    def add_realized_pnl(self, realized_pnl: float) -> None:
        with self._lock:
            self._session_realized_pnl += float(realized_pnl)
            self._session_high_water_mark = max(self._session_high_water_mark, self._session_realized_pnl)
            logger.debug(
                "LossTracker: realized pnl updated by %.2f -> %.2f",
                realized_pnl,
                self._session_realized_pnl,
            )

    def get_session_realized_pnl(self) -> float:
        with self._lock:
            return self._session_realized_pnl

    def is_session_circuit_hit(self) -> bool:
        with self._lock:
            return self._session_realized_pnl <= self._session_circuit

    def is_session_target_hit(self) -> bool:
        with self._lock:
            return self._session_realized_pnl >= self._session_target

    def get_session_status(self) -> str:
        with self._lock:
            if self._session_realized_pnl >= self._session_target:
                return "TARGET_HIT"
            if self._session_realized_pnl <= self._session_circuit:
                return "CIRCUIT_HIT"
            return "ACTIVE"

    def reset_daily_losses(self) -> None:
        with self._lock:
            self._global_daily_losses = 0
            self._symbol_daily_losses = {}
            self._symbol_consecutive_losses = {}
            self._symbol_last_stop_price = {}
            self._daily_loss_reset_time = self._next_midnight()
            self._save_daily_losses()

            logger.info("LossTracker: daily losses manually reset")
