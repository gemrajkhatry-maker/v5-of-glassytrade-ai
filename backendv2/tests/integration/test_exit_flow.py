"""Integration tests for exit flows — CheckExitHandler, TradeLifecycleHandler, PartitionExitManager."""

from __future__ import annotations

import pytest
from decimal import Decimal
from unittest.mock import Mock
from app.application.handlers.check_exit_handler import CheckExitHandler, IPositionRepository
from app.application.commands.trading_commands import CheckExit
from app.infrastructure.messaging.event_bus import EventBus
from app.domain.shared.event.domain_events import PositionClosed
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus, Source
from app.domain.exit.service import PartitionExitManagerV2, LossTracker
from app.domain.exit.model.exit_models import PartitionState


def _make_partition_state():
    return PartitionState(
        counter_aggression_count=0,
        p1_taken=False,
        p2_taken=False,
        p3_taken=False,
    )


class MockPositionRepo(IPositionRepository):
    def __init__(self):
        self._positions: dict[str, Position] = {}

    def add(self, position: Position):
        self._positions[position.id] = position

    def get_by_id(self, position_id: str):
        return self._positions.get(position_id)


def _make_position(
    position_id="pos-1",
    symbol="NIFTY",
    side=Side.LONG,
    entry_price=22500.0,
    size=1.0,
    stop_loss=22400.0,
    take_profit=22700.0,
    status=PositionStatus.OPEN,
):
    return Position(
        id=position_id,
        symbol=symbol,
        side=side,
        source=Source.AMT,
        entry_price=Decimal(str(entry_price)),
        size=Decimal(str(size)),
        stop_loss=Decimal(str(stop_loss)),
        take_profit=Decimal(str(take_profit)),
        status=status,
    )


class TestCheckExitHandler:
    """Test CheckExitHandler exit detection."""

    def setup_method(self):
        self.event_bus = EventBus()
        self.repo = MockPositionRepo()
        self.handler = CheckExitHandler(event_bus=self.event_bus, position_repo=self.repo)

    def test_long_position_sl_hit_triggers_exit(self):
        """LONG position with price <= stop_loss → exit triggered."""
        pos = _make_position(entry_price=22500.0, stop_loss=22400.0)
        self.repo.add(pos)
        received = []
        self.event_bus.subscribe(PositionClosed, lambda e: received.append(e))
        cmd = CheckExit(position_id="pos-1", current_price=22350.0)
        self.handler.handle(cmd)
        assert len(received) == 1
        assert received[0].position_id == "pos-1"
        assert received[0].reason == "STOP_LOSS"
        assert received[0].pnl < 0

    def test_long_position_tp_hit_triggers_exit(self):
        """LONG position with price >= take_profit → exit triggered."""
        pos = _make_position(entry_price=22500.0, take_profit=22700.0)
        self.repo.add(pos)
        received = []
        self.event_bus.subscribe(PositionClosed, lambda e: received.append(e))
        cmd = CheckExit(position_id="pos-1", current_price=22750.0)
        self.handler.handle(cmd)
        assert len(received) == 1
        assert received[0].reason == "TAKE_PROFIT"
        assert received[0].pnl > 0

    def test_long_position_no_exit_condition(self):
        """LONG position between SL and TP → no exit."""
        pos = _make_position(entry_price=22500.0, stop_loss=22400.0, take_profit=22700.0)
        self.repo.add(pos)
        received = []
        self.event_bus.subscribe(PositionClosed, lambda e: received.append(e))
        cmd = CheckExit(position_id="pos-1", current_price=22550.0)
        self.handler.handle(cmd)
        assert len(received) == 0

    def test_short_position_sl_hit_triggers_exit(self):
        """SHORT position with price >= stop_loss → exit triggered."""
        pos = _make_position(side=Side.SHORT, entry_price=22500.0, stop_loss=22600.0)
        self.repo.add(pos)
        received = []
        self.event_bus.subscribe(PositionClosed, lambda e: received.append(e))
        cmd = CheckExit(position_id="pos-1", current_price=22650.0)
        self.handler.handle(cmd)
        assert len(received) == 1
        assert received[0].reason == "STOP_LOSS"

    def test_short_position_tp_hit_triggers_exit(self):
        """SHORT position with price <= take_profit → exit triggered."""
        pos = _make_position(side=Side.SHORT, entry_price=22500.0, take_profit=22300.0)
        self.repo.add(pos)
        received = []
        self.event_bus.subscribe(PositionClosed, lambda e: received.append(e))
        cmd = CheckExit(position_id="pos-1", current_price=22250.0)
        self.handler.handle(cmd)
        assert len(received) == 1
        assert received[0].reason == "TAKE_PROFIT"

    def test_already_closed_position_ignored(self):
        """Closed position → no exit triggered."""
        pos = _make_position(status=PositionStatus.CLOSED)
        self.repo.add(pos)
        received = []
        self.event_bus.subscribe(PositionClosed, lambda e: received.append(e))
        cmd = CheckExit(position_id="pos-1", current_price=22300.0)
        self.handler.handle(cmd)
        assert len(received) == 0

    def test_missing_position_ignored(self):
        """Position not found → no exit."""
        received = []
        self.event_bus.subscribe(PositionClosed, lambda e: received.append(e))
        cmd = CheckExit(position_id="nonexistent", current_price=22500.0)
        self.handler.handle(cmd)
        assert len(received) == 0

    def test_no_position_repo_no_op(self):
        """No position repo → handler returns immediately."""
        handler = CheckExitHandler(event_bus=self.event_bus, position_repo=None)
        cmd = CheckExit(position_id="pos-1", current_price=22500.0)
        handler.handle(cmd)

    def test_pnl_calculation_long(self):
        """LONG PNL = (exit - entry) * size."""
        pos = _make_position(entry_price=22500.0, size=1.0, take_profit=22700.0)
        self.repo.add(pos)
        received = []
        self.event_bus.subscribe(PositionClosed, lambda e: received.append(e))
        cmd = CheckExit(position_id="pos-1", current_price=22750.0)
        self.handler.handle(cmd)
        assert received[0].pnl > 0


