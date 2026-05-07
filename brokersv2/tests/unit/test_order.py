"""Tests for order state machine."""

import pytest
from datetime import datetime
from decimal import Decimal

from brokersv2.domain.order.models import Order, OrderStateMachine
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import OrderStatus, OrderSide, OrderType, Exchange, Segment, InstrumentType


@pytest.fixture
def sample_instrument():
    """Create a sample instrument for testing."""
    return CanonicalInstrument(
        internal_uid="test-uid-123",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        segment=Segment.EQUITY,
        instrument_type=InstrumentType.EQUITY,
        lot_size=1,
        tick_size=Decimal("0.01"),
    )


class TestOrderStateMachine:
    """Tests for order state machine transitions."""
    
    def test_valid_transitions(self, sample_instrument):
        """Test all valid state transitions."""
        order = Order(
            order_id="test-order-1",
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            status=OrderStatus.NEW,
        )
        
        # NEW -> VALIDATED
        assert OrderStateMachine.transition(order, OrderStatus.VALIDATED)
        assert order.status == OrderStatus.VALIDATED
        
        # VALIDATED -> SENT
        assert OrderStateMachine.transition(order, OrderStatus.SENT)
        assert order.status == OrderStatus.SENT
        
        # SENT -> ACKNOWLEDGED
        assert OrderStateMachine.transition(order, OrderStatus.ACKNOWLEDGED)
        assert order.status == OrderStatus.ACKNOWLEDGED
        
        # ACKNOWLEDGED -> OPEN
        assert OrderStateMachine.transition(order, OrderStatus.OPEN)
        assert order.status == OrderStatus.OPEN
        
        # OPEN -> PARTIALLY_FILLED
        assert OrderStateMachine.transition(order, OrderStatus.PARTIALLY_FILLED)
        assert order.status == OrderStatus.PARTIALLY_FILLED
        
        # PARTIALLY_FILLED -> FILLED
        assert OrderStateMachine.transition(order, OrderStatus.FILLED)
        assert order.status == OrderStatus.FILLED
    
    def test_invalid_transition_returns_false(self, sample_instrument):
        """Test that invalid transitions return False."""
        order = Order(
            order_id="test-order-2",
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            status=OrderStatus.FILLED,  # Terminal state
        )
        
        # FILLED cannot transition to anything
        assert not OrderStateMachine.transition(order, OrderStatus.CANCELLED)
        assert order.status == OrderStatus.FILLED  # Unchanged
    
    def test_cancel_flow(self, sample_instrument):
        """Test order cancellation flow."""
        order = Order(
            order_id="test-order-3",
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            status=OrderStatus.OPEN,
        )
        
        # OPEN -> CANCEL_PENDING
        assert OrderStateMachine.transition(order, OrderStatus.CANCEL_PENDING)
        
        # CANCEL_PENDING -> CANCELLED
        assert OrderStateMachine.transition(order, OrderStatus.CANCELLED)
        assert order.status == OrderStatus.CANCELLED


class TestOrder:
    """Tests for Order aggregate."""
    
    def test_add_fill_updates_quantity(self, sample_instrument):
        """Test that fill updates filled quantity."""
        order = Order(
            order_id="test-order-4",
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            status=OrderStatus.OPEN,
        )
        
        order.add_fill(Decimal("50"), Decimal("100"))
        assert order.filled_quantity == Decimal("50")
        assert order.status == OrderStatus.PARTIALLY_FILLED
        
        order.add_fill(Decimal("50"), Decimal("101"))
        assert order.filled_quantity == Decimal("100")
        assert order.status == OrderStatus.FILLED
    
    def test_remaining_quantity(self, sample_instrument):
        """Test remaining quantity calculation."""
        order = Order(
            order_id="test-order-5",
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            status=OrderStatus.OPEN,
        )
        
        assert order.remaining_quantity == Decimal("100")
        order.filled_quantity = Decimal("30")
        assert order.remaining_quantity == Decimal("70")