"""Order Retry — handles failed order retries with exponential backoff.

When an order fails:
1. Wait backoff_ms × 2^attempt
2. Retry up to max_attempts times
3. If all retries fail, alert and halt trading
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from appv2.config import constants as C

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryResult:
    success: bool
    order_id: str = ""
    attempts: int = 0
    last_error: str = ""
    total_time_ms: float = 0.0


class OrderRetryHandler:
    """Retries failed orders with exponential backoff."""

    def __init__(
        self,
        max_attempts: int = C.ORDER_RETRY_MAX_ATTEMPTS,
        base_backoff_ms: int = C.ORDER_RETRY_BACKOFF_BASE_MS,
        max_backoff_ms: int = 10_000,
    ):
        self._max_attempts = max_attempts
        self._base_backoff_ms = base_backoff_ms
        self._max_backoff_ms = max_backoff_ms
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0

    async def execute_with_retry(
        self,
        place_order_fn,  # Async callable that places the order
        *args,
        **kwargs,
    ) -> RetryResult:
        """Execute order placement with retry logic.

        Args:
            place_order_fn: Async callable that returns order_id or raises
            *args, **kwargs: Arguments passed to place_order_fn

        Returns:
            RetryResult with success/failure details
        """
        start_time = time.time()

        for attempt in range(1, self._max_attempts + 1):
            try:
                order_id = await place_order_fn(*args, **kwargs)
                self._failure_count = 0
                elapsed_ms = (time.time() - start_time) * 1000
                return RetryResult(
                    success=True,
                    order_id=order_id,
                    attempts=attempt,
                    total_time_ms=round(elapsed_ms, 1),
                )
            except Exception as e:
                self._failure_count += 1
                self._last_failure_time = time.time()
                error_msg = str(e)

                if attempt < self._max_attempts:
                    backoff = self._get_backoff_ms(attempt)
                    logger.warning(
                        "Order attempt %d/%d failed: %s — retrying in %.1fs",
                        attempt, self._max_attempts, error_msg, backoff / 1000,
                    )
                    await asyncio.sleep(backoff / 1000)
                else:
                    elapsed_ms = (time.time() - start_time) * 1000
                    logger.error(
                        "Order FAILED after %d attempts: %s",
                        attempt, error_msg,
                    )
                    return RetryResult(
                        success=False,
                        attempts=attempt,
                        last_error=error_msg,
                        total_time_ms=round(elapsed_ms, 1),
                    )

        # Should not reach here
        return RetryResult(success=False, attempts=self._max_attempts, last_error="Unknown")

    def _get_backoff_ms(self, attempt: int) -> float:
        """Exponential backoff with jitter."""
        import random
        base = min(self._base_backoff_ms * (2 ** (attempt - 1)), self._max_backoff_ms)
        jitter = random.uniform(0, base * 0.1)
        return base + jitter

    @property
    def consecutive_failures(self) -> int:
        return self._failure_count

    @property
    def should_halt(self) -> bool:
        """Halt if too many consecutive failures."""
        return self._failure_count >= self._max_attempts * 2

    def reset(self) -> None:
        self._failure_count = 0
        self._last_failure_time = 0.0
