"""
Tests for Phase 3: Market Data L2 Processing.

Tests:
- IncrementalUpdateHandler for L2 book updates
- SequenceValidator for message sequencing
- OrderBookState management
- Gap detection and recovery
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from brokersv2.marketdata.incremental_handler import (
    IncrementalBatch,
    IncrementalUpdateHandler,
    OrderBookState,
    OrderUpdate,
    SequenceGapError,
    UpdateType,
)
from brokersv2.marketdata.sequence_validator import (
    SequenceError,
    SequenceValidator,
    StreamState,
)


# =============================================================================
# OrderBookState Tests
# =============================================================================

class TestOrderBookState:
    """Test order book state management."""
    
    def test_initial_state(self):
        """Test initial book state."""
        state = OrderBookState("SEC1", "RELIANCE")
        assert state.security_id == "SEC1"
        assert state.symbol == "RELIANCE"
        assert state.last_sequence == 0
        assert state.bids == {}
        assert state.asks == {}
    
    def test_apply_add_order(self):
        """Test adding new order to book."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        batch = IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                )
            ],
        )
        
        applied = state.apply_batch(batch)
        assert applied == 1
        assert state.last_sequence == 1
        assert Decimal("100.00") in state.bids
        assert state.bids[Decimal("100.00")] == (100, 1)
    
    def test_apply_multiple_adds_same_price(self):
        """Test multiple orders at same price level."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        batch = IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=2,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                ),
                OrderUpdate(
                    order_id="ORD2",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=50,
                    side="bid",
                ),
            ],
        )
        
        state.apply_batch(batch)
        assert state.bids[Decimal("100.00")] == (150, 2)  # 150 qty, 2 orders
    
    def test_apply_cancel(self):
        """Test order cancellation."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        # Add order
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                )
            ],
        ))
        
        # Cancel order
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=2,
            sequence_end=2,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.CANCEL,
                    price=Decimal("100.00"),
                    quantity=0,
                    side="bid",
                )
            ],
        ))
        
        assert Decimal("100.00") not in state.bids
        assert "ORD1" not in state.orders
    
    def test_apply_modify(self):
        """Test order modification."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        # Add order
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                )
            ],
        ))
        
        # Modify quantity
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=2,
            sequence_end=2,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.MODIFY,
                    price=Decimal("100.00"),
                    quantity=75,  # Reduced from 100
                    side="bid",
                )
            ],
        ))
        
        assert state.bids[Decimal("100.00")] == (75, 1)
    
    def test_apply_trade(self):
        """Test trade execution reducing order."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        # Add order
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="ask",
                )
            ],
        ))
        
        # Trade executes
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=2,
            sequence_end=2,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.TRADE,
                    price=Decimal("100.00"),
                    quantity=60,  # Partial fill
                    side="ask",
                    trade_price=Decimal("100.00"),
                    trade_quantity=40,
                )
            ],
        ))
        
        # 40 traded, 60 remaining
        assert state.orders["ORD1"] == (Decimal("100.00"), 60, "ask")
    
    def test_sequence_gap_detection(self):
        """Test detection of sequence gaps."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        # First batch: seq 1
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                )
            ],
        ))
        
        # Second batch: seq 3 (gap - missing seq 2)
        with pytest.raises(SequenceGapError):
            state.apply_batch(IncrementalBatch(
                security_id="SEC1",
                symbol="RELIANCE",
                sequence_start=3,  # Should be 2
                sequence_end=3,
                updates=[],
            ))
    
    def test_get_best_bid_ask(self):
        """Test best bid/ask retrieval."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        # Add bids
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=2,
            updates=[
                OrderUpdate(
                    order_id="BID1",
                    update_type=UpdateType.ADD,
                    price=Decimal("99.00"),
                    quantity=100,
                    side="bid",
                ),
                OrderUpdate(
                    order_id="BID2",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=50,
                    side="bid",
                ),
            ],
        ))
        
        # Add ask
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=3,
            sequence_end=3,
            updates=[
                OrderUpdate(
                    order_id="ASK1",
                    update_type=UpdateType.ADD,
                    price=Decimal("101.00"),
                    quantity=75,
                    side="ask",
                )
            ],
        ))
        
        best_bid = state.get_best_bid()
        best_ask = state.get_best_ask()
        
        assert best_bid == (Decimal("100.00"), 50)
        assert best_ask == (Decimal("101.00"), 75)
    
    def test_get_spread(self):
        """Test bid-ask spread calculation."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=2,
            updates=[
                OrderUpdate(
                    order_id="BID1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                ),
                OrderUpdate(
                    order_id="ASK1",
                    update_type=UpdateType.ADD,
                    price=Decimal("101.00"),
                    quantity=100,
                    side="ask",
                ),
            ],
        ))
        
        spread = state.get_spread()
        assert spread == Decimal("1.00")
    
    def test_get_mid_price(self):
        """Test mid price calculation."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=2,
            updates=[
                OrderUpdate(
                    order_id="BID1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                ),
                OrderUpdate(
                    order_id="ASK1",
                    update_type=UpdateType.ADD,
                    price=Decimal("102.00"),
                    quantity=100,
                    side="ask",
                ),
            ],
        ))
        
        mid = state.get_mid_price()
        assert mid == Decimal("101.00")
    
    def test_get_book_depth(self):
        """Test book depth calculation."""
        state = OrderBookState("SEC1", "RELIANCE")
        
        state.apply_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=3,
            updates=[
                OrderUpdate(
                    order_id="BID1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                ),
                OrderUpdate(
                    order_id="BID2",
                    update_type=UpdateType.ADD,
                    price=Decimal("99.00"),
                    quantity=200,
                    side="bid",
                ),
                OrderUpdate(
                    order_id="ASK1",
                    update_type=UpdateType.ADD,
                    price=Decimal("101.00"),
                    quantity=150,
                    side="ask",
                ),
            ],
        ))
        
        depth = state.get_book_depth()
        assert depth["bid_depth"] == 300
        assert depth["ask_depth"] == 150
        assert depth["total_depth"] == 450
        assert depth["bid_levels"] == 2
        assert depth["ask_levels"] == 1


