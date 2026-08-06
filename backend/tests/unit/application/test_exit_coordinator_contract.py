"""Contract tests for ExitCoordinator close-path handling."""

from __future__ import annotations

from decimal import Decimal

from app.application.services.exit_coordinator import ExitCoordinator
from app.application.services.session_state_manager import SessionStateManager
from quant.contracts.entities import Position
from quant.contracts.enums import PositionStatus, Side, Source


class FakeExitEngine:
    def __init__(self):
        self.get_position_metrics_calls = 0

    def get_position_metrics(self, *_args, **_kwargs):
        self.get_position_metrics_calls += 1
        return {"tick_count": 5, "mfe": 2.0, "mae": 1.0}


class FakeLifecycleHandler:
    def __init__(self):
        self.exit_engine = FakeExitEngine()


class FakeEventLogger:
    def __init__(self):
        self.log_exit_calls = []

    def log_exit(self, **kwargs):
        self.log_exit_calls.append(kwargs)

    def log_partial_exit(self, **_kwargs):
        pass

    def log_break_even_triggered(self, **_kwargs):
        pass

    def log_position_event(self, **_kwargs):
        pass

    def log_rejection(self, **_kwargs):
        pass

    def log_entry(self, **_kwargs):
        pass


class FakeRiskManager:
    def __init__(self):
        self.record_trade_calls = []
        self.value = "NORMAL"
        self.stop_loss_pct = 0.02
        self.session_pnl = 120.0
        self.consecutive_wins = 3
        self.consecutive_losses = 1
        self.risk_tier = self

    def record_trade(self, pnl: float):
        self.record_trade_calls.append(pnl)


class FakeRiskCoordinator:
    def __init__(self, manager: FakeRiskManager):
        self._manager = manager
        self.get_session_risk_manager_calls = []
        self.persist_risk_state_calls = []

    def get_session_risk_manager(self, symbol: str):
        self.get_session_risk_manager_calls.append(symbol)
        return self._manager

    def persist_risk_state(self, symbol: str):
        self.persist_risk_state_calls.append(symbol)


class FakeStorage:
    def __init__(self):
        self.delete_open_position_calls = []

    def delete_open_position(self, position_id: str):
        self.delete_open_position_calls.append(position_id)


class FakeLLMHandler:
    def __init__(self):
        self.record_successful_exit_calls = []

    def record_successful_exit(self, **kwargs):
        self.record_successful_exit_calls.append(kwargs)

    def record_stop_out(self, *args, **kwargs):
        pass


class FakeOverseer:
    def reset_position_state(self):
        pass


class FakeLearningEngine:
    def __init__(self):
        self.learn_calls = []

    def learn(self, position):
        self.learn_calls.append(position)


class FakeBroker:
    def cancel_order(self, *_args, **_kwargs):
        pass


def _make_position(position_id: str, tick_trace_id: str, symbol: str = "NIFTY") -> Position:
    return Position(
        id=position_id,
        symbol=symbol,
        side=Side.LONG,
        source=Source.LLM,
        entry_price=Decimal("100"),
        size=Decimal("1"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        entry_time="2026-01-01T09:00:00Z",
        exit_time="2026-01-01T10:00:00Z",
        status=PositionStatus.CLOSED,
        pnl=Decimal("12.5"),
        metadata={"tick_trace_id": tick_trace_id},
    )


def _make_coordinator():
    lifecycle_handler = FakeLifecycleHandler()
    event_logger = FakeEventLogger()
    risk_manager = FakeRiskManager()
    risk_coordinator = FakeRiskCoordinator(risk_manager)
    storage = FakeStorage()

    return ExitCoordinator(
        broker=FakeBroker(),
        lifecycle_handler=lifecycle_handler,
        event_logger=event_logger,
        overseer_handler=FakeOverseer(),
        state_manager=SessionStateManager(),
        storage=storage,
        llm_handler=FakeLLMHandler(),
        risk_coordinator=risk_coordinator,
        post_trade_analyst=None,
    ), event_logger, risk_coordinator, risk_manager, lifecycle_handler, storage


def test_position_close_accepts_position_object_and_preserves_tick_trace():
    coordinator, event_logger, risk_coordinator, risk_manager, lifecycle_handler, storage = (
        _make_coordinator()
    )
    session_manager = coordinator._state_manager
    session = session_manager.get_or_create_session("NIFTY")
    session.learning = FakeLearningEngine()
    coordinator._state_manager.get_or_create_session("NIFTY").learning = session.learning

    position = _make_position("pos-object", tick_trace_id="trace-object")
    session.portfolio.positions.append(position)

    coordinator.on_position_closed("NIFTY", position, session=session)

    assert len(event_logger.log_exit_calls) == 1
    log_args = event_logger.log_exit_calls[-1]
    assert log_args["tick_trace_id"] == "trace-object"
    assert log_args["position"] is position
    assert log_args["symbol"] == "NIFTY"
    assert log_args["time_in_trade"] >= 0.0
    assert session.learning.learn_calls == [position]
    assert risk_coordinator.get_session_risk_manager_calls == ["NIFTY"]
    assert risk_manager.record_trade_calls == [position.pnl]
    assert risk_coordinator.persist_risk_state_calls == ["NIFTY"]
    assert storage.delete_open_position_calls == [position.id]


def test_position_close_accepts_position_id_from_session_manager():
    coordinator, event_logger, risk_coordinator, _risk_manager, _lifecycle_handler, storage = (
        _make_coordinator()
    )
    session_manager = coordinator._state_manager
    session = session_manager.get_or_create_session("BANKNIFTY")
    session.learning = FakeLearningEngine()
    position = _make_position("pos-id", tick_trace_id="trace-id", symbol="BANKNIFTY")
    session.portfolio.positions.append(position)

    coordinator.on_position_closed("", "pos-id")

    assert len(event_logger.log_exit_calls) == 1
    log_args = event_logger.log_exit_calls[-1]
    assert log_args["tick_trace_id"] == "trace-id"
    assert risk_coordinator.get_session_risk_manager_calls == ["BANKNIFTY"]
    assert storage.delete_open_position_calls == ["pos-id"]


def test_position_close_stale_id_is_noop():
    coordinator, event_logger, risk_coordinator, _risk_manager, _lifecycle_handler, storage = (
        _make_coordinator()
    )
    session_manager = coordinator._state_manager
    session = session_manager.get_or_create_session("NIFTY")
    session.learning = FakeLearningEngine()
    session.portfolio.positions.append(
        _make_position("pos-existing", tick_trace_id="trace-existing", symbol="NIFTY")
    )

    coordinator.on_position_closed("NIFTY", "pos-stale")

    assert len(event_logger.log_exit_calls) == 0
    assert risk_coordinator.get_session_risk_manager_calls == []
    assert storage.delete_open_position_calls == []
