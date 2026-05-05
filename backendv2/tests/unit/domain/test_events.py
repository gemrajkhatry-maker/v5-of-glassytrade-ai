"""Unit tests for domain events."""

import pytest
from app.domain.shared.event.base import DomainEvent, _generate_idempotency_key
from app.domain.shared.event.market import TickReceived
from app.domain.shared.event.analysis import AMTAnalyzed, AIAnalysisCompleted
from app.domain.shared.event.signal import SignalGenerated, SignalValidated
from app.domain.shared.event.order import OrderPlaced, OrderCancelled, FillReceived
from app.domain.shared.event.position import (
    PositionChanged, PositionOpened, PositionClosed,
)
from app.domain.shared.event.risk import (
    RiskCheckFailed, DailyLossLimitReached,
)


class TestDomainEventBase:
    """Tests for DomainEvent base class."""

    def test_has_event_id(self):
        event = DomainEvent()
        assert event.event_id is not None
        assert len(event.event_id) == 36  # UUID

    def test_has_timestamp(self):
        event = DomainEvent()
        assert event.timestamp is not None

    def test_has_idempotency_key(self):
        event = DomainEvent()
        assert event.idempotency_key is not None

    def test_is_frozen(self):
        event = DomainEvent()
        with pytest.raises(AttributeError):
            event.event_id = "new-id"

    def test_str_representation(self):
        event = DomainEvent()
        assert "DomainEvent" in str(event)

    def test_to_dict(self):
        event = DomainEvent()
        d = event.to_dict()
        assert "event_id" in d
        assert "timestamp" in d
        assert "idempotency_key" in d


class TestIdempotencyKey:
    """Tests for deterministic idempotency keys."""

    def test_same_inputs_same_key(self):
        key1 = _generate_idempotency_key("BTC", "signal-123")
        key2 = _generate_idempotency_key("BTC", "signal-123")
        assert key1 == key2

    def test_different_inputs_different_key(self):
        key1 = _generate_idempotency_key("BTC", "signal-123")
        key2 = _generate_idempotency_key("ETH", "signal-123")
        assert key1 != key2


class TestTickReceived:
    """Tests for TickReceived event."""

    def test_create(self):
        event = TickReceived(symbol="BTCUSDT", price=50000.0, volume=1.5)
        assert event.symbol == "BTCUSDT"
        assert event.price == 50000.0
        assert event.volume == 1.5

    def test_is_frozen(self):
        event = TickReceived(symbol="BTCUSDT", price=50000.0, volume=1.5)
        with pytest.raises(AttributeError):
            event.price = 99999.0

    def test_str(self):
        event = TickReceived(symbol="BTCUSDT", price=50000.0, volume=1.5)
        assert "BTCUSDT" in str(event)
        assert "50000" in str(event)


class TestAMTAnalyzed:
    """Tests for AMTAnalyzed event."""

    def test_default_values(self):
        event = AMTAnalyzed(symbol="BTCUSDT")
        assert event.symbol == "BTCUSDT"
        assert event.market_state == "BALANCED"
        assert event.poc == 0.0

    def test_with_values(self):
        event = AMTAnalyzed(
            symbol="BTCUSDT",
            market_state="IMBALANCED",
            poc=50000.0,
            value_area_high=50200.0,
            value_area_low=49800.0,
            aggression=3.5,
            has_displacement=True,
        )
        assert event.market_state == "IMBALANCED"
        assert event.poc == 50000.0
        assert event.has_displacement is True


class TestAIAnalysisCompleted:
    """Tests for AIAnalysisCompleted event."""

    def test_create_factory(self):
        event = AIAnalysisCompleted.create(
            symbol="BTCUSDT",
            direction="LONG",
            rationale="Strong absorption",
            confidence="High",
        )
        assert event.symbol == "BTCUSDT"
        assert event.direction == "LONG"
        assert event.idempotency_key is not None


