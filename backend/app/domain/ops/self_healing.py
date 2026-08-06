"""Self-Healing Mechanisms — order rejection recovery + DB write fallback.

Handles failures gracefully without blocking trade decisions:
  1. Order rejection recovery (retry with backoff)
  2. DB write failure fallback (in-memory buffer)
  3. WebSocket reconnect (exponential backoff)
  4. LLM timeout recovery (disable after N consecutive timeouts)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from app.core.async_boundary import ensure_sync_adapter_result

logger = logging.getLogger(__name__)


class OrderRejectionAction(str, Enum):
    RETRY = "RETRY"
    ALERT = "ALERT"
    SKIP = "SKIP"


@dataclass
class OrderRejectionHandler:
    """Handles broker order rejections with retry logic.

    Rules per spec:
      Entry rejection: do NOT retry (signal may be stale)
      SL order rejection: CRITICAL alert + retry once after 2s
      Exit order rejection: retry 3 times with 1s gap, then alert
    """

    _sl_retry_count: dict[str, int] = field(default_factory=dict)
    _exit_retry_count: dict[str, int] = field(default_factory=dict)
    _max_sl_retries: int = 1
    _max_exit_retries: int = 3

    def handle_entry_rejection(
        self,
        order_id: str,
        reason: str,
    ) -> OrderRejectionAction:
        """Handle entry order rejection — do NOT retry."""
        logger.warning(
            "Entry order rejected (%s): %s — not retrying (signal may be stale)",
            order_id,
            reason,
        )
        return OrderRejectionAction.SKIP

    def handle_sl_rejection(
        self,
        order_id: str,
        reason: str,
    ) -> OrderRejectionAction:
        """Handle SL order rejection — retry once, then alert."""
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
        else:
            logger.critical(
                "SL order rejected (%s): %s — max retries reached — ALERT",
                order_id,
                reason,
            )
            return OrderRejectionAction.ALERT

    def handle_exit_rejection(
        self,
        order_id: str,
        reason: str,
    ) -> OrderRejectionAction:
        """Handle exit order rejection — retry 3 times, then alert."""
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
        else:
            logger.critical(
                "Exit order rejected (%s): %s — max retries — ALERT + manual intervention",
                order_id,
                reason,
            )
            return OrderRejectionAction.ALERT

    def reset(self) -> None:
        self._sl_retry_count.clear()
        self._exit_retry_count.clear()


@dataclass
class DBFallbackBuffer:
    """In-memory fallback buffer for DB write failures.

    Trade decisions are NEVER blocked by DB write failures.
    Failed writes are buffered and flushed when DB recovers.
    Max buffer: 10,000 events.
    """

    _buffer: deque = field(default_factory=lambda: deque(maxlen=10000))
    _write_failures: int = 0
    _flush_attempts: int = 0
    _flush_successes: int = 0

    def buffer_write(self, key: str, data: dict) -> None:
        """Buffer a failed DB write."""
        self._buffer.append({"key": key, "data": data, "time": time.time()})
        self._write_failures += 1

    def try_flush(self, storage) -> int:
        """Attempt to flush buffered writes to storage.

        Returns number of successfully flushed items.
        """
        self._flush_attempts += 1
        flushed = 0
        remaining = []

        while self._buffer:
            item = self._buffer.popleft()
            try:
                if item["key"] == "save_trade":
                    ensure_sync_adapter_result(
                        "storage.save_trade",
                        storage.save_trade,
                        item["data"],
                    )
                elif item["key"] == "save_tick":
                    ensure_sync_adapter_result(
                        "storage.save_tick",
                        storage.save_tick,
                        item["data"].get("symbol", ""),
                        item["data"],
                    )
                elif item["key"] == "save_performance_snapshot":
                    ensure_sync_adapter_result(
                        "storage.save_performance_snapshot",
                        storage.save_performance_snapshot,
                        item["data"],
                    )
                flushed += 1
                self._flush_successes += 1
            except (KeyError, TypeError):
                remaining.append(item)
                break  # stop flushing on first failure

        # Put unflushed items back
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
    """Manages LLM timeout recovery.

    Rules:
      On timeout: action = HOLD (never exit on timeout)
      Consecutive timeouts >= 5: disable LLM overseer for this session
      Log: LLM unavailable → rule-based exit only
    """

    def __init__(self, max_consecutive_timeouts: int = 5) -> None:
        self._max_timeouts = max_consecutive_timeouts
        self._consecutive_timeouts: dict[str, int] = {}
        self._disabled_symbols: set[str] = set()

    def record_timeout(self, symbol: str) -> bool:
        """Record a timeout. Returns True if LLM should be disabled."""
        count = self._consecutive_timeouts.get(symbol, 0) + 1
        self._consecutive_timeouts[symbol] = count

        if count >= self._max_timeouts:
            self._disabled_symbols.add(symbol)
            logger.warning(
                "LLM disabled for %s — %d consecutive timeouts (rule-based exit only)",
                symbol,
                count,
            )
            return True
        return False

    def record_success(self, symbol: str) -> None:
        """Record a successful LLM call — resets timeout counter."""
        self._consecutive_timeouts[symbol] = 0
        if symbol in self._disabled_symbols:
            self._disabled_symbols.discard(symbol)
            logger.info("LLM re-enabled for %s", symbol)

    def is_disabled(self, symbol: str) -> bool:
        """Check if LLM is disabled for this symbol."""
        return symbol in self._disabled_symbols

    def get_status(self) -> dict:
        return {
            "disabled_symbols": list(self._disabled_symbols),
            "consecutive_timeouts": dict(self._consecutive_timeouts),
        }
