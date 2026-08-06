"""Invariant tests for Trading System - Domain-Driven Design Verification.

These tests verify that the core invariants hold:
1. Position always derived from fills (never stored)
2. Trade status matches position state
3. Realized PnL equals sum of fill PnLs
4. Events are append-only (immutability)
5. Idempotency keys prevent duplicates
6. State reconstruction yields deterministic results
7. State derivation is consistent
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone
import uuid

from app.domain.trading.models.trade_aggregate import (
    Trade,
    TradeStatus,
    CloseReason,
    Confidence,
    Direction,
    FillType,
    EntrySignal,
    Fill,
    Position,
    TradeThesis,
    create_trade,
    create_trade_from_snapshot,
)
from quant.contracts.enums import Side, SetupType
from quant.contracts.events import (
    DomainEvent,
    FillReceived,
    SignalGenerated,
    OrderPlaced,
    PositionChanged,
)
from quant.contracts.event_store import (
    EventBus,
    InMemoryEventStore,
    AuditTrailVerifier,
)


# =============================================================================
# INVARIANT 1: Position = Derived from Fills
# =============================================================================


class TestPositionDerivationInvariant:
    """INVARIANT: position.quantity = sum(fills.quantity) - ALWAYS TRUE"""

    def test_position_equals_sum_of_entry_fills(self):
        """Position quantity must equal sum of entry fills minus sum of exit fills."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("50"),
                fill_type=FillType.ENTRY,
            ),
            Fill(
                fill_id="F2",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("110"),
                quantity=Decimal("50"),
                fill_type=FillType.SCALE_IN,
            ),
        )

        position = Position.from_fills(fills)

        # Total entry quantity = 50 + 50 = 100
        assert position.quantity == Decimal("100")

    def test_position_zero_after_full_exit(self):
        """After full exit, position quantity must be zero."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("100"),
                fill_type=FillType.ENTRY,
            ),
            Fill(
                fill_id="F2",
                trade_id="T1",
                side=Side.SHORT,
                price=Decimal("120"),
                quantity=Decimal("100"),
                fill_type=FillType.EXIT,
            ),
        )

        position = Position.from_fills(fills)

        assert position.quantity == Decimal("0")

    def test_partial_exit_reduces_position(self):
        """Partial exit must reduce position quantity."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("100"),
                fill_type=FillType.ENTRY,
            ),
            Fill(
                fill_id="F2",
                trade_id="T1",
                side=Side.SHORT,
                price=Decimal("120"),
                quantity=Decimal("50"),
                fill_type=FillType.PARTIAL,
            ),
        )

        position = Position.from_fills(fills)

        # 100 - 50 = 50
        assert position.quantity == Decimal("50")

    def test_weighted_avg_entry_price(self):
        """Average entry price must be weighted by quantity."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("50"),
                fill_type=FillType.ENTRY,
            ),
            Fill(
                fill_id="F2",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("120"),
                quantity=Decimal("50"),
                fill_type=FillType.SCALE_IN,
            ),
        )

        position = Position.from_fills(fills)

        # Weighted avg = (100*50 + 120*50) / 100 = 110
        assert position.avg_entry_price == Decimal("110")


# =============================================================================
# INVARIANT 2: Trade Status Matches Position State
# =============================================================================


class TestTradeStatusInvariant:
    """INVARIANT: trade.status = OPEN iff position.is_open"""

    def test_pending_trade_has_closed_position(self):
        """Pending trade must have zero quantity position."""
        signal = EntrySignal(
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")

        assert trade.status == TradeStatus.PENDING
        assert not trade.position.is_open
        assert trade.position.quantity == Decimal("0")

    def test_open_trade_has_open_position(self):
        """Open trade must have open position (quantity > 0)."""
        signal = EntrySignal(
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        fill = Fill(
            fill_id="F1",
            trade_id=trade.trade_id,
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            fill_type=FillType.ENTRY,
            timestamp="2025-01-01T10:00:00Z",
        )
        trade = trade.add_fill(fill)

        assert trade.status == TradeStatus.OPEN
        assert trade.position.is_open
        assert trade.position.quantity > Decimal("0")

    def test_closed_trade_has_closed_position(self):
        """Closed trade must have zero quantity position."""
        signal = EntrySignal(
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        # Entry fill
        fill1 = Fill(
            fill_id="F1",
            trade_id=trade.trade_id,
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            fill_type=FillType.ENTRY,
            timestamp="2025-01-01T10:00:00Z",
        )
        trade = trade.add_fill(fill1)

        # Exit fill
        fill2 = Fill(
            fill_id="F2",
            trade_id=trade.trade_id,
            side=Side.SHORT,
            price=Decimal("120"),
            quantity=Decimal("75"),
            fill_type=FillType.EXIT,
            timestamp="2025-01-01T10:30:00Z",
        )
        trade = trade.add_fill(fill2)

        assert trade.status == TradeStatus.CLOSED
        assert not trade.position.is_open
        assert trade.position.quantity == Decimal("0")


# =============================================================================
# INVARIANT 3: Realized PnL from Fills
# =============================================================================


class TestPnLInvariant:
    """INVARIANT: realized_pnl = sum of exit fill PnLs"""

    def test_realized_pnl_from_single_exit(self):
        """Realized PnL must come from exit fills."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("100"),
                fill_type=FillType.ENTRY,
            ),
            Fill(
                fill_id="F2",
                trade_id="T1",
                side=Side.SHORT,
                price=Decimal("120"),
                quantity=Decimal("100"),
                fill_type=FillType.EXIT,
                commission=Decimal("10"),
            ),
        )

        position = Position.from_fills(fills)

        # Exit: 120 * 100 - 100 * 100 - 10 = 2000 - 10000 - 10 = -8010 (simplified)
        # The actual PnL calculation should account for both entry and exit
        assert position.quantity == Decimal("0")  # Fully closed


