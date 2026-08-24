"""Position Reconciliation Engine — matches internal state to broker state.

Critical for live trading. Runs every 30 seconds during live session.
Detects ghost positions, missing positions, and quantity mismatches.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ReconciliationIssue(str, Enum):
    GHOST_POSITION = "GHOST_POSITION"
    MISSING_POSITION = "MISSING_POSITION"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    OK = "OK"


@dataclass(frozen=True)
class ReconciliationResult:
    """Result of a reconciliation check."""

    issue: ReconciliationIssue
    internal_id: str
    broker_id: str
    internal_qty: float
    broker_qty: float
    internal_symbol: str
    broker_symbol: str
    resolution: str
    severity: str  # "OK", "WARNING", "CRITICAL"


@dataclass
class PositionReconciliationEngine:
    """Compares internal portfolio state to broker positions.

    Called every 30 seconds during live session. Detects and resolves
    discrepancies between system state and broker state.
    """

    def __init__(self, broker_adapter=None) -> None:
        self._broker = broker_adapter
        self._last_reconciliation: float = 0.0
        self._issues_found: int = 0
        self._ghost_positions: int = 0
        self._mismatches: int = 0

    def reconcile(
        self,
        internal_positions: dict,  # id -> Position
        broker_positions: list,  # list of dicts from broker API
    ) -> list[ReconciliationResult]:
        """Run one reconciliation cycle.

        Args:
            internal_positions: dict of position_id -> Position objects
            broker_positions: list of dicts from broker position API

        Returns:
            List of reconciliation issues found
        """
        results = []

        # Index broker positions by symbol
        broker_by_symbol: dict[str, list] = {}
        for bp in broker_positions:
            symbol = bp.get("trading_symbol", "")
            if symbol not in broker_by_symbol:
                broker_by_symbol[symbol] = []
            broker_by_symbol[symbol].append(bp)

        # Check each internal position against broker
        internal_symbols = set()
        for pos_id, pos in internal_positions.items():
            symbol = getattr(pos, "symbol", "")
            internal_symbols.add(symbol)

            broker_match = broker_by_symbol.get(symbol, [])
            if not broker_match:
                # Ghost position — in system but not in broker
                results.append(
                    ReconciliationResult(
                        issue=ReconciliationIssue.GHOST_POSITION,
                        internal_id=pos_id,
                        broker_id="",
                        internal_qty=float(getattr(pos, "size", 0)),
                        broker_qty=0,
                        internal_symbol=symbol,
                        broker_symbol="",
                        resolution="Mark as closed, compute PnL from last known LTP",
                        severity="CRITICAL",
                    )
                )
            else:
                # Check quantity match
                broker_qty = sum(
                    bp.get("netQty", 0) or bp.get("quantity", 0) for bp in broker_match
                )
                internal_qty = float(getattr(pos, "size", 0))
                if abs(internal_qty - broker_qty) > 0.01:
                    results.append(
                        ReconciliationResult(
                            issue=ReconciliationIssue.QUANTITY_MISMATCH,
                            internal_id=pos_id,
                            broker_id=broker_match[0].get("orderId", ""),
                            internal_qty=internal_qty,
                            broker_qty=float(broker_qty),
                            internal_symbol=symbol,
                            broker_symbol=symbol,
                            resolution=f"Reduce internal to {broker_qty}",
                            severity="WARNING",
                        )
                    )

        # Check for missing positions (in broker, not in system)
        for symbol, bps in broker_by_symbol.items():
            if symbol not in internal_symbols:
                results.append(
                    ReconciliationResult(
                        issue=ReconciliationIssue.MISSING_POSITION,
                        internal_id="",
                        broker_id=bps[0].get("orderId", ""),
                        internal_qty=0,
                        broker_qty=float(
                            bps[0].get("netQty", 0) or bps[0].get("quantity", 0)
                        ),
                        internal_symbol="",
                        broker_symbol=symbol,
                        resolution="Register as external position, monitor only",
                        severity="WARNING",
                    )
                )

        self._issues_found += len(
            [r for r in results if r.issue != ReconciliationIssue.OK]
        )
        self._ghost_positions += len(
            [r for r in results if r.issue == ReconciliationIssue.GHOST_POSITION]
        )
        self._mismatches += len(
            [r for r in results if r.issue == ReconciliationIssue.QUANTITY_MISMATCH]
        )

        return results

    def get_stats(self) -> dict:
        """Get reconciliation statistics."""
        return {
            "issues_found": self._issues_found,
            "ghost_positions": self._ghost_positions,
            "mismatches": self._mismatches,
        }

    def reset_stats(self) -> None:
        self._issues_found = 0
        self._ghost_positions = 0
        self._mismatches = 0