# =============================================================================
# IncrementalUpdateHandler Tests
# =============================================================================

class TestIncrementalUpdateHandler:
    """Test incremental update handler."""
    
    def test_process_single_batch(self):
        """Test processing single batch."""
        handler = IncrementalUpdateHandler()
        
        batch = IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                )
            ],
        )
        
        applied = handler.process_batch(batch)
        assert applied == 1
        
        stats = handler.get_stats()
        assert stats["batches_received"] == 1
        assert stats["updates_applied"] == 1
    
    def test_process_multiple_securities(self):
        """Test handling multiple securities."""
        handler = IncrementalUpdateHandler()
        
        # Process RELIANCE
        handler.process_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                )
            ],
        ))
        
        # Process TCS
        handler.process_batch(IncrementalBatch(
            security_id="SEC2",
            symbol="TCS",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD2",
                    update_type=UpdateType.ADD,
                    price=Decimal("3000.00"),
                    quantity=50,
                    side="ask",
                )
            ],
        ))
        
        active_books = handler.get_active_books()
        assert len(active_books) == 2
        assert "SEC1" in active_books
        assert "SEC2" in active_books
    
    def test_gap_detection(self):
        """Test sequence gap detection across batches."""
        handler = IncrementalUpdateHandler()
        
        # First batch: seq 1
        handler.process_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[],
        ))
        
        # Second batch: seq 3 (gap)
        with pytest.raises(SequenceGapError):
            handler.process_batch(IncrementalBatch(
                security_id="SEC1",
                symbol="RELIANCE",
                sequence_start=3,  # Should be 2
                sequence_end=3,
                updates=[],
            ))
        
        stats = handler.get_stats()
        assert stats["gaps_detected"] == 1
    
    def test_reset(self):
        """Test handler reset."""
        handler = IncrementalUpdateHandler()
        
        handler.process_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[],
        ))
        
        handler.reset()
        
        assert handler.get_active_books() == []
        assert handler.get_stats()["batches_received"] == 0


# =============================================================================
# SequenceValidator Tests
# =============================================================================

