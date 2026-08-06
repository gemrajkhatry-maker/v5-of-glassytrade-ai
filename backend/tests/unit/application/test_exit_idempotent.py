"""Tests for ExitCoordinator.on_position_closed idempotency (AMT cleanup Task 6).

Both the tick path (``TradingSessionService._handle_closed_positions``) and the
SL watchdog force-close path route through ``ExitCoordinator.on_position_closed``.
A guard on ``position.id`` must make the second call a no-op so learning,
post-trade analysis, risk recording and storage persistence run exactly once.
"""

from __future__ import annotations

from decimal import Decimal

from app.application.services.exit_coordinator import ExitCoordinator
from app.application.services.session_state_manager import SessionStateManager
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import PositionStatus, Side, Source


class FakeExitEngine:
    def get_position_metrics(self, *_args, **_kwargs):
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


class FakePostTradeAnalyst:
    def __init__(self):
        self.analyze_calls = []

    def analyze(self, **kwargs):
        self.analyze_calls.append(kwargs)


class FakeLearningEngine:
    def __init__(self):
        self.learn_calls = []

    def learn(self, position):
        self.learn_calls.append(position)


class FakeBroker:
    def cancel_order(self, *_args, **_kwargs):
        pass


def _make_position(position_id: str, symbol: str = "NIFTY") -> Position:
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
        metadata={"tick_trace_id": f"trace-{position_id}"},
    )


def _make_coordinator():
    lifecycle_handler = FakeLifecycleHandler()
    event_logger = FakeEventLogger()
    risk_manager = FakeRiskManager()
    risk_coordinator = FakeRiskCoordinator(risk_manager)
    storage = FakeStorage()
    post_trade = FakePostTradeAnalyst()

    coordinator = ExitCoordinator(
        broker=FakeBroker(),
        lifecycle_handler=lifecycle_handler,
        event_logger=event_logger,
        overseer_handler=FakeOverseer(),
        state_manager=SessionStateManager(),
        storage=storage,
        llm_handler=FakeLLMHandler(),
        risk_coordinator=risk_coordinator,
        post_trade_analyst=post_trade,
    )
    return coordinator, post_trade, event_logger, risk_manager, storage


def _session_for(coordinator, symbol: str):
    session_manager = coordinator._state_manager
    session = session_manager.get_or_create_session(symbol)
    session.learning = FakeLearningEngine()
    return session


def test_on_position_closed_is_idempotent():
    coordinator, post_trade, event_logger, risk_manager, storage = _make_coordinator()
    session = _session_for(coordinator, "NIFTY")
    position = _make_position("pos-idem")
    session.portfolio.positions.append(position)

    coordinator.on_position_closed("NIFTY", position, session=session)
    coordinator.on_position_closed("NIFTY", position, session=session)  # no-op

    assert len(post_trade.analyze_calls) == 1
    assert len(event_logger.log_exit_calls) == 1
    assert risk_manager.record_trade_calls == [position.pnl]
    assert storage.delete_open_position_calls == [position.id]
    assert session.learning.learn_calls == [position]
    assert coordinator._recorded_close_ids == {position.id}


def test_on_position_closed_idempotent_by_position_id():
    coordinator, post_trade, event_logger, _risk_manager, storage = _make_coordinator()
    session = _session_for(coordinator, "BANKNIFTY")
    position = _make_position("pos-by-id", symbol="BANKNIFTY")
    session.portfolio.positions.append(position)

    coordinator.on_position_closed("", "pos-by-id")
    coordinator.on_position_closed("", "pos-by-id")  # no-op

    assert len(post_trade.analyze_calls) == 1
    assert len(event_logger.log_exit_calls) == 1
    assert storage.delete_open_position_calls == ["pos-by-id"]


def test_on_position_closed_distinct_positions_both_handled():
    coordinator, post_trade, _event_logger, _risk_manager, storage = _make_coordinator()
    session = _session_for(coordinator, "NIFTY")
    pos1 = _make_position("pos-a")
    pos2 = _make_position("pos-b")
    session.portfolio.positions.append(pos1)
    session.portfolio.positions.append(pos2)

    coordinator.on_position_closed("NIFTY", pos1, session=session)
    coordinator.on_position_closed("NIFTY", pos2, session=session)

    assert len(post_trade.analyze_calls) == 2
    assert set(storage.delete_open_position_calls) == {"pos-a", "pos-b"}
    assert coordinator._recorded_close_ids == {"pos-a", "pos-b"}


def test_on_position_closed_stale_id_still_noop():
    coordinator, post_trade, event_logger, _risk_manager, storage = _make_coordinator()
    _session_for(coordinator, "NIFTY")

    coordinator.on_position_closed("NIFTY", "pos-stale")
    coordinator.on_position_closed("NIFTY", "pos-stale")

    assert len(post_trade.analyze_calls) == 0
    assert len(event_logger.log_exit_calls) == 0
    assert storage.delete_open_position_calls == []
    assert coordinator._recorded_close_ids == set()
