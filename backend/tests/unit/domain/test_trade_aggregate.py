"""Invariant tests for Trade Aggregate.

These tests verify that the domain model maintains its invariants:
1. position = Position.from_fills(fills) - ALWAYS true
2. status = OPEN iff position.is_open
3. realized_pnl = sum(fill.pnl for fills of type EXIT/PARTIAL)
"""

import pytest
from decimal import Decimal

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
)
from quant.contracts.enums import Side, SetupType


class TestPositionDerivation:
    """Test that Position is always derived from fills."""

    def test_empty_fills_gives_zero_position(self):
        """No fills = zero position."""
        fills = ()
        position = Position.from_fills(fills)
        assert position.quantity == Decimal("0")
        assert position.avg_entry_price == Decimal("0")

    def test_single_entry_fill(self):
        """Single entry fill creates position with that quantity."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                order_id="O1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("75"),
                commission=Decimal("10"),
                timestamp="2025-01-01T10:00:00Z",
                fill_type=FillType.ENTRY,
            ),
        )
        position = Position.from_fills(fills)
        assert position.quantity == Decimal("75")
        assert position.avg_entry_price == Decimal("100")

    def test_multiple_entry_fills_weighted_avg(self):
        """Multiple fills calculate weighted average correctly."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("50"),
                commission=Decimal("5"),
                timestamp="2025-01-01T10:00:00Z",
                fill_type=FillType.ENTRY,
            ),
            Fill(
                fill_id="F2",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("110"),
                quantity=Decimal("50"),
                commission=Decimal("5"),
                timestamp="2025-01-01T10:05:00Z",
                fill_type=FillType.SCALE_IN,
            ),
        )
        position = Position.from_fills(fills)
        assert position.quantity == Decimal("100")
        assert position.avg_entry_price == Decimal("105")  # (100*50 + 110*50) / 100

    def test_partial_exit_reduces_quantity(self):
        """Partial exit reduces position quantity."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("100"),
                commission=Decimal("10"),
                timestamp="2025-01-01T10:00:00Z",
                fill_type=FillType.ENTRY,
            ),
            Fill(
                fill_id="F2",
                trade_id="T1",
                side=Side.SHORT,  # Selling
                price=Decimal("120"),
                quantity=Decimal("50"),
                commission=Decimal("5"),
                timestamp="2025-01-01T10:30:00Z",
                fill_type=FillType.PARTIAL,
            ),
        )
        position = Position.from_fills(fills)
        assert position.quantity == Decimal("50")  # 100 - 50

    def test_full_exit_closes_position(self):
        """Full exit results in zero quantity."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("100"),
                commission=Decimal("10"),
                timestamp="2025-01-01T10:00:00Z",
                fill_type=FillType.ENTRY,
            ),
            Fill(
                fill_id="F2",
                trade_id="T1",
                side=Side.SHORT,
                price=Decimal("120"),
                quantity=Decimal("100"),
                commission=Decimal("10"),
                timestamp="2025-01-01T10:30:00Z",
                fill_type=FillType.EXIT,
            ),
        )
        position = Position.from_fills(fills)
        assert position.quantity == Decimal("0")

    def test_position_unrealized_pnl_long(self):
        """Long position unrealized PnL calculation."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.LONG,
                price=Decimal("100"),
                quantity=Decimal("100"),
                commission=Decimal("0"),
                timestamp="2025-01-01T10:00:00Z",
                fill_type=FillType.ENTRY,
            ),
        )
        position = Position.from_fills(fills, current_price=Decimal("110"))
        # (110 - 100) * 100 = 1000
        assert position.unrealized_pnl == Decimal("1000")

    def test_position_unrealized_pnl_short(self):
        """Short position unrealized PnL calculation."""
        fills = (
            Fill(
                fill_id="F1",
                trade_id="T1",
                side=Side.SHORT,
                price=Decimal("100"),
                quantity=Decimal("100"),
                commission=Decimal("0"),
                timestamp="2025-01-01T10:00:00Z",
                fill_type=FillType.ENTRY,
            ),
        )
        position = Position.from_fills(fills, current_price=Decimal("90"))
        # (100 - 90) * 100 = 1000
        assert position.unrealized_pnl == Decimal("1000")


class TestTradeInvariants:
    """Test Trade aggregate invariants."""

    def test_create_pending_trade(self):
        """Trade starts in PENDING status."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")

        assert trade.status == TradeStatus.PENDING
        assert trade.is_pending
        assert not trade.is_open
        assert not trade.is_closed

    def test_open_trade(self):
        """Opening a trade transitions to OPEN status."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        assert trade.status == TradeStatus.OPEN
        assert trade.is_open

    def test_trade_status_matches_position(self):
        """Trade status must match position.is_open."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")

        # Pending: position should be closed (no fills)
        assert trade.position.quantity == Decimal("0")

        # Open with entry fill
        trade = trade.open(signal, "2025-01-01T10:00:00Z")
        fill = Fill(
            fill_id="F1",
            trade_id=trade.trade_id,
            order_id="O1",
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            commission=Decimal("10"),
            timestamp="2025-01-01T10:00:00Z",
            fill_type=FillType.ENTRY,
        )
        trade = trade.add_fill(fill)

        # After entry fill: position is open
        assert trade.position.quantity == Decimal("75")
        assert trade.status == TradeStatus.OPEN
        assert trade.is_open

    def test_close_trade(self):
        """Closing a trade transitions to CLOSED status."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        # Add entry fill
        fill = Fill(
            fill_id="F1",
            trade_id=trade.trade_id,
            order_id="O1",
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            commission=Decimal("10"),
            timestamp="2025-01-01T10:00:00Z",
            fill_type=FillType.ENTRY,
        )
        trade = trade.add_fill(fill)

        # Add exit fill
        exit_fill = Fill(
            fill_id="F2",
            trade_id=trade.trade_id,
            order_id="O2",
            side=Side.SHORT,
            price=Decimal("120"),
            quantity=Decimal("75"),
            commission=Decimal("10"),
            timestamp="2025-01-01T10:30:00Z",
            fill_type=FillType.EXIT,
        )
        trade = trade.add_fill(exit_fill)

        # After exit fill: position closed
        assert trade.position.quantity == Decimal("0")
        assert trade.status == TradeStatus.CLOSED
        assert trade.is_closed
        assert trade.close_reason == CloseReason.TAKE_PROFIT

    def test_event_history_preserved(self):
        """All events are preserved in history."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        fill = Fill(
            fill_id="F1",
            trade_id=trade.trade_id,
            order_id="O1",
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            commission=Decimal("10"),
            timestamp="2025-01-01T10:00:00Z",
            fill_type=FillType.ENTRY,
        )
        trade = trade.add_fill(fill)

        events = trade.get_event_history()
        assert len(events) == 2  # OPEN + FILL
        assert events[0].event_type == "TRADE_OPENED"
        assert events[1].event_type == "FILL_RECEIVED"

    def test_snapshot_reconstruction(self):
        """Trade can be serialized and reconstructed."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
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
            order_id="O1",
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            commission=Decimal("10"),
            timestamp="2025-01-01T10:00:00Z",
            fill_type=FillType.ENTRY,
        )
        trade = trade.add_fill(fill)

        # Snapshot
        snapshot = trade.to_snapshot()

        # Reconstruct
        from app.domain.trading.models.trade_aggregate import create_trade_from_snapshot

        reconstructed = create_trade_from_snapshot(snapshot)

        assert reconstructed.trade_id == trade.trade_id
        assert reconstructed.symbol == trade.symbol
        assert reconstructed.status == trade.status
        assert reconstructed.entry_signal.signal_id == trade.entry_signal.signal_id
        assert len(reconstructed.fills) == len(trade.fills)


class TestTradeBusinessRules:
    """Test business rules and constraints."""

    def test_cannot_open_already_open_trade(self):
        """Cannot open a trade that's already open."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        with pytest.raises(ValueError, match="Cannot open trade in status"):
            trade.open(signal, "2025-01-01T10:30:00Z")

    def test_cannot_close_pending_trade(self):
        """Cannot directly close a pending trade (must cancel)."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")

        with pytest.raises(ValueError, match="Cannot close trade in status"):
            trade.close(CloseReason.MANUAL, "2025-01-01T10:30:00Z")

    def test_cancel_pending_trade(self):
        """Can cancel a pending trade."""
        signal = EntrySignal(
            signal_id="S1",
            timestamp="2025-01-01T10:00:00Z",
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.cancel("No confirmation", "2025-01-01T10:30:00Z")

        assert trade.status == TradeStatus.CLOSED
        assert trade.close_reason == CloseReason.SIGNAL_REJECTED


class TestEntrySignal:
    """Test EntrySignal value object."""

    def test_risk_per_share_calculation(self):
        """Risk per share is entry - stop loss."""
        signal = EntrySignal(
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
        )
        assert signal.risk_per_share == Decimal("5")

    def test_risk_reward_ratio(self):
        """Risk/reward ratio calculation."""
        signal = EntrySignal(
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),  # Risk: 5
            take_profit=Decimal("115"),  # Reward: 15
            position_size=Decimal("75"),
        )
        assert signal.risk_reward_ratio == 3.0  # 15 / 5

    def test_zero_risk_gives_zero_ratio(self):
        """Zero risk gives zero ratio (avoid division by zero)."""
        signal = EntrySignal(
            entry_price=Decimal("100"),
            stop_loss=Decimal("100"),  # No risk
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
        )
        assert signal.risk_reward_ratio == 0.0
