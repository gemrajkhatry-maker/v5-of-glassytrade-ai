"""Unit tests for Position domain model."""
import pytest
from decimal import Decimal
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus, CushionState


class TestPosition:
    """Tests for Position entity following TDD principles."""

    def test_create_position_open(self):
        """Test that position is created in OPEN status."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.001,
            stop_loss=49000.0,
            take_profit=51000.0,
        )
        assert position.symbol == "BTCUSDT"
        assert position.side == Side.LONG
        assert position.status == PositionStatus.OPEN
        assert position.entry_price == Decimal("50000")

    def test_position_is_mutable(self):
        """Test that position can be mutated (entity, not value object)."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.001,
            stop_loss=49000.0,
            take_profit=51000.0,
        )
        # Entities are mutable
        position.pnl = Decimal("100")
        assert position.pnl == Decimal("100")

    def test_close_changes_status(self):
        """Test that closing position changes status."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.001,
            stop_loss=49000.0,
            take_profit=51000.0,
        )
        position.close(Decimal("51000"), "2026-01-01T00:00:00", "TAKE_PROFIT")
        assert position.status == PositionStatus.CLOSED
        assert position.exit_price == Decimal("51000")

    def test_risk_reward_calculation(self):
        """Test risk-reward ratio calculation."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.001,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        assert position.risk_reward == 2.0

    def test_risk_reward_zero_risk(self):
        """Test risk-reward when entry equals stop loss."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.001,
            stop_loss=50000.0,
            take_profit=51000.0,
        )
        assert position.risk_reward == 0.0

    def test_is_long_short_helpers(self):
        """Test side helper methods."""
        long_position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.001,
            stop_loss=49000.0,
            take_profit=51000.0,
        )
        short_position = Position.open(
            symbol="BTCUSDT",
            side=Side.SHORT,
            entry_price=50000.0,
            size=0.001,
            stop_loss=51000.0,
            take_profit=49000.0,
        )
        assert long_position.is_long is True
        assert long_position.is_short is False
        assert short_position.is_long is False
        assert short_position.is_short is True

    def test_update_pnl_long(self):
        """Test PnL update for long position."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.01,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        pnl = position.update_pnl(51000.0)
        assert pnl == Decimal("10.0")

    def test_update_pnl_short(self):
        """Test PnL update for short position."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.SHORT,
            entry_price=50000.0,
            size=0.01,
            stop_loss=51000.0,
            take_profit=48000.0,
        )
        pnl = position.update_pnl(49000.0)
        assert pnl == Decimal("10.0")

    def test_should_close_stop_loss_long(self):
        """Test stop loss detection for long position."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.01,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        should_close, reason = position.should_close(Decimal("48900"))
        assert should_close is True
        assert "Stop" in reason

    def test_should_close_take_profit_long(self):
        """Test take profit detection for long position."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.01,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        should_close, reason = position.should_close(Decimal("52100"))
        assert should_close is True
        assert "Profit" in reason

    def test_should_not_close_within_range(self):
        """Test no close when price is within range."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.01,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        should_close, _ = position.should_close(Decimal("50500"))
        assert should_close is False

    def test_cushion_state_transitions(self):
        """Test cushion state machine."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.01,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        assert position.cushion_state == CushionState.OPEN
        assert position.validate_cushion_transition(CushionState.CUSHIONED) is True
        assert position.validate_cushion_transition(CushionState.TRAILING) is False
        position.advance_cushion_state(CushionState.CUSHIONED)
        assert position.cushion_state == CushionState.CUSHIONED
        position.advance_cushion_state(CushionState.TRAILING)
        assert position.cushion_state == CushionState.TRAILING

    def test_from_signal_factory(self):
        """Test creating position from signal."""
        from app.domain.trading.model.entities import Signal
        from app.domain.trading.model.enums import SignalType, SetupType, Source
        signal = Signal.create(
            type=SignalType.BUY, price=50000, reason="test",
            stop_loss=49000, take_profit=52000, timestamp="2026-01-01T00:00:00",
            setup=SetupType.TREND_MODEL, source=Source.AMT,
        )
        position = Position.from_signal(signal, "BTCUSDT", Decimal("0.01"))
        assert position.symbol == "BTCUSDT"
        assert position.side == Side.LONG
        assert position.entry_price == Decimal("50000")
        assert position.is_open is True