class TestSequenceValidator:
    """Test sequence validation."""
    
    def test_valid_sequence(self):
        """Test valid sequential messages."""
        validator = SequenceValidator()
        
        assert validator.validate("stream1", 1) is None
        assert validator.validate("stream1", 2) is None
        assert validator.validate("stream1", 3) is None
    
    def test_detect_duplicate(self):
        """Test duplicate sequence detection."""
        validator = SequenceValidator()
        
        validator.validate("stream1", 1)
        error = validator.validate("stream1", 1)  # Duplicate
        
        assert error is not None
        assert error.error_type == "duplicate"
    
    def test_detect_gap(self):
        """Test gap detection."""
        validator = SequenceValidator()
        
        validator.validate("stream1", 1)
        error = validator.validate("stream1", 5)  # Gap of 3
        
        assert error is not None
        assert error.error_type == "gap"
        assert error.expected == 2
        assert error.received == 5
    
    def test_detect_out_of_order(self):
        """Test out-of-order detection."""
        validator = SequenceValidator()
        
        validator.validate("stream1", 5)  # First message
        validator.validate("stream1", 6)  # Valid next
        error = validator.validate("stream1", 4)  # Out of order (less than 6)
        
        assert error is not None
        assert error.error_type == "out_of_order"
    
    def test_detect_initial_gap(self):
        """Test initial sequence should be 1."""
        validator = SequenceValidator()
        
        error = validator.validate("stream1", 5)  # Should start at 1
        
        assert error is not None
        assert error.error_type == "initial_gap"
    
    def test_validate_batch(self):
        """Test batch validation."""
        validator = SequenceValidator()
        
        errors = validator.validate_batch("stream1", [1, 2, 3, 4, 5])
        assert len(errors) == 0
        
        # Invalid batch with gap (stream2 is fresh)
        errors = validator.validate_batch("stream2", [1, 3, 4])
        # After 1, expects 2 but gets 3 (gap), then expects 2 but gets 4 (out of order)
        assert len(errors) == 2
    
    def test_reset_stream(self):
        """Test stream reset."""
        validator = SequenceValidator()
        
        validator.validate("stream1", 10)
        validator.reset_stream("stream1")
        
        # After reset, should accept sequence 1
        error = validator.validate("stream1", 1)
        assert error is None
    
    def test_multiple_streams(self):
        """Test managing multiple streams."""
        validator = SequenceValidator()
        
        validator.validate("stream1", 1)
        validator.validate("stream2", 1)
        validator.validate("stream1", 2)
        validator.validate("stream2", 2)
        
        active = validator.get_active_streams()
        assert len(active) == 2
    
    def test_get_validation_stats(self):
        """Test statistics collection."""
        validator = SequenceValidator()
        
        validator.validate("stream1", 1)
        validator.validate("stream1", 2)
        validator.validate("stream1", 5)  # Gap
        
        stats = validator.get_validation_stats()
        
        assert stats["total_streams"] == 1
        assert stats["total_validated"] == 3
        assert stats["total_errors"] == 1
        assert stats["overall_error_rate"] > 0
    
    def test_cleanup_inactive(self):
        """Test cleanup of inactive streams."""
        validator = SequenceValidator(auto_cleanup=True, inactive_threshold=1)
        
        validator.validate("stream1", 1)
        validator.validate("stream2", 1)
        
        # Deactivate stream2
        validator.deactivate_stream("stream2")
        
        cleaned = validator.cleanup_inactive()
        assert cleaned == 1
        assert "stream2" not in validator._streams
    
    def test_reset_all(self):
        """Test full reset."""
        validator = SequenceValidator()
        
        validator.validate("stream1", 1)
        validator.validate("stream2", 1)
        
        validator.reset_all()
        
        stats = validator.get_validation_stats()
        assert stats["total_streams"] == 0
        assert stats["total_validated"] == 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestPhase3Integration:
    """Integration tests for Phase 3 components."""
    
    def test_handler_with_sequence_validation(self):
        """Test IncrementalUpdateHandler with SequenceValidator."""
        handler = IncrementalUpdateHandler()
        validator = SequenceValidator()
        
        # Process batch with validation
        batch = IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=2,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                ),
                OrderUpdate(
                    order_id="ORD2",
                    update_type=UpdateType.ADD,
                    price=Decimal("101.00"),
                    quantity=50,
                    side="ask",
                ),
            ],
        )
        
        # Validate sequence
        error = validator.validate("SEC1", batch.sequence_start)
        assert error is None
        
        # Process batch
        applied = handler.process_batch(batch)
        assert applied == 2
        
        # Verify book state
        state = handler.get_book_state("SEC1")
        assert state is not None
        assert state.get_best_bid() == (Decimal("100.00"), 100)
        assert state.get_best_ask() == (Decimal("101.00"), 50)
        assert state.get_spread() == Decimal("1.00")
    
    def test_gap_recovery_workflow(self):
        """Test gap detection and recovery workflow."""
        handler = IncrementalUpdateHandler()
        validator = SequenceValidator()
        
        # Valid batch 1
        handler.process_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                )
            ],
        ))
        validator.validate("SEC1", 1)
        
        # Gap detected in batch 2
        try:
            handler.process_batch(IncrementalBatch(
                security_id="SEC1",
                symbol="RELIANCE",
                sequence_start=5,  # Gap!
                sequence_end=5,
                updates=[],
            ))
        except SequenceGapError:
            # Recovery: reset stream and request snapshot
            handler.reset()
            validator.reset_stream("SEC1")
        
        # After recovery, process valid batch
        handler.process_batch(IncrementalBatch(
            security_id="SEC1",
            symbol="RELIANCE",
            sequence_start=1,
            sequence_end=1,
            updates=[
                OrderUpdate(
                    order_id="ORD1",
                    update_type=UpdateType.ADD,
                    price=Decimal("100.00"),
                    quantity=100,
                    side="bid",
                )
            ],
        ))
        
        # System recovered
        state = handler.get_book_state("SEC1")
        assert state is not None
        assert state.last_sequence == 1
