"""Phase 5: Reconciliation after restart.

Rebuilds state from event store (journal) and compares with broker positions.
Detects stale positions (in journal, not at broker) and orphaned positions
(at broker, not in journal).

After any restart or recovery:
1. Replay journal → rebuild EngineState
2. Query broker → get actual positions
3. Compare: journal positions vs broker positions
4. If mismatch:
   - Journal has position, broker doesn't → stale, remove from journal
   - Broker has position, journal doesn't → orphaned, register as external
   - Quantity mismatch → use broker quantity, log discrepancy
5. Only resume trading after reconciliation passes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from quant.event_store import EventStore
from quant.state_machine import EngineState


class BrokerInterface(Protocol):
    """Interface for broker operations needed by reconciliation."""
    
    def get_positions(self) -> list[dict[str, Any]]:
        """Get current positions from broker."""
        ...


@dataclass(frozen=True)
class ReconciliationResult:
    """Result of reconciliation."""
    can_trade: bool
    discrepancies: tuple[str, ...]
    
    @staticmethod
    def ok() -> ReconciliationResult:
        """Create a successful result."""
        return ReconciliationResult(can_trade=True, discrepancies=())
    
    @staticmethod
    def failed(discrepancies: list[str]) -> ReconciliationResult:
        """Create a failed result."""
        return ReconciliationResult(can_trade=False, discrepancies=tuple(discrepancies))


class Reconciliation:
    """Reconciles journal state with broker state."""
    
    def __init__(self, event_store: EventStore, broker: BrokerInterface) -> None:
        self._event_store = event_store
        self._broker = broker
    
    def rebuild_state(self) -> EngineState:
        """Rebuild state from event store (journal replay)."""
        return self._event_store.fold()
    
    def reconcile(self) -> ReconciliationResult:
        """Compare journal state with broker state.
        
        Returns:
            ReconciliationResult indicating if trading can resume.
        """
        # Get journal positions
        journal_positions = self._get_journal_positions()
        
        # Get broker positions
        broker_positions = self._get_broker_positions()
        
        # Compare
        discrepancies: list[str] = []
        blocking_discrepancies: list[str] = []
        
        # Check for stale positions (in journal, not at broker)
        for pos_id, journal_pos in journal_positions.items():
            broker_pos = broker_positions.get(pos_id)
            if broker_pos is None:
                discrepancies.append(
                    f"Stale: position {pos_id} ({journal_pos['symbol']}) in journal "
                    f"but not at broker — manual review needed"
                )
            elif broker_pos["size"] != journal_pos["size"]:
                blocking_discrepancies.append(
                    f"Size mismatch: position {pos_id} journal={journal_pos['size']} "
                    f"vs broker={broker_pos['size']}"
                )
        
        # Check for orphaned positions (at broker, not in journal)
        for pos_id, broker_pos in broker_positions.items():
            if pos_id not in journal_positions:
                blocking_discrepancies.append(
                    f"Orphaned: position {pos_id} ({broker_pos['symbol']}) at broker "
                    f"but not in journal — manual review needed"
                )
        
        # Stale positions are non-blocking (can be cleaned up)
        # Orphaned positions and size mismatches are blocking
        if blocking_discrepancies:
            return ReconciliationResult.failed(blocking_discrepancies)
        
        # If only stale positions, can trade after cleanup
        if discrepancies:
            return ReconciliationResult(can_trade=True, discrepancies=tuple(discrepancies))
        
        return ReconciliationResult.ok()
    
    def _get_journal_positions(self) -> dict[str, dict[str, Any]]:
        """Extract open positions from journal events."""
        positions: dict[str, dict[str, Any]] = {}
        
        for event in self._event_store.get_all():
            if hasattr(event, 'position'):
                pos = event.position
                # Support both PositionState (id) and legacy Position (_id)
                pos_id = getattr(pos, 'id', None) or getattr(pos, '_id', None)
                if pos_id:
                    positions[pos_id] = {
                        "id": pos_id,
                        "symbol": event.symbol,
                        "entry": getattr(pos, 'entry', 0.0),
                        "size": getattr(pos, 'size', 0.0),
                        "sl": getattr(pos, 'sl', 0.0),
                        "tp": getattr(pos, 'tp', 0.0),
                        "side": getattr(pos, 'side', 'LONG'),
                    }
            elif hasattr(event, 'fill'):
                fill = event.fill
                if hasattr(fill, 'position'):
                    pos = fill.position
                    pos_id = getattr(pos, 'id', None) or getattr(pos, '_id', None)
                    if pos_id and pos_id in positions:
                        del positions[pos_id]
        
        return positions
    
    def _get_broker_positions(self) -> dict[str, dict[str, Any]]:
        """Get positions from broker, indexed by ID."""
        positions: dict[str, dict[str, Any]] = {}
        
        for pos in self._broker.get_positions():
            pos_id = pos.get("id")
            if pos_id:
                positions[pos_id] = pos
        
        return positions
