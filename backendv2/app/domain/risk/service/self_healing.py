"""Self-healing resilience mechanisms for execution/runtime fault handling."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

logger = logging.getLogger(__name__)


class OrderRejectionAction(str, Enum):
    RETRY = "RETRY"
    ALERT = "ALERT"
    SKIP = "SKIP"


def _execute_sync(factory):
    """Execute a sync/async callable result in a sync context."""
    result = factory()
    if not inspect.isawaitable(result):
        return result

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(result)

    if not loop.is_running():
        return loop.run_until_complete(result)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return list(executor.map(lambda awaitable: asyncio.run(awaitable), [result]))[0]


@dataclass
class OrderRejectionHandler:
    """Handles broker order rejections with bounded retry logic.

    Rules:
      - Entry rejection: do not retry (signal may be stale)
      - SL rejection: retry once after short wait
      - Exit rejection: retry up to 3 times, then escalate
    """

    _sl_retry_count: dict[str, int] = field(default_factory=dict)
    _exit_retry_count: dict[str, int] = field(default_factory=dict)
    _max_sl_retries: int = 1
    _max_exit_retries: int = 3

    def handle_entry_rejection(self, order_id: str, reason: str) -> OrderRejectionAction:
        """Handle entry order rejection."""
        logger.warning(
            "Entry order rejected (%s): %s — not retrying (signal may be stale)",
            order_id,
            reason,
        )
        return OrderRejectionAction.SKIP

    def handle_sl_rejection(self, order_id: str, reason: str) -> OrderRejectionAction:
        """Handle stop-loss related rejection."""
        retries = self._sl_retry_count.get(order_id, 0)
        if retries < self._max_sl_retries:
            self._sl_retry_count[order_id] = retries + 1
            logger.warning(
                "SL order rejected (%s): %s — retrying (attempt %d/%d)",
                order_id,
                reason,
                retries + 1,
                self._max_sl_retries,
            )
            return OrderRejectionAction.RETRY
        logger.critical(
            "SL order rejected (%s): %s — max retries reached — ALERT",
            order_id,
            reason,
        )
        return OrderRejectionAction.ALERT

    def handle_exit_rejection(self, order_id: str, reason: str) -> OrderRejectionAction:
        """Handle exit order rejection."""
        retries = self._exit_retry_count.get(order_id, 0)
        if retries < self._max_exit_retries:
            self._exit_retry_count[order_id] = retries + 1
            logger.warning(
                "Exit order rejected (%s): %s — retrying (attempt %d/%d)",
                order_id,
                reason,
                retries + 1,
                self._max_exit_retries,
            )
            return OrderRejectionAction.RETRY
        logger.critical(
            "Exit order rejected (%s): %s — max retries reached — ALERT + manual",
            order_id,
            reason,
        )
        return OrderRejectionAction.ALERT

    def reset(self) -> None:
        self._sl_retry_count.clear()
        self._exit_retry_count.clear()


@dataclass
class DBFallbackBuffer:
    """In-memory fallback for storage writes when DB is unavailable."""

    _buffer: deque = field(default_factory=lambda: deque(maxlen=10000))
    _write_failures: int = 0
    _flush_attempts: int = 0
    _flush_successes: int = 0

    def buffer_write(self, key: str, data: dict) -> None:
        """Queue failed write data for later flush."""
        self._buffer.append({"key": key, "data": data, "time": time.time()})
        self._write_failures += 1

    def try_flush(self, storage) -> int:
        """Attempt to flush queued writes to storage."""
        self._flush_attempts += 1
        flushed = 0
        remaining = []

        while self._buffer:
            item = self._buffer.popleft()
            try:
                if item["key"] == "save_trade":
                    _execute_sync(lambda: storage.save_trade(item["data"]))
                elif item["key"] == "save_tick":
                    _execute_sync(
                        lambda: storage.save_tick(
                            item["data"].get("symbol", ""),
                            item["data"],
                        )
                    )
                elif item["key"] == "save_performance_snapshot":
                    _execute_sync(lambda: storage.save_performance_snapshot(item["data"]))
                else:
                    logger.debug("Unknown fallback write key ignored: %s", item["key"])
                    continue
                flushed += 1
                self._flush_successes += 1
            except (KeyError, TypeError, AttributeError):
                remaining.append(item)
                break

        for item in remaining:
            self._buffer.appendleft(item)
        return flushed

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    def get_stats(self) -> dict:
        return {
            "buffer_size": self.buffer_size,
            "write_failures": self._write_failures,
            "flush_attempts": self._flush_attempts,
            "flush_successes": self._flush_successes,
        }


class LLMTimeoutRecovery:
    """Tracks LLM timeout streaks and disables a symbol on repeated timeouts."""

    def __init__(self, max_consecutive_timeouts: int = 5) -> None:
        self._max_timeouts = max_consecutive_timeouts
        self._consecutive_timeouts: dict[str, int] = {}
        self._disabled_symbols: set[str] = set()

    def record_timeout(self, symbol: str) -> bool:
        """Record timeout and return true when LLM should be disabled."""
        count = self._consecutive_timeouts.get(symbol, 0) + 1
        self._consecutive_timeouts[symbol] = count

        if count >= self._max_timeouts:
            self._disabled_symbols.add(symbol)
            logger.warning(
                "LLM disabled for %s after %d consecutive timeouts.",
                symbol,
                count,
            )
            return True
        return False

    def record_success(self, symbol: str) -> None:
        """Reset counter when model call succeeds."""
        self._consecutive_timeouts[symbol] = 0
        if symbol in self._disabled_symbols:
            self._disabled_symbols.discard(symbol)
            logger.info("LLM re-enabled for %s", symbol)

    def is_disabled(self, symbol: str) -> bool:
        """Whether LLM processing is currently disabled for symbol."""
        return symbol in self._disabled_symbols

    def get_status(self) -> dict:
        return {
            "disabled_symbols": list(self._disabled_symbols),
            "consecutive_timeouts": dict(self._consecutive_timeouts),
        }
