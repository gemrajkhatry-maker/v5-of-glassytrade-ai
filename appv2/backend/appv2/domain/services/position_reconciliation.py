"""Position Reconciliation — compares internal vs broker positions every 30s.

Critical for live trading: detects discrepancies between what the system
thinks is open vs what the broker reports.

Reconciliation logic:
1. Fetch broker positions
2. Match by symbol + side
3. Compare quantity + average price
4. Alert on mismatch
5. Auto-correct option (use broker as source of truth, or freeze trading)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationResult:
    matched: bool
    discrepancies: list[str]
    internal_count: int
    broker_count: int
    timestamp: float


@dataclass(frozen=True)
class PositionMatch:
    symbol: str
    side: str
    internal_qty: int
    broker_qty: int
    internal_avg: float
    broker_avg: float
    matched: bool


class PositionReconciler:
    """Reconciles internal positions with broker positions.

    Usage:
        reconciler = PositionReconciler()
        result = await reconciler.reconcile(internal_positions, broker_positions)
        if result.discrepancies:
            # Handle mismatch
    """

    def __init__(
        self,
        interval_seconds: int = 30,
        on_mismatch: Callable[[ReconciliationResult], Awaitable[None]] | None = None,
    ):
        self._interval = interval_seconds
        self._on_mismatch = on_mismatch
        self._last_reconciliation: float = 0.0
        self._consecutive_mismatches: int = 0
        self._max_mismatches_before_halt: int = 3

    async def reconcile(
        self,
        internal_positions: list[dict],
        broker_positions: list[dict],
    ) -> ReconciliationResult:
        """Reconcile internal vs broker positions.

        Args:
            internal_positions: List of dicts with keys:
                symbol, side (BUY/SELL), quantity, avg_price
            broker_positions: Same format from broker API

        Returns:
            ReconciliationResult with match status and discrepancies
        """
        self._last_reconciliation = time.time()
        discrepancies: list[str] = []
        matches: list[PositionMatch] = []

        # Build lookup maps
        internal_map = {}
        for pos in internal_positions:
            key = (pos["symbol"], pos["side"])
            internal_map[key] = pos

        broker_map = {}
        for pos in broker_positions:
            key = (pos["symbol"], pos["side"])
            broker_map[key] = pos

        # Check internal positions against broker
        for key, int_pos in internal_map.items():
            symbol, side = key
            broker_pos = broker_map.get(key)

            if broker_pos is None:
                discrepancies.append(
                    f"MISSING in broker: {symbol} {side} qty={int_pos['quantity']}"
                )
                matches.append(PositionMatch(
                    symbol=symbol,
                    side=side,
                    internal_qty=int_pos["quantity"],
                    broker_qty=0,
                    internal_avg=int_pos.get("avg_price", 0),
                    broker_avg=0,
                    matched=False,
                ))
            else:
                qty_match = int_pos["quantity"] == broker_pos["quantity"]
                price_diff = abs(
                    int_pos.get("avg_price", 0) - broker_pos.get("avg_price", 0)
                )
                price_match = price_diff < 0.01  # Within 1 paisa

                if not qty_match or not price_match:
                    discrepancies.append(
                        f"MISMATCH: {symbol} {side} | "
                        f"Internal: qty={int_pos['quantity']}, avg={int_pos.get('avg_price', 0):.2f} | "
                        f"Broker: qty={broker_pos['quantity']}, avg={broker_pos.get('avg_price', 0):.2f}"
                    )

                matches.append(PositionMatch(
                    symbol=symbol,
                    side=side,
                    internal_qty=int_pos["quantity"],
                    broker_qty=broker_pos["quantity"],
                    internal_avg=int_pos.get("avg_price", 0),
                    broker_avg=broker_pos.get("avg_price", 0),
                    matched=qty_match and price_match,
                ))

        # Check for broker positions not in internal
        for key, broker_pos in broker_map.items():
            if key not in internal_map:
                discrepancies.append(
                    f"EXTRA in broker (not tracked): "
                    f"{key[0]} {key[1]} qty={broker_pos['quantity']}"
                )

        # Update mismatch counter
        if discrepancies:
            self._consecutive_mismatches += 1
            logger.warning(
                "Reconciliation FAILED (%d discrepancies, consecutive: %d): %s",
                len(discrepancies),
                self._consecutive_mismatches,
                discrepancies,
            )

            if self._on_mismatch:
                result = ReconciliationResult(
                    matched=False,
                    discrepancies=discrepancies,
                    internal_count=len(internal_positions),
                    broker_count=len(broker_positions),
                    timestamp=time.time(),
                )
                await self._on_mismatch(result)
        else:
            self._consecutive_mismatches = 0

        return ReconciliationResult(
            matched=len(discrepancies) == 0,
            discrepancies=discrepancies,
            internal_count=len(internal_positions),
            broker_count=len(broker_positions),
            timestamp=time.time(),
        )

    @property
    def should_halt_trading(self) -> bool:
        """Halt if consecutive mismatches exceed threshold."""
        return self._consecutive_mismatches >= self._max_mismatches_before_halt

    @property
    def seconds_since_last(self) -> float:
        if self._last_reconciliation <= 0:
            return float("inf")
        return time.time() - self._last_reconciliation

    def reset(self) -> None:
        self._consecutive_mismatches = 0
        self._last_reconciliation = 0.0
