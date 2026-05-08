"""Centralized consecutive loss tracking — single source of truth.

This module provides the canonical implementation of consecutive loss
tracking for the entire trading system. All services that need to query
or update loss counters should use this service instead of maintaining
their own counters.

Usage:
    tracker = ConsecutiveLossTracker()
    tracker.record_loss("NIFTY")
    count = tracker.get_consecutive_losses("NIFTY")
    if count >= 3:
        # Circuit breaker triggered
        pass
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class LossCounterState:
    """Snapshot of loss counter state for a symbol."""

    symbol: str
    consecutive_losses: int
    daily_losses: int
    total_trades: int
    last_loss_time: float | None = None
    last_stop_price: float = 0.0


class ConsecutiveLossTracker:
    """Single source of truth for consecutive loss tracking.

    Thread-safe tracker that maintains:
    - Per-symbol consecutive loss counters
    - Per-symbol daily loss counters
    - Global daily loss counter
    - Automatic daily reset at midnight IST

    All circuit breakers and risk services should query this tracker
    instead of maintaining their own counters.
    """

    MAX_CONSECUTIVE_LOSSES = 3
    MAX_DAILY_LOSSES = 3

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._symbol_consecutive_losses: dict[str, int] = {}
        self._symbol_daily_losses: dict[str, int] = {}
        self._global_daily_losses: int = 0
        self._symbol_last_stop_price: dict[str, float] = {}
        self._symbol_last_loss_time: dict[str, float] = {}
        self._trade_date: date = datetime.now(IST).date()

    def _maybe_reset_daily(self) -> None:
        """Reset counters if trading day has changed."""
        today = datetime.now(IST).date()
        if today != self._trade_date:
            logger.info(
                "ConsecutiveLossTracker: daily reset (global_losses=%d)",
                self._global_daily_losses,
            )
            self._symbol_consecutive_losses.clear()
            self._symbol_daily_losses.clear()
            self._global_daily_losses = 0
            self._symbol_last_stop_price.clear()
            self._symbol_last_loss_time.clear()
            self._trade_date = today

    def record_loss(self, symbol: str, stop_price: float = 0.0, timestamp: float = 0.0) -> None:
        """Record a losing trade for the given symbol.

        Args:
            symbol: Trading symbol.
            stop_price: Stop loss price that was hit (optional).
            timestamp: Time of the loss (defaults to current time).
        """
        import time

        with self._lock:
            self._maybe_reset_daily()

            self._symbol_consecutive_losses[symbol] = (
                self._symbol_consecutive_losses.get(symbol, 0) + 1
            )
            self._symbol_daily_losses[symbol] = (
                self._symbol_daily_losses.get(symbol, 0) + 1
            )
            self._global_daily_losses += 1

            if stop_price > 0:
                self._symbol_last_stop_price[symbol] = stop_price
            if timestamp > 0:
                self._symbol_last_loss_time[symbol] = timestamp
            else:
                self._symbol_last_loss_time[symbol] = time.time()

            logger.info(
                "ConsecutiveLossTracker: %s loss recorded (consecutive=%d, daily=%d)",
                symbol,
                self._symbol_consecutive_losses[symbol],
                self._symbol_daily_losses[symbol],
            )

    def record_win(self, symbol: str) -> None:
        """Record a winning trade, resetting consecutive losses for the symbol.

        Args:
            symbol: Trading symbol.
        """
        with self._lock:
            self._maybe_reset_daily()
            if symbol in self._symbol_consecutive_losses:
                self._symbol_consecutive_losses[symbol] = 0
                logger.debug("ConsecutiveLossTracker: %s consecutive losses reset on win", symbol)

    def get_consecutive_losses(self, symbol: str) -> int:
        """Get consecutive loss count for a symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            Number of consecutive losses.
        """
        with self._lock:
            self._maybe_reset_daily()
            return self._symbol_consecutive_losses.get(symbol, 0)

    def get_daily_losses(self, symbol: str) -> int:
        """Get daily loss count for a symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            Number of losses today for this symbol.
        """
        with self._lock:
            self._maybe_reset_daily()
            return self._symbol_daily_losses.get(symbol, 0)

    def get_global_daily_losses(self) -> int:
        """Get total daily loss count across all symbols.

        Returns:
            Total number of losses today.
        """
        with self._lock:
            self._maybe_reset_daily()
            return self._global_daily_losses

    def is_circuit_breaker_triggered(self, symbol: str, max_losses: int | None = None) -> bool:
        """Check if circuit breaker should trigger for a symbol.

        Args:
            symbol: Trading symbol.
            max_losses: Override for max consecutive losses (defaults to class constant).

        Returns:
            True if circuit breaker should trigger.
        """
        with self._lock:
            self._maybe_reset_daily()
            limit = max_losses if max_losses is not None else self.MAX_CONSECUTIVE_LOSSES
            return self._symbol_consecutive_losses.get(symbol, 0) >= limit

    def is_daily_limit_reached(self, symbol: str, max_losses: int | None = None) -> bool:
        """Check if daily loss limit is reached for a symbol.

        Args:
            symbol: Trading symbol.
            max_losses: Override for max daily losses (defaults to class constant).

        Returns:
            True if daily limit is reached.
        """
        with self._lock:
            self._maybe_reset_daily()
            limit = max_losses if max_losses is not None else self.MAX_DAILY_LOSSES
            # Global limit is 3x the per-symbol limit
            if self._global_daily_losses >= limit * 3:
                return True
            return self._symbol_daily_losses.get(symbol, 0) >= limit

    def should_block_entry(
        self,
        symbol: str,
        current_price: float = 0.0,
        current_atr: float = 0.0,
        proximity_multiplier: float = 1.5,
    ) -> bool:
        """Check if entry should be blocked due to recent losses.

        Blocks entry if:
        - Daily limit reached, OR
        - 2+ consecutive losses AND price is within 1.5x ATR of last stop

        Args:
            symbol: Trading symbol.
            current_price: Current market price.
            current_atr: Current ATR value.
            proximity_multiplier: ATR proximity multiplier (default 1.5).

        Returns:
            True if entry should be blocked.
        """
        if self.is_daily_limit_reached(symbol):
            return True

        with self._lock:
            self._maybe_reset_daily()
            cons = self._symbol_consecutive_losses.get(symbol, 0)
            if cons >= 2 and current_price > 0 and current_atr > 0:
                last_stop = self._symbol_last_stop_price.get(symbol, 0.0)
                if last_stop > 0 and abs(current_price - last_stop) < (proximity_multiplier * current_atr):
                    logger.warning(
                        "ConsecutiveLossTracker: entry blocked for %s (distance %.2f < %.2f)",
                        symbol,
                        abs(current_price - last_stop),
                        proximity_multiplier * current_atr,
                    )
                    return True
        return False

    def get_last_stop_price(self, symbol: str) -> float:
        """Get the last stop loss price hit for a symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            Stop loss price, or 0.0 if none recorded.
        """
        with self._lock:
            return self._symbol_last_stop_price.get(symbol, 0.0)

    def get_state(self) -> dict[str, LossCounterState]:
        """Get complete state for all symbols.

        Returns:
            Dict mapping symbol to LossCounterState.
        """
        with self._lock:
            self._maybe_reset_daily()
            all_symbols = set(self._symbol_consecutive_losses.keys())
            all_symbols.update(self._symbol_daily_losses.keys())

            return {
                symbol: LossCounterState(
                    symbol=symbol,
                    consecutive_losses=self._symbol_consecutive_losses.get(symbol, 0),
                    daily_losses=self._symbol_daily_losses.get(symbol, 0),
                    total_trades=0,  # Not tracked here
                    last_loss_time=self._symbol_last_loss_time.get(symbol),
                    last_stop_price=self._symbol_last_stop_price.get(symbol, 0.0),
                )
                for symbol in all_symbols
            }

    def reset(self) -> None:
        """Reset all counters."""
        with self._lock:
            self._symbol_consecutive_losses.clear()
            self._symbol_daily_losses.clear()
            self._global_daily_losses = 0
            self._symbol_last_stop_price.clear()
            self._symbol_last_loss_time.clear()
            self._trade_date = datetime.now(IST).date()
            logger.info("ConsecutiveLossTracker: manually reset all counters")