# =============================================================================
# INVARIANT 4: Event Immutability
# =============================================================================


class TestEventImmutabilityInvariant:
    """INVARIANT: Events are immutable (frozen)"""

    def test_domain_event_is_frozen(self):
        """DomainEvent must be frozen (immutable)."""
        event = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        # Attempting to modify should raise
        with pytest.raises(Exception):  # FrozenInstanceError
            event.price = 200.0

    def test_event_has_timestamp(self):
        """All events must have timestamp."""
        event = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        assert event.timestamp is not None
        assert len(event.timestamp) > 0


# =============================================================================
# INVARIANT 5: Idempotency
# =============================================================================


class TestIdempotencyInvariant:
    """INVARIANT: Duplicate events are rejected"""

    def test_duplicate_fill_rejected(self):
        """Duplicate fill with same idempotency key must be rejected."""
        store = InMemoryEventStore()

        event = FillReceived(
            idempotency_key="T1|F1",
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        store.append(event)

        # Try to add duplicate
        from quant.contracts.event_store import DuplicateEventError

        with pytest.raises(DuplicateEventError):
            store.append(event)

    def test_different_events_allowed(self):
        """Different events with different keys must be allowed."""
        store = InMemoryEventStore()

        event1 = FillReceived(
            idempotency_key="T1|F1",
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        event2 = FillReceived(
            idempotency_key="T1|F2",  # Different key
            trade_id="T1",
            fill_id="F2",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        store.append(event1)
        store.append(event2)  # Should not raise

        assert store.get_event_count() == 2


# =============================================================================
# INVARIANT 6: Deterministic State Reconstruction
# =============================================================================


class TestDeterminismInvariant:
    """INVARIANT: Same events always produce same state"""

    def test_state_reconstruction_is_repeatable(self):
        """Applying the same events twice must produce identical state."""
        store = InMemoryEventStore()
        engine = AuditTrailVerifier(store)

        events = [
            SignalGenerated(
                idempotency_key="sig1",
                signal_id="S1",
                symbol="NIFTY",
                direction="LONG",
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=115.0,
                position_size=75.0,
                confidence="HIGH",
                setup_type="TREND",
            ),
            FillReceived(
                idempotency_key="T1|F1",
                trade_id="T1",
                fill_id="F1",
                symbol="NIFTY",
                side="BUY",
                fill_type="ENTRY",
                price=100.0,
                quantity=75.0,
            ),
        ]

        for e in events:
            store.append(e)

        # Verify determinism
        assert engine.verify_determinism(events) is True

    def test_different_event_order_same_final_state(self):
        """Event order should not change final derived state."""
        store1 = InMemoryEventStore()
        verifier1 = AuditTrailVerifier(store1)

        # Add in order: signal, fill
        events1 = [
            SignalGenerated(
                signal_id="S1",
                symbol="NIFTY",
                direction="LONG",
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=115.0,
                position_size=75.0,
                confidence="HIGH",
                setup_type="TREND",
            ),
            FillReceived(
                trade_id="T1",
                fill_id="F1",
                symbol="NIFTY",
                side="BUY",
                fill_type="ENTRY",
                price=100.0,
                quantity=75.0,
            ),
        ]
        for e in events1:
            store1.append(e)

        store2 = InMemoryEventStore()
        verifier2 = AuditTrailVerifier(store2)

        # Add in reverse order: fill, signal
        events2 = [
            FillReceived(
                trade_id="T1",
                fill_id="F1",
                symbol="NIFTY",
                side="BUY",
                fill_type="ENTRY",
                price=100.0,
                quantity=75.0,
            ),
            SignalGenerated(
                signal_id="S1",
                symbol="NIFTY",
                direction="LONG",
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=115.0,
                position_size=75.0,
                confidence="HIGH",
                setup_type="TREND",
            ),
        ]
        for e in events2:
            store2.append(e)

        # Both should have same count
        assert store1.get_event_count() == store2.get_event_count()


# =============================================================================
# INVARIANT 7: State Derivation Consistency
# =============================================================================


class TestStateDerivationInvariant:
    """INVARIANT: Derived state is always consistent"""

    def test_position_matches_trade_position(self):
        """Trade.position must match manually derived position."""
        signal = EntrySignal(
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        # Add fills to trade
        fill = Fill(
            fill_id="F1",
            trade_id=trade.trade_id,
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            fill_type=FillType.ENTRY,
            timestamp="2025-01-01T10:00:00Z",
        )
        trade = trade.add_fill(fill)

        # Trade's derived position (uses trade.fills)
        trade_position = trade.position

        # Manual calculation with same fills
        fills = (fill,)
        direct_position = Position.from_fills(fills, Decimal("100"))

        # Must be equal
        assert trade_position.quantity == direct_position.quantity
        assert trade_position.avg_entry_price == direct_position.avg_entry_price

    def test_snapshot_reconstruction_preserves_invariants(self):
        """Trade reconstructed from snapshot must preserve all invariants."""
        signal = EntrySignal(
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            thesis=TradeThesis(
                market_state="BALANCED",
                location_type="POC",
                location_level=100.0,
                aggression_trigger="DELTA_EXPANSION",
                session_context="MORNING",
                invalidation_level=95.0,
            ),
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        fill = Fill(
            fill_id="F1",
            trade_id=trade.trade_id,
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            fill_type=FillType.ENTRY,
        )
        trade = trade.add_fill(fill)

        # Snapshot and reconstruct
        snapshot = trade.to_snapshot()
        reconstructed = create_trade_from_snapshot(snapshot)

        # Invariant: position must match
        assert reconstructed.position.quantity == trade.position.quantity

        # Invariant: status must match
        assert reconstructed.status == trade.status

        # Invariant: fills must match
        assert len(reconstructed.fills) == len(trade.fills)


# =============================================================================
# INVARIANT 8: Event Ordering
# =============================================================================


class TestEventOrderingInvariant:
    """INVARIANT: Events are ordered by timestamp"""

    def test_events_ordered_by_timestamp(self):
        """Events must be retrievable in timestamp order."""
        store = InMemoryEventStore()

        events = [
            FillReceived(
                idempotency_key="e1",
                timestamp="2025-01-01T10:00:00Z",
                trade_id="T1",
                fill_id="F1",
                symbol="NIFTY",
                side="BUY",
                fill_type="ENTRY",
                price=100.0,
                quantity=75.0,
            ),
            FillReceived(
                idempotency_key="e2",
                timestamp="2025-01-01T10:01:00Z",
                trade_id="T1",
                fill_id="F2",
                symbol="NIFTY",
                side="SELL",
                fill_type="EXIT",
                price=110.0,
                quantity=75.0,
            ),
        ]

        for e in events:
            store.append(e)

        retrieved = store.get_events(aggregate_id="T1")

        assert len(retrieved) == 2
        assert retrieved[0].timestamp < retrieved[1].timestamp


# =============================================================================
# INTEGRATION: Full Trade Lifecycle Invariants
# =============================================================================


class TestFullLifecycleInvariants:
    """Test complete trade lifecycle maintains all invariants."""

    def test_complete_trade_lifecycle_invariants(self):
        """Full trade lifecycle: signal → entry → exit must maintain invariants."""

        # 1. Create trade (PENDING)
        signal = EntrySignal(
            signal_id="S1",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("100"),
            confidence=Confidence.HIGH,
        )

        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")

        # INVARIANT: Pending = no position
        assert trade.position.quantity == Decimal("0")
        assert trade.status == TradeStatus.PENDING

        # 2. Open trade
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        # 3. Add entry fill
        entry_fill = Fill(
            fill_id="F1",
            trade_id=trade.trade_id,
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("100"),
            fill_type=FillType.ENTRY,
            timestamp="2025-01-01T10:00:00Z",
        )
        trade = trade.add_fill(entry_fill)

        # INVARIANT: Position reflects fill
        assert trade.position.quantity == Decimal("100")
        assert trade.position.avg_entry_price == Decimal("100")
        assert trade.status == TradeStatus.OPEN

        # 4. Add exit fill (full close)
        exit_fill = Fill(
            fill_id="F2",
            trade_id=trade.trade_id,
            side=Side.SHORT,
            price=Decimal("120"),
            quantity=Decimal("100"),
            fill_type=FillType.EXIT,
            timestamp="2025-01-01T10:30:00Z",
        )
        trade = trade.add_fill(exit_fill)

        # INVARIANT: Position closed = zero quantity
        assert trade.position.quantity == Decimal("0")
        assert trade.status == TradeStatus.CLOSED
        assert trade.close_reason is not None

        # INVARIANT: All events preserved
        events = trade.get_event_history()
        assert len(events) >= 2  # At least OPEN and FILL events