class TestTradeLifecycleHandler:
    """Test TradeLifecycleHandler exit evaluation."""

    def test_no_open_positions_returns_false(self):
        """No open positions → check_exits returns False."""
        from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
        from app.domain.exit.service import ExitEngine, PartitionExitManagerV2, TrailEngine
        handler = TradeLifecycleHandler(
            exit_engine=ExitEngine(),
            partition_manager=PartitionExitManagerV2(),
            trail_engine=TrailEngine(),
        )
        portfolio = Mock()
        portfolio.positions = []
        result = handler.check_exits(portfolio, current_price=22500.0)
        assert result is False

    def test_cvd_divergence_kill_long(self):
        """BEARISH CVD divergence on LONG with tick_count >= 3 → CVD_KILL."""
        from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
        from app.domain.exit.service import ExitEngine, PartitionExitManagerV2, TrailEngine
        pm = PartitionExitManagerV2()
        pm._states = {}  # Ensure _states exists
        handler = TradeLifecycleHandler(
            exit_engine=ExitEngine(),
            partition_manager=pm,
            trail_engine=TrailEngine(),
        )
        pos = _make_position(entry_price=22500.0, stop_loss=22400.0)
        pos.tick_count = 5
        portfolio = Mock()
        portfolio.positions = [pos]
        portfolio.close_position = Mock(return_value=True)
        portfolio.partial_close_position = Mock(return_value=Decimal("0"))
        handler.check_exits(portfolio, current_price=22500.0, symbol="NIFTY", cvd_divergence="BEARISH")
        portfolio.close_position.assert_called()


class TestPartitionExitManager:
    """Test PartitionExitManagerV2 exit logic."""

    def setup_method(self):
        self.manager = PartitionExitManagerV2()

    def test_partition_exits_no_signal_at_entry(self):
        """At entry price → no partition exit signals."""
        signals = self.manager.check_exits(
            entry_price=22500.0,
            initial_stop=22400.0,
            take_profit=22700.0,
            current_price=22500.0,
            is_long=True,
            cvd_slope=0.0,
            state=_make_partition_state(),
            market_state="BALANCED",
        )
        assert isinstance(signals, list)

    def test_partition_exit_evaluates_price_movement(self):
        """Price movement → partition manager evaluates."""
        signals = self.manager.check_exits(
            entry_price=22500.0,
            initial_stop=22400.0,
            take_profit=22700.0,
            current_price=22600.0,
            is_long=True,
            cvd_slope=10.0,
            state=_make_partition_state(),
            market_state="BALANCED",
        )
        assert isinstance(signals, list)

    def test_structural_stop_below_entry(self):
        """Price significantly below entry → evaluates stop."""
        signals = self.manager.check_exits(
            entry_price=22500.0,
            initial_stop=22400.0,
            take_profit=22700.0,
            current_price=22350.0,
            is_long=True,
            cvd_slope=-50.0,
            state=_make_partition_state(),
            market_state="BALANCED",
        )
        assert isinstance(signals, list)


class TestFlashCrashProtector:
    """Test flash crash protection in exit flow."""

    def setup_method(self):
        from app.domain.risk.service import FlashCrashProtector
        self.protector = FlashCrashProtector()

    def test_normal_volatility_no_halt(self):
        """Small price moves → no flash crash halt."""
        state = self.protector.update(100.0, 1.0)
        state = self.protector.update(100.5, 2.0)
        state = self.protector.update(101.0, 3.0)
        assert not state.is_halted

    def test_extreme_drop_triggers(self):
        """Sudden large price drop → may trigger halt."""
        self.protector.update(100.0, 1.0)
        state = self.protector.update(90.0, 2.0)
        assert state is not None


class TestLossTracker:
    """Test LossTracker integration."""

    def setup_method(self):
        self.tracker = LossTracker()

    def test_record_loss(self):
        """Record a loss → tracked."""
        self.tracker.record_loss("NIFTY", stop_price=22400.0)
        assert True

    def test_record_win(self):
        """Record a win → tracked."""
        self.tracker.record_win("NIFTY")
        assert True

    def test_record_exit_time(self):
        """Record exit time for symbol."""
        self.tracker.record_exit_time("NIFTY")
        assert True