class TestSignalGenerated:
    """Tests for SignalGenerated event."""

    def test_create_factory(self):
        event = SignalGenerated.create(
            symbol="BTCUSDT",
            signal_id="sig-001",
            direction="LONG",
            entry_price=50000.0,
            stop_loss=49000.0,
            take_profit=52000.0,
            position_size=0.01,
            confidence="High",
            setup_type="TREND_MODEL",
        )
        assert event.symbol == "BTCUSDT"
        assert event.direction == "LONG"
        assert event.entry_price == 50000.0
        assert event.idempotency_key == "BTCUSDT|sig-001"


class TestSignalValidated:
    """Tests for SignalValidated event."""

    def test_create_approved(self):
        event = SignalValidated.create("sig-001", "BTCUSDT", approved=True)
        assert event.validation_result == "APPROVED"

    def test_create_rejected(self):
        event = SignalValidated.create("sig-001", "BTCUSDT", approved=False, rejection_reason="Daily loss limit")
        assert event.validation_result == "REJECTED"
        assert event.rejection_reason == "Daily loss limit"


class TestOrderPlaced:
    """Tests for OrderPlaced event."""

    def test_create_factory(self):
        event = OrderPlaced.create(
            trade_id="trade-001",
            order_id="order-001",
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            price=50000.0,
            quantity=0.01,
        )
        assert event.symbol == "BTCUSDT"
        assert event.side == "BUY"
        assert event.idempotency_key == "trade-001|order-001"


class TestFillReceived:
    """Tests for FillReceived event."""

    def test_create_factory(self):
        event = FillReceived.create(
            trade_id="trade-001",
            fill_id="fill-001",
            order_id="order-001",
            symbol="BTCUSDT",
            side="BUY",
            fill_type="ENTRY",
            price=50000.0,
            quantity=0.01,
            commission=5.0,
            slippage=2.0,
        )
        assert event.fill_type == "ENTRY"
        assert event.price == 50000.0

    def test_fill_types(self):
        entry = FillReceived.create("t1", "f1", "o1", "BTC", "BUY", "ENTRY", 50000, 0.01)
        partial = FillReceived.create("t1", "f2", "o1", "BTC", "BUY", "PARTIAL", 50100, 0.005)
        exit_fill = FillReceived.create("t1", "f3", "o2", "BTC", "SELL", "EXIT", 51000, 0.005)
        assert entry.fill_type == "ENTRY"
        assert partial.fill_type == "PARTIAL"
        assert exit_fill.fill_type == "EXIT"


class TestPositionOpened:
    """Tests for PositionOpened event."""

    def test_create_factory(self):
        event = PositionOpened.create(
            trade_id="trade-001",
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
        )
        assert event.symbol == "BTCUSDT"
        assert event.side == "LONG"
        assert event.entry_price == 50000.0


class TestPositionClosed:
    """Tests for PositionClosed event."""

    def test_create_factory(self):
        event = PositionClosed.create(
            trade_id="trade-001",
            symbol="BTCUSDT",
            close_reason="TAKE_PROFIT",
            realized_pnl=1000.0,
            exit_price=52000.0,
        )
        assert event.close_reason == "TAKE_PROFIT"
        assert event.realized_pnl == 1000.0
        assert event.exit_price == 52000.0


class TestRiskEvents:
    """Tests for risk-related events."""

    def test_risk_check_failed(self):
        event = RiskCheckFailed.create(
            signal_id="sig-001",
            symbol="BTCUSDT",
            check_name="DAILY_LOSS",
            reason="Daily loss limit reached",
        )
        assert event.check_name == "DAILY_LOSS"
        assert event.reason == "Daily loss limit reached"

    def test_daily_loss_limit_reached(self):
        event = DailyLossLimitReached.create(
            symbol="BTCUSDT",
            current_loss=-5000.0,
            limit=-10000.0,
        )
        assert event.current_loss == -5000.0
        assert event.limit == -10000.0
