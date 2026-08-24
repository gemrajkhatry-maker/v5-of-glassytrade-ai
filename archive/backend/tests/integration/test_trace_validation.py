"""Regression test for tick_trace_id continuity through critical runtime paths."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

from app.application.services.session_event_router import SessionEventRouter
from app.application.services.session_state_manager import SessionStateManager
from app.application.services.entry_coordinator import EntryCoordinator
from app.application.services.session_event_logger import SessionEventLogger
from app.application.services.exit_coordinator import ExitCoordinator
from quant.contracts.entities import Position, Signal
from quant.contracts.enums import PositionStatus, SetupType, SignalType, Side, Source
from quant.contracts.value_objects import AMTResult, OHLC
from quant.contracts.events import TickReceived


class _FakeTradeJournal:
    def __init__(self) -> None:
        self.entry_calls: list[dict] = []
        self.exit_calls: list[dict] = []
        self.partial_exit_calls: list[dict] = []
        self.break_even_calls: list[dict] = []
        self.signal_calls: list[dict] = []
        self.rejection_calls: list[dict] = []

    def log_entry(self, **kwargs) -> None:
        self.entry_calls.append(kwargs)

    def log_exit(self, **kwargs) -> None:
        self.exit_calls.append(kwargs)

    def log_partial_exit(self, **kwargs) -> None:
        self.partial_exit_calls.append(kwargs)

    def log_break_even_move(self, **kwargs) -> None:
        self.break_even_calls.append(kwargs)

    def log_signal(self, **kwargs) -> None:
        self.signal_calls.append(kwargs)

    def log_rejection(self, **kwargs) -> None:
        self.rejection_calls.append(kwargs)


class _FakeSignalTracker:
    def __init__(self) -> None:
        self.generated_calls: list[dict] = []
        self.blocked_calls: list[dict] = []

    def track_signal_generated(self, **kwargs) -> None:
        self.generated_calls.append(kwargs)

    def track_gate_block(self, **kwargs) -> None:
        self.blocked_calls.append(kwargs)


class _FakeEventLogger:
    def __init__(self) -> None:
        self.entry_calls: list[dict] = []
        self.position_event_calls: list[dict] = []

    def _decision_attribution(self, *_args, **_kwargs) -> tuple[str, str]:
        return "llm", "model"

    def log_entry(self, **kwargs) -> None:
        self.entry_calls.append(kwargs)

    def log_position_event(self, **kwargs) -> None:
        self.position_event_calls.append(kwargs)

    def log_rejection(self, **_kwargs) -> None:
        return None


class _FakeLifecycleHandler:
    def initialize_partition_state(self, position_id, symbol) -> None:
        return None


class _FakeBroker:
    def execute_order(self, *_args, **_kwargs):
        return Position(
            id="trace-pos",
            symbol="NIFTY",
            side=Side.LONG,
            source=Source.AMT,
            entry_price=Decimal("100"),
            size=Decimal("1"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("110"),
            entry_time="2026-01-01T09:00:00Z",
        )

    def cancel_order(self, *_args, **_kwargs):
        return None


class _FakeStorage:
    def __init__(self) -> None:
        self.open_positions: list[dict] = []
        self.delete_open_position_calls: list[str] = []

    def save_open_position(self, payload) -> None:
        self.open_positions.append(payload)

    def delete_open_position(self, position_id: str) -> None:
        self.delete_open_position_calls.append(position_id)


class _FakeExchangeConfig:
    def __init__(self) -> None:
        self.max_distance_to_level_ticks = 3.0

    def get_tick_size(self, *_args, **_kwargs) -> float:
        return 0.05


class _FakeRiskManager:
    can_trade = True
    halt_reason = None
    stop_loss_pct = 0.02
    risk_tier = "NORMAL"


class _FakeSessionRiskCoordinator:
    def __init__(self) -> None:
        self.manager = _FakeRiskManager()

    def get_session_risk_manager(self, *_args, **_kwargs):
        return self.manager

    def validate_entry(self, *_args, **_kwargs) -> bool:
        return True


class _FakeRiskManagerForClose:
    def __init__(self) -> None:
        self.record_trade_calls = []
        self.value = "NORMAL"
        self.stop_loss_pct = 0.02
        self.session_pnl = 0.0
        self.consecutive_wins = 0
        self.consecutive_losses = 0

        class _RiskTier:
            value = "NORMAL"

        self.risk_tier = _RiskTier()

    def record_trade(self, pnl: float):
        self.record_trade_calls.append(pnl)


class _FakeRiskCoordinatorForClose:
    def __init__(self, manager: _FakeRiskManagerForClose) -> None:
        self._manager = manager
        self.get_session_risk_manager_calls = []
        self.persist_risk_state_calls = []

    def get_session_risk_manager(self, symbol: str):
        self.get_session_risk_manager_calls.append(symbol)
        return self._manager

    def persist_risk_state(self, symbol: str):
        self.persist_risk_state_calls.append(symbol)


class _FakeLifecycleEngineForClose:
    def get_position_metrics(self, *_args, **_kwargs):
        return {"tick_count": 5, "mfe": 2.0, "mae": 1.0}


class _FakeLifecycleHandlerForClose:
    def __init__(self) -> None:
        self.exit_engine = _FakeLifecycleEngineForClose()


class _FakeOverseerForClose:
    def reset_position_state(self):
        return None


class _FakeLLMHandlerForClose:
    def __init__(self) -> None:
        self.record_successful_exit_calls = []

    def record_successful_exit(self, **kwargs):
        self.record_successful_exit_calls.append(kwargs)


def _sample_signal() -> Signal:
    return Signal.create(
        type=SignalType.BUY,
        price=Decimal("100"),
        reason="trace validation",
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        timestamp="2026-01-01T09:00:00Z",
        setup=SetupType.TREND_MODEL,
        source=Source.LLM,
        metadata={
            "trade_thesis": {
                "market_state": "BALANCED",
                "location_type": "UPPER",
                "location_level": 1.0,
                "aggression_trigger": "test",
                "session_context": "MORNING",
                "invalidation_level": 1.0,
                "setup_family": "trend_model",
            },
            "grade_score": 6,
        },
    )


def _sample_amt() -> AMTResult:
    return AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=103.0,
        value_area_low=97.0,
        aggression=0.9,
    )


def _sample_tick() -> OHLC:
    return OHLC.create(time="2026-01-01T09:00:00Z", open=100, high=101, low=99, close=100, volume=10)


def _build_router() -> tuple[SessionEventRouter, _FakeEventLogger, _FakeSignalTracker, _FakeStorage]:
    fake_event_logger = _FakeEventLogger()
    fake_lifecycle_handler = _FakeLifecycleHandler()
    fake_storage = _FakeStorage()
    fake_risk_coordinator = _FakeSessionRiskCoordinator()
    fake_broker = _FakeBroker()
    fake_exchange = _FakeExchangeConfig()
    fake_signal_tracker = _FakeSignalTracker()

    entry_coordinator = EntryCoordinator(
        broker=fake_broker,
        lifecycle_handler=fake_lifecycle_handler,
        event_logger=fake_event_logger,
        storage=fake_storage,
        risk_coordinator=fake_risk_coordinator,
        option_selector=Mock(_lot_size_for=lambda _underlying: 25, select_strike=lambda **_kwargs: 100),
        state_manager=Mock(),
    )

    router = SessionEventRouter(
        lifecycle_handler=fake_lifecycle_handler,
        llm_handler=Mock(),
        overseer_handler=Mock(),
        entry_coordinator=entry_coordinator,
        exit_coordinator=Mock(),
        broker=fake_broker,
        storage=fake_storage,
        risk_coordinator=fake_risk_coordinator,
        probability_engine=Mock(is_ready=lambda: True),
        exchange_config=fake_exchange,
        exchange="MCX",
        allow_short=True,
        gate_tracker=Mock(),
        signal_tracker=fake_signal_tracker,
        scalp_enabled=False,
    )
    return router, fake_event_logger, fake_signal_tracker, fake_storage


def _build_router_with_real_event_logger(
    fake_storage: _FakeStorage,
) -> tuple[SessionEventRouter, SessionEventLogger, _FakeSignalTracker, _FakeTradeJournal]:
    fake_signal_tracker = _FakeSignalTracker()
    fake_journal = _FakeTradeJournal()
    fake_lifecycle_handler = _FakeLifecycleHandler()
    fake_risk_coordinator = _FakeSessionRiskCoordinator()
    fake_broker = _FakeBroker()
    fake_exchange = _FakeExchangeConfig()

    fake_event_logger = SessionEventLogger(storage=fake_storage)
    fake_event_logger._journal = fake_journal

    entry_coordinator = EntryCoordinator(
        broker=fake_broker,
        lifecycle_handler=fake_lifecycle_handler,
        event_logger=fake_event_logger,
        storage=fake_storage,
        risk_coordinator=fake_risk_coordinator,
        option_selector=Mock(
            _lot_size_for=lambda _underlying: 25,
            select_strike=lambda **_kwargs: 100,
        ),
        state_manager=Mock(),
    )

    router = SessionEventRouter(
        lifecycle_handler=fake_lifecycle_handler,
        llm_handler=Mock(),
        overseer_handler=Mock(),
        entry_coordinator=entry_coordinator,
        exit_coordinator=Mock(),
        broker=fake_broker,
        storage=fake_storage,
        risk_coordinator=fake_risk_coordinator,
        probability_engine=Mock(is_ready=lambda: True),
        exchange_config=fake_exchange,
        exchange="MCX",
        allow_short=True,
        gate_tracker=Mock(),
        signal_tracker=fake_signal_tracker,
        scalp_enabled=False,
    )
    return router, fake_event_logger, fake_signal_tracker, fake_journal


def _build_exit_coordinator_with_real_event_logger(
    fake_storage: _FakeStorage,
) -> tuple[ExitCoordinator, _FakeTradeJournal, _FakeStorage, SessionStateManager]:
    fake_journal = _FakeTradeJournal()
    event_logger = SessionEventLogger(storage=fake_storage)
    event_logger._journal = fake_journal

    state_manager = SessionStateManager()
    risk_manager = _FakeRiskManagerForClose()
    risk_coordinator = _FakeRiskCoordinatorForClose(risk_manager)
    lifecycle_handler = _FakeLifecycleHandlerForClose()

    coordinator = ExitCoordinator(
        broker=_FakeBroker(),
        lifecycle_handler=lifecycle_handler,
        event_logger=event_logger,
        overseer_handler=_FakeOverseerForClose(),
        state_manager=state_manager,
        storage=fake_storage,
        llm_handler=_FakeLLMHandlerForClose(),
        risk_coordinator=risk_coordinator,
        post_trade_analyst=None,
    )
    return coordinator, fake_journal, fake_storage, state_manager


def test_tick_trace_id_continues_from_tick_to_signal_tracker_to_journal(monkeypatch):
    router, fake_event_logger, fake_signal_tracker, fake_storage = _build_router()
    session = SessionStateManager().get_or_create_session("NIFTY")
    session._agent_decision = None
    tick = _sample_tick()

    event = TickReceived(
        symbol="NIFTY",
        tick=tick,
        order_book=None,
        data=tuple([tick] * 25),
        agent_series=tuple([tick] * 25),
        tick_trace_id="trace-2026-01-01",
    )

    def _fake_run_gate_pipeline(*_args, **_kwargs):
        return True, "", "", 2, 2

    fake_signal = _sample_signal()
    monkeypatch.setattr(
        "app.application.services.session_event_router.run_gate_pipeline",
        _fake_run_gate_pipeline,
    )
    monkeypatch.setattr(
        router,
        "_build_entry_signal",
        lambda *args, **kwargs: fake_signal,
    )

    router.execute_entry_path(
        event=event,
        session=session,
        amt_result=_sample_amt(),
        exec_dir="LONG",
        exec_prob=0.8,
        run_entry=True,
        exchange_config=router._exchange_config,
        allow_short=True,
        scalp_enabled=False,
    )

    assert fake_signal_tracker.generated_calls[0]["tick_trace_id"] == "trace-2026-01-01"
    assert fake_event_logger.entry_calls[0]["tick_trace_id"] == "trace-2026-01-01"
    assert fake_storage.open_positions[0]["tick_trace_id"] == "trace-2026-01-01"


def test_tick_trace_id_reaches_journal_on_entry(monkeypatch):
    fake_storage = _FakeStorage()
    router, _, fake_signal_tracker, fake_journal = _build_router_with_real_event_logger(
        fake_storage=fake_storage,
    )

    session = SessionStateManager().get_or_create_session("NIFTY")
    session._agent_decision = None
    tick = _sample_tick()

    event = TickReceived(
        symbol="NIFTY",
        tick=tick,
        order_book=None,
        data=tuple([tick] * 25),
        agent_series=tuple([tick] * 25),
        tick_trace_id="trace-journal-2026-01-01",
    )

    def _fake_run_gate_pipeline(*_args, **_kwargs):
        return True, "", "", 2, 2

    fake_signal = _sample_signal()
    monkeypatch.setattr(
        "app.application.services.session_event_router.run_gate_pipeline",
        _fake_run_gate_pipeline,
    )
    monkeypatch.setattr(
        router,
        "_build_entry_signal",
        lambda *args, **kwargs: fake_signal,
    )

    router.execute_entry_path(
        event=event,
        session=session,
        amt_result=_sample_amt(),
        exec_dir="LONG",
        exec_prob=0.8,
        run_entry=True,
        exchange_config=router._exchange_config,
        allow_short=True,
        scalp_enabled=False,
    )

    assert fake_signal_tracker.generated_calls[0]["tick_trace_id"] == "trace-journal-2026-01-01"
    assert fake_journal.entry_calls[0]["tick_trace_id"] == "trace-journal-2026-01-01"
    assert fake_storage.open_positions[0]["tick_trace_id"] == "trace-journal-2026-01-01"


def test_tick_trace_id_survives_close_path_to_journal_and_storage():
    fake_storage = _FakeStorage()
    coordinator, fake_journal, _storage, state_manager = _build_exit_coordinator_with_real_event_logger(
        fake_storage=fake_storage,
    )
    session = state_manager.get_or_create_session("NIFTY")

    class _FakeLearningEngine:
        def __init__(self) -> None:
            self.learn_calls = []

        def learn(self, position):
            self.learn_calls.append(position)

    session.learning = _FakeLearningEngine()

    close_position = Position(
        id="trace-close-pos",
        symbol="NIFTY",
        side=Side.LONG,
        source=Source.AMT,
        entry_price=Decimal("100"),
        size=Decimal("1"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        entry_time="2026-01-01T09:00:00Z",
        exit_time="2026-01-01T09:15:00Z",
        status=PositionStatus.CLOSED,
        pnl=Decimal("12.5"),
        metadata={"tick_trace_id": "trace-close-2026-01-01"},
    )
    session.portfolio.positions.append(close_position)

    coordinator.on_position_closed("NIFTY", close_position, session=session)

    assert fake_journal.exit_calls[0]["tick_trace_id"] == "trace-close-2026-01-01"
    assert _storage.delete_open_position_calls == ["trace-close-pos"]
    assert session.learning.learn_calls == [close_position]
