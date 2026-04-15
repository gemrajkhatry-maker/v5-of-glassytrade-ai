"""Daily loss tracking and circuit breaker state.

This module tracks daily losses per symbol and globally, and implements
circuit breaker logic to prevent over-trading after losses.

Key features:
- Daily loss counting (global and per-symbol)
- Consecutive loss tracking for circuit breakers
- ATR-based re-entry distance checks
- Persistence via IKeyValueStorage (DIP-compliant)
- Automatic daily reset at IST midnight
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from app.domain.ports.storage import IKeyValueStorage
from app.shared.timezones import IST

logger = logging.getLogger(__name__)


def _make_storage_adapter(persist_fn: Callable[[str, str | None], str | None]) -> IKeyValueStorage:
    """Create a IKeyValueStorage adapter from legacy persist_fn callback.

    The legacy persist_fn is dual-purpose:
    - persist_fn(key, value) stores the value
    - persist_fn(key, None) returns the stored value

    This adapter provides the cleaner IKeyValueStorage interface.
    """
    class _PersistFnAdapter:
        def __init__(self, fn: Callable[[str, str | None], str | None]):
            self._fn = fn

        def persist(self, key: str, value: str | None) -> None:
            self._fn(key, value)

        def load(self, key: str) -> str | None:
            return self._fn(key, None)

    return _PersistFnAdapter(persist_fn)


class LossTracker:
    """Tracks daily losses and consecutive losses for circuit breaking.

    This class manages:
    - Global daily loss count (circuit breaker at MAX_DAILY_LOSSES * 3)
    - Per-symbol daily loss count (circuit breaker at MAX_DAILY_LOSSES)
    - Per-symbol consecutive loss count (circuit breaker at 2+ losses with ATR proximity)
    - Last stop price per symbol (for ATR distance check)
    - Session realized PnL (for cushion system)

    Thread-safe via RLock.

    Dependency Injection:
        Prefer `storage` parameter (IKeyValueStorage) for DIP compliance.
        The `persist_fn` parameter is deprecated but supported for backward compatibility.
    """

    MAX_DAILY_LOSSES = 3  # Per Fabio's AMT strategy

    def __init__(
        self,
        storage: IKeyValueStorage | None = None,
        persist_fn: Callable[[str, str | None], str | None] | None = None,
        max_daily_losses: int = 3,
    ):
        """Initialize loss tracker.

        Args:
            storage: IKeyValueStorage for persistence (preferred, DIP-compliant).
            persist_fn: Legacy callback for persistence (deprecated). Called as:
                        persist_fn(key: str, value: str | None) -> str | None
                        Pass value to store, None to load. Returns stored value on load.
                        Use `storage` parameter instead for type safety.
            max_daily_losses: Max losses per symbol before blocking.
        """
        self._lock = threading.RLock()

        # Handle backward compatibility: if persist_fn is provided without storage,
        # create an adapter
        if storage is not None:
            self._storage = storage
        elif persist_fn is not None:
            self._storage = _make_storage_adapter(persist_fn)
            # Keep reference for backward compat with tests that check _persist_fn
            self._persist_fn = persist_fn
        else:
            self._storage = None

        self._max_daily_losses = max_daily_losses

        # Daily loss tracking
        self._global_daily_losses: int = 0
        self._symbol_daily_losses: dict[str, int] = {}
        self._symbol_consecutive_losses: dict[str, int] = {}
        self._symbol_last_stop_price: dict[str, float] = {}

        # Session PnL tracking
        self._session_realized_pnl: float = 0.0

        # Cooldown tracking per symbol (session-level)
        self._last_exit_time: dict[str, float] = {}

        # Daily reset time
        self._daily_loss_reset_time: float = self._next_ist_midnight()

        # Load persisted state
        self._load_daily_losses()

    # -----------------------------------------------------------------------
    # Daily Reset Logic
    # -----------------------------------------------------------------------

    @staticmethod
    def _next_ist_midnight() -> float:
        """Calculate the next IST midnight timestamp."""
        now = datetime.now(IST)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return tomorrow.timestamp()

    def _load_daily_losses(self) -> None:
        """Load daily losses from persistence."""
        if not self._storage:
            return
        try:
            raw = self._storage.load("daily_losses_v2")
            if raw:
                data = json.loads(raw)
                today = datetime.now(IST).strftime("%Y-%m-%d")
                if data.get("date") == today:
                    self._global_daily_losses = data.get("global_count", 0)
                    self._symbol_daily_losses = data.get("symbol_counts", {})
                    logger.info(
                        "LossTracker: Restored daily losses from DB: global=%d, symbols=%s",
                        self._global_daily_losses,
                        self._symbol_daily_losses,
                    )
        except Exception:
            logger.debug("Failed to load daily losses from DB", exc_info=True)

    def _save_daily_losses(self) -> None:
        """Persist daily losses to storage."""
        if not self._storage:
            return
        try:
            today = datetime.now(IST).strftime("%Y-%m-%d")
            payload = {
                "date": today,
                "global_count": self._global_daily_losses,
                "symbol_counts": self._symbol_daily_losses,
            }
            self._storage.persist("daily_losses_v2", json.dumps(payload))
        except Exception:
            logger.debug("Failed to persist daily losses", exc_info=True)

    def _maybe_reset_daily(self) -> None:
        """Reset daily counts if we've crossed IST midnight."""
        if time.time() >= self._daily_loss_reset_time:
            self._global_daily_losses = 0
            self._symbol_daily_losses = {}
            self._symbol_consecutive_losses = {}
            self._symbol_last_stop_price = {}
            self._daily_loss_reset_time = self._next_ist_midnight()
            self._save_daily_losses()
            logger.info("LossTracker: Daily losses reset at IST midnight")

    # -----------------------------------------------------------------------
    # Loss Recording
    # -----------------------------------------------------------------------

    def record_loss(self, symbol: str, stop_price: float = 0.0) -> None:
        """Record a loss for the given symbol.

        Increments both global and symbol-specific daily loss counters,
        as well as consecutive loss counter.

        Args:
            symbol: Trading symbol.
            stop_price: Stop price where loss occurred (for ATR distance check).
        """
        with self._lock:
            self._maybe_reset_daily()
            self._global_daily_losses += 1
            self._symbol_daily_losses[symbol] = self._symbol_daily_losses.get(symbol, 0) + 1
            self._symbol_consecutive_losses[symbol] = (
                self._symbol_consecutive_losses.get(symbol, 0) + 1
            )
            if stop_price > 0:
                self._symbol_last_stop_price[symbol] = stop_price

            logger.info(
                "LossTracker: daily losses - global=%d/%d, %s=%d/%d",
                self._global_daily_losses,
                self._max_daily_losses * 3,
                symbol,
                self._symbol_daily_losses[symbol],
                self._max_daily_losses,
            )
            self._save_daily_losses()

    def record_win(self, symbol: str) -> None:
        """Record a win for the given symbol.

        Resets the consecutive loss counter but not the daily loss counter.

        Args:
            symbol: Trading symbol.
        """
        with self._lock:
            self._maybe_reset_daily()
            if symbol in self._symbol_consecutive_losses:
                self._symbol_consecutive_losses[symbol] = 0
            logger.debug("LossTracker: Win recorded for %s, consecutive losses reset", symbol)

    # -----------------------------------------------------------------------
    # Circuit Breaker Checks
    # -----------------------------------------------------------------------

    def is_daily_limit_reached(self, symbol: str) -> bool:
        """Check if daily loss limit is reached.

        Returns True if either:
        - Global daily losses >= MAX_DAILY_LOSSES * 3 (global circuit breaker)
        - Symbol daily losses >= MAX_DAILY_LOSSES (symbol circuit breaker)

        Args:
            symbol: Trading symbol to check.

        Returns:
            True if limit reached, False otherwise.
        """
        with self._lock:
            self._maybe_reset_daily()
            if self._global_daily_losses >= (self._max_daily_losses * 3):
                return True
            return self._symbol_daily_losses.get(symbol, 0) >= self._max_daily_losses

    def is_daily_limit_reached_with_override(
        self, symbol: str, max_daily_losses: int
    ) -> bool:
        """Check if daily loss limit is reached with override for max_daily_losses.

        This method allows the caller to override the max_daily_losses value,
        which is useful when tests modify ExitEngine.MAX_DAILY_LOSSES at runtime.

        Args:
            symbol: Trading symbol to check.
            max_daily_losses: Override for max daily losses per symbol.

        Returns:
            True if limit reached, False otherwise.
        """
        with self._lock:
            self._maybe_reset_daily()
            if self._global_daily_losses >= (max_daily_losses * 3):
                return True
            return self._symbol_daily_losses.get(symbol, 0) >= max_daily_losses

    def should_block_entry(
        self,
        symbol: str,
        current_price: float = 0.0,
        current_atr: float = 0.0,
    ) -> bool:
        """Check if entry should be blocked due to circuit breakers.

        Blocks if:
        1. Daily loss limit reached (see is_daily_limit_reached)
        2. 2+ consecutive losses AND current price is within 1.5 ATR of last stop

        Args:
            symbol: Trading symbol to check.
            current_price: Current market price (for ATR distance check).
            current_atr: Current ATR value (for distance calculation).

        Returns:
            True if entry should be blocked, False otherwise.
        """
        if self.is_daily_limit_reached(symbol):
            return True

        with self._lock:
            cons_losses = self._symbol_consecutive_losses.get(symbol, 0)
            if cons_losses >= 2 and current_price > 0 and current_atr > 0:
                last_price = self._symbol_last_stop_price.get(symbol, 0.0)
                if last_price > 0:
                    distance = abs(current_price - last_price)
                    if distance < (1.5 * current_atr):
                        logger.warning(
                            f"LossTracker: Circuit Breaker ACTIVE for {symbol}. "
                            f"Distance from last stop ({distance:.1f}) < required buffer ({1.5 * current_atr:.1f})."
                        )
                        return True
        return False

    def should_block_entry_with_override(
        self,
        symbol: str,
        current_price: float = 0.0,
        current_atr: float = 0.0,
        max_daily_losses: int = 3,
    ) -> bool:
        """Check if entry should be blocked with override for max_daily_losses.

        This method allows the caller to override the max_daily_losses value,
        which is useful when tests modify ExitEngine.MAX_DAILY_LOSSES at runtime.

        Args:
            symbol: Trading symbol to check.
            current_price: Current market price (for ATR distance check).
            current_atr: Current ATR value (for distance calculation).
            max_daily_losses: Override for max daily losses per symbol.

        Returns:
            True if entry should be blocked, False otherwise.
        """
        if self.is_daily_limit_reached_with_override(symbol, max_daily_losses):
            return True

        with self._lock:
            cons_losses = self._symbol_consecutive_losses.get(symbol, 0)
            if cons_losses >= 2 and current_price > 0 and current_atr > 0:
                last_price = self._symbol_last_stop_price.get(symbol, 0.0)
                if last_price > 0:
                    distance = abs(current_price - last_price)
                    if distance < (1.5 * current_atr):
                        logger.warning(
                            f"LossTracker: Circuit Breaker ACTIVE for {symbol}. "
                            f"Distance from last stop ({distance:.1f}) < required buffer ({1.5 * current_atr:.1f})."
                        )
                        return True
        return False

    def reset_consecutive_losses(self, symbol: str) -> None:
        """Reset consecutive loss counter for a symbol.

        Called after a winning trade.

        Args:
            symbol: Trading symbol.
        """
        with self._lock:
            if symbol in self._symbol_consecutive_losses:
                self._symbol_consecutive_losses[symbol] = 0

    # -----------------------------------------------------------------------
    # Session PnL Tracking
    # -----------------------------------------------------------------------

    def add_realized_pnl(self, realized_pnl: float) -> None:
        """Add to session realized PnL.

        Args:
            realized_pnl: PnL to add (positive or negative).
        """
        with self._lock:
            self._session_realized_pnl += realized_pnl
            logger.info(
                f"LossTracker: realized PnL added: {realized_pnl:.2f}. Session total: {self._session_realized_pnl:.2f}"
            )

    def get_session_realized_pnl(self) -> float:
        """Get current session realized PnL.

        Returns:
            Session realized PnL total.
        """
        with self._lock:
            return self._session_realized_pnl

    def compute_dynamic_risk(
        self,
        base_capital: float,
        session_realized_pnl: float | None = None,
    ) -> tuple[float, str]:
        """Compute dynamic risk percentage based on cushion system.

        ``session_realized_pnl`` overrides the internal tracker when provided,
        making the method usable as a pure function without instance state.

        Args:
            base_capital: Base capital amount.
            session_realized_pnl: Optional override for session PnL.

        Returns:
            Tuple of (risk_percentage, risk_mode_string).
        """
        if session_realized_pnl is not None:
            pnl = session_realized_pnl
        else:
            with self._lock:
                pnl = self._session_realized_pnl

        if pnl <= 0:
            return 0.0025, "Conservative"

        cushion_risk_amount = (base_capital * 0.0035) + (pnl * 0.20)
        risk_pct = cushion_risk_amount / base_capital
        max_allowed_from_profit = (base_capital * 0.0025) + (pnl * 0.30)
        max_allowed_pct = min(0.0050, max_allowed_from_profit / base_capital)
        final_risk_pct = min(risk_pct, max_allowed_pct)

        if final_risk_pct >= 0.0040:
            return final_risk_pct, "Momentum (Aggressive)"
        return final_risk_pct, "Cushion Built (Scaling)"

    # -----------------------------------------------------------------------
    # Cooldown Tracking
    # -----------------------------------------------------------------------

    def in_cooldown(
        self,
        symbol: str,
        current_time: float | None = None,
        cooldown_seconds: float = 30.0,
    ) -> bool:
        """Check if symbol is in cooldown period after exit.

        Args:
            symbol: Trading symbol to check.
            current_time: Current time (defaults to time.time()).
            cooldown_seconds: Cooldown duration in seconds.

        Returns:
            True if in cooldown, False otherwise.
        """
        with self._lock:
            last_exit = self._last_exit_time.get(symbol, 0.0)
            if last_exit == 0.0:
                return False
            now = current_time if current_time is not None else time.time()
            return (now - last_exit) < cooldown_seconds

    def record_exit_time(
        self,
        symbol: str,
        current_time: float | None = None,
    ) -> None:
        """Record the time of an exit for cooldown tracking.

        Args:
            symbol: Trading symbol.
            current_time: Exit time (defaults to time.time()).
        """
        with self._lock:
            self._last_exit_time[symbol] = current_time if current_time is not None else time.time()

    # -----------------------------------------------------------------------
    # State Access
    # -----------------------------------------------------------------------

    def get_state(self) -> dict:
        """Get current loss tracking state for debugging/logging.

        Returns:
            Dict with all tracking state.
        """
        with self._lock:
            return {
                "global_daily_losses": self._global_daily_losses,
                "symbol_daily_losses": dict(self._symbol_daily_losses),
                "symbol_consecutive_losses": dict(self._symbol_consecutive_losses),
                "symbol_last_stop_price": dict(self._symbol_last_stop_price),
                "session_realized_pnl": self._session_realized_pnl,
                "daily_loss_reset_time": self._daily_loss_reset_time,
            }

    def reset_daily_losses(self) -> None:
        """Manually reset all daily loss counters.

        Called during session start or manual intervention.
        """
        with self._lock:
            self._global_daily_losses = 0
            self._symbol_daily_losses = {}
            self._symbol_consecutive_losses = {}
            self._symbol_last_stop_price = {}
            self._save_daily_losses()
            logger.info("LossTracker: Daily losses manually reset")
