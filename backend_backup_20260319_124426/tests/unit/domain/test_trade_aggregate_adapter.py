"""Tests for Trade Aggregate Adapter."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.domain.trading.models.enums import Side, SetupType
from app.domain.trading.models.trade_aggregate import (
    Trade,
    TradeStatus,
    Direction,
    FillType,
    EntrySignal,
    Fill,
    CloseReason,
    Confidence,
    create_trade,
)
from app.domain.trading.services.trade_aggregate_adapter import (
    ManagedPositionAdapter,
    TradeAggregateService,
    create_trade_aggregate_service,
)
from app.domain.trading.event_store import EventBus


class TestManagedPositionAdapter:
    """Tests for ManagedPositionAdapter."""

    def test_adapter_exposes_trade_properties(self):
        """Adapter correctly exposes Trade properties."""
        signal = EntrySignal(
            direction=Direction.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("115"),
            position_size=Decimal("75"),
            confidence=Confidence.HIGH,
        )
        trade = create_trade("NIFTY", signal, "2025-01-01T10:00:00Z")
        trade = trade.open(signal, "2025-01-01T10:00:00Z")

        adapter = ManagedPositionAdapter(trade=trade)

        assert adapter.position_id == trade.trade_id
        assert adapter.symbol == "NIFTY"
        assert adapter.side == "LONG"
        assert adapter.is_long is True
        assert adapter.entry_price == 100.0
        assert adapter.stop_loss == 95.0
        assert adapter.take_profit == 115.0

    def test_adapter_with_fill(self):
        """Adapter correctly exposes position after fill."""
        signal = EntrySignal(
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
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            fill_type=FillType.ENTRY,
            timestamp="2025-01-01T10:00:00Z",
        )
        trade = trade.add_fill(fill)

        adapter = ManagedPositionAdapter(trade=trade)

        assert adapter.quantity == 75.0
        assert adapter.is_open is True

    def test_adapter_close_trade(self):
        """Adapter can close trade."""
        signal = EntrySignal(
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
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            fill_type=FillType.ENTRY,
            timestamp="2025-01-01T10:00:00Z",
        )
        trade = trade.add_fill(fill)

        adapter = ManagedPositionAdapter(trade=trade)

        # Close the trade
        closed_trade = adapter.close("TP", "2025-01-01T10:30:00Z")

        assert closed_trade.status == TradeStatus.CLOSED
        assert closed_trade.close_reason == CloseReason.TAKE_PROFIT


class TestTradeAggregateService:
    """Tests for TradeAggregateService."""

    def test_create_trade(self):
        """Service can create trades."""
        service = create_trade_aggregate_service()

        adapter = service.create_trade(
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            setup_type=SetupType.TREND_MODEL,
            confidence="HIGH",
        )

        assert adapter.symbol == "NIFTY"
        assert service.get_trade_count() == 1

    def test_get_open_trades(self):
        """Service can filter open trades."""
        service = create_trade_aggregate_service()

        # Create and open a trade
        adapter = service.create_trade(
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            setup_type=SetupType.TREND_MODEL,
            confidence="HIGH",
        )

        # The trade is created in PENDING status, need to open it
        trade = service.get_trade(adapter.position_id)
        assert trade is not None

        # Open the trade
        if trade and trade.entry_signal:
            trade = trade.open(trade.entry_signal, "2025-01-01T10:00:00Z")
            service._trades[adapter.position_id] = trade

        open_trades = service.get_open_trades()

        assert len(open_trades) == 1
        assert open_trades[0].symbol == "NIFTY"

    def test_snapshot_and_restore(self):
        """Service can serialize and deserialize trades."""
        service = create_trade_aggregate_service()

        # Create a trade
        adapter = service.create_trade(
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            setup_type=SetupType.TREND_MODEL,
            confidence="HIGH",
        )

        trade_id = adapter.position_id

        # Snapshot
        snapshot = service.to_snapshot()

        # Restore
        service2 = create_trade_aggregate_service()
        service2.from_snapshot(snapshot)

        restored = service2.get_trade(trade_id)
        assert restored is not None
        assert restored.symbol == "NIFTY"


class TestEventPublishing:
    """Tests for event publishing."""

    def test_events_published_on_create(self):
        """Events are published when trade is created."""
        event_bus = EventBus()
        service = TradeAggregateService(event_bus=event_bus)

        received = []
        event_bus.subscribe("SignalGenerated", lambda e: received.append(e))

        service.create_trade(
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            setup_type=SetupType.TREND_MODEL,
            confidence="HIGH",
        )

        assert len(received) == 1
        assert received[0].symbol == "NIFTY"

    def test_events_published_on_fill(self):
        """Events are published when fill is added."""
        event_bus = EventBus()
        service = TradeAggregateService(event_bus=event_bus)

        received = []
        event_bus.subscribe("FillReceived", lambda e: received.append(e))

        adapter = service.create_trade(
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            setup_type=SetupType.TREND_MODEL,
            confidence="HIGH",
        )

        fill = Fill(
            fill_id="F1",
            trade_id=adapter.position_id,
            symbol="NIFTY",  # Added symbol
            side=Side.LONG,
            price=Decimal("100"),
            quantity=Decimal("75"),
            fill_type=FillType.ENTRY,
            timestamp="2025-01-01T10:00:00Z",
        )

        adapter.add_fill(fill)

        assert len(received) == 1
        assert received[0].trade_id == adapter.position_id
