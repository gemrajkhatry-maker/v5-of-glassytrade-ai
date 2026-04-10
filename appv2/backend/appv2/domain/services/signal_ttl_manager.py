"""Signal TTL Manager — manages signal lifecycle with expiration and retry.

Handles:
- Signal expiration after TTL seconds
- Signal deduplication (prevent double-execution)
- Retry on order failure
- Signal age tracking
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from appv2.domain.models.signal import Signal
from appv2.config import constants as C

logger = logging.getLogger(__name__)


@dataclass
class SignalState:
    signal: Signal
    status: str  # "PENDING" | "EXECUTING" | "FILLED" | "EXPIRED" | "REJECTED"
    attempts: int = 0
    last_attempt: float = 0.0
    order_id: str = ""


class SignalTTLManager:
    """Manages signal lifecycle with TTL and retry."""

    def __init__(
        self,
        ttl_seconds: int = C.SIGNAL_TTL_SECONDS,
        max_retries: int = C.ORDER_RETRY_MAX_ATTEMPTS,
        retry_backoff_ms: int = C.ORDER_RETRY_BACKOFF_BASE_MS,
    ):
        self._ttl = ttl_seconds
        self._max_retries = max_retries
        self._retry_backoff_ms = retry_backoff_ms
        self._signals: dict[str, SignalState] = {}  # symbol → state
        self._executed_ids: set[str] = set()  # Prevent double execution

    def add_signal(self, signal: Signal) -> bool:
        """Add a new signal to the manager.

        Returns:
            True if added, False if duplicate or expired.
        """
        # Check for duplicate
        if signal.symbol in self._signals:
            existing = self._signals[signal.symbol]
            if existing.status in ("PENDING", "EXECUTING"):
                logger.debug("Duplicate signal for %s — ignoring", signal.symbol)
                return False

        # Check expired
        if signal.is_expired:
            logger.debug("Signal expired before adding for %s", signal.symbol)
            return False

        self._signals[signal.symbol] = SignalState(
            signal=signal,
            status="PENDING",
        )
        logger.info(
            "Signal added: %s %s @ %.4f (TTL: %ds)",
            signal.symbol, signal.direction.value, signal.entry_price, self._ttl,
        )
        return True

    def get_pending_signal(self, symbol: str) -> Signal | None:
        """Get pending signal for symbol, checking TTL."""
        state = self._signals.get(symbol)
        if state is None:
            return None

        if state.status != "PENDING":
            return None

        # Check TTL
        if state.signal.is_expired:
            state.status = "EXPIRED"
            logger.warning("Signal expired for %s (age: %.0fs)", symbol, state.signal.age_seconds)
            return None

        return state.signal

    def mark_executing(self, symbol: str) -> None:
        """Mark signal as being executed."""
        state = self._signals.get(symbol)
        if state:
            state.status = "EXECUTING"
            state.attempts += 1
            state.last_attempt = time.time()

    def mark_filled(self, symbol: str, order_id: str) -> None:
        """Mark signal as filled."""
        state = self._signals.get(symbol)
        if state:
            state.status = "FILLED"
            state.order_id = order_id
            self._executed_ids.add(symbol)

    def mark_rejected(self, symbol: str, reason: str) -> None:
        """Mark signal as rejected."""
        state = self._signals.get(symbol)
        if state:
            state.status = "REJECTED"
            logger.info("Signal rejected for %s: %s", symbol, reason)

    def should_retry(self, symbol: str) -> bool:
        """Check if a failed signal should be retried."""
        state = self._signals.get(symbol)
        if not state:
            return False

        if state.attempts >= self._max_retries:
            return False

        # Check backoff
        if state.last_attempt > 0:
            elapsed_ms = (time.time() - state.last_attempt) * 1000
            backoff = self._retry_backoff_ms * (2 ** (state.attempts - 1))
            if elapsed_ms < backoff:
                return False

        # Check TTL
        if state.signal.is_expired:
            return False

        return True

    def get_retry_backoff_ms(self, symbol: str) -> float:
        """Get current retry backoff for symbol."""
        state = self._signals.get(symbol)
        if not state:
            return 0.0
        attempts = max(1, state.attempts)
        return self._retry_backoff_ms * (2 ** (attempts - 1))

    def cleanup_expired(self) -> list[str]:
        """Remove expired signals. Returns list of cleaned symbols."""
        expired = []
        for symbol, state in list(self._signals.items()):
            if state.status in ("EXPIRED", "FILLED", "REJECTED"):
                expired.append(symbol)
                del self._signals[symbol]
            elif state.signal.is_expired:
                state.status = "EXPIRED"
                expired.append(symbol)
                del self._signals[symbol]
        return expired

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._signals.values() if s.status == "PENDING")

    def reset(self) -> None:
        self._signals.clear()
        self._executed_ids.clear()
