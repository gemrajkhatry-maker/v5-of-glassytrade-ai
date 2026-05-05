"""Runtime contract checks for startup and trading-cycle invariants."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import Mock, call

from fastapi.testclient import TestClient

import app.main as main
from app.application.services.entry_coordinator import EntryCoordinator
from app.application.services.session_state_manager import SessionStateManager
from app.domain.ports.broker import IBroker
from app.domain.ports.llm_inference import ILLMInference
from app.domain.ports.market_data import IMarketData
from app.domain.ports.storage import IStorage
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.enums import SetupType, SignalType, Source, Side
from app.domain.trading.models.value_objects import OHLC
from app.application.services.trading_session import TradingSessionService


class _FakeContainer:
    def __init__(self, factories: dict[type, Callable[["_FakeContainer"], Any]]) -> None:
        self._factories = dict(factories)
        self._singletons: dict[type, Any] = {}

    def register(self, interface: type, factory: Callable[["_FakeContainer"], Any]) -> None:
        self._factories[interface] = factory

    def register_singleton(self, interface: type, factory: Callable[["_FakeContainer"], Any]) -> None:
        self._factories[interface] = factory

    def resolve(self, interface: type) -> Any:
        if interface in self._singletons:
            return self._singletons[interface]

        if interface not in self._factories:
            raise RuntimeError(f"Unregistered interface: {interface}")

        factory = self._factories[interface]
        value = factory(self)
        self._singletons[interface] = value
        return value


class _FakeTradingSession:
    def __init__(self) -> None:
        self.cleanup_called = False

    def cleanup(self) -> None:
        self.cleanup_called = True


class _FakeStorage:
    def __init__(self) -> None:
        self.flush_calls = 0
        self.close_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1

    def close(self) -> None:
        self.close_calls += 1


def _build_runtime_app_fixture(
    monkeypatch,
    selected_symbols: tuple[str, ...],
    startup_symbols: tuple[str, ...],
) -> tuple[Any, _FakeContainer, _FakeStorage, _FakeTradingSession]:
    class _FakeScannerResult:
        def __init__(self, symbol: str, ltp: float) -> None:
            self.symbol = symbol
            self.ltp = ltp

    class _FakeScanner:
        def __init__(self, market_data):
            self._market_data = market_data

        def scan_top_n(
            self,
            n: int,
            underlyings,
            preferred_option_type,
            exchange,
            expiry_index,
            strikes_around_atm,
        ):
            return [_FakeScannerResult(symbol, 100.0 + i * 10.0) for i, symbol in enumerate(selected_symbols)]

    class _FakeEngine:
        instances: list[Any] = []

        def __init__(self, _container):
            self.started = False
            self.stopped = False
            _FakeEngine.instances.append(self)

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    fake_session = _FakeTradingSession()
    fake_storage = _FakeStorage()

    container = _FakeContainer(
        {
            TradingSessionService: lambda c: fake_session,
            IBroker: lambda c: Mock(),
            IStorage: lambda c: fake_storage,
            IMarketData: lambda c: Mock(),
            ILLMInference: lambda c: Mock(),
            list: lambda c: list(startup_symbols),
        }
    )

    monkeypatch.setattr(
        "app.application.di.composition_root.compose_container",
        lambda config: container,
    )
    monkeypatch.setattr(
        "app.domain.fabio_ai.services.option_scanner.OptionScannerService",
        _FakeScanner,
    )
    monkeypatch.setattr("app.application.engine.TradingEngine", _FakeEngine)
    monkeypatch.setattr(
        "config.consolidated.ConsolidatedConfig.from_unified",
        lambda: SimpleNamespace(dhan_symbols=list(startup_symbols), cors_origins=["*"]),
    )
    monkeypatch.setattr("app.config.settings.SCANNER_TOP_N", len(selected_symbols), raising=False)
    monkeypatch.setattr("app.config.settings.SCANNER_UNDERLYINGS", ["TESTIDX"], raising=False)
    monkeypatch.setattr("app.config.settings.SCANNER_OPTION_TYPE", "", raising=False)
    monkeypatch.setattr("app.config.settings.DEFAULT_EXCHANGE", "MCX", raising=False)
    monkeypatch.setattr("app.config.settings.SCANNER_EXPIRY_INDEX", 0, raising=False)
    monkeypatch.setattr("app.config.settings.STRIKES_AROUND_ATM", 2, raising=False)

    return main.create_application(), container, fake_storage, fake_session


def _make_sample_signal(timestamp: str) -> Signal:
    return Signal.create(
        type=SignalType.BUY,
        price=Decimal("100"),
        reason="contract test signal",
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        timestamp=timestamp,
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
        },
    )


def _tick(time: str) -> OHLC:
    return OHLC.create(
        time=time,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=10,
    )


def test_startup_registry_contract_aligns_state_with_runtime_registry(monkeypatch):
    """Startup must update registry-backed active symbols before trading starts."""
    selected_symbols = ("SYM_A", "SYM_B")
    app = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=selected_symbols,
        startup_symbols=("FALLBACK_X",),
    )[0]

    with TestClient(app) as client:
        assert client.base_url  # start app
        assert app.state.active_symbols == list(selected_symbols)
        assert app.state.container.resolve(list) == list(selected_symbols)


def test_untradable_symbol_blocks_pending_signal_execution():
    svc = TradingSessionService(broker=Mock(), gen_ai_service=Mock())
    svc.set_symbol_trading_state("CRUDE", "UNTRADABLE_NOW", "safety")

    cache = svc._get_cache("CRUDE")
    cache.set_pending_signal("CRUDE", _make_sample_signal("2026-01-01T09:00:00Z"))

    svc._event_router = Mock()
    svc._on_tick = Mock()
    svc.process_tick("CRUDE", _tick("2026-01-01T09:00:30Z"))

    svc._event_router.execute_signal.assert_not_called()


def test_fresh_pending_signal_executes_only_when_symbol_is_tradable():
    svc = TradingSessionService(broker=Mock(), gen_ai_service=Mock())
    svc.set_symbol_trading_state("CRUDE", "TRADABLE", None)

    signal = _make_sample_signal("2026-01-01T09:00:00Z")
    cache = svc._get_cache("CRUDE")
    cache.set_pending_signal("CRUDE", signal)

    svc._event_router = Mock()
    svc._on_tick = Mock()
    svc.process_tick("CRUDE", _tick("2026-01-01T09:00:45Z"))

    svc._event_router.execute_signal.assert_called_once_with("CRUDE", signal, svc.get_or_create_session("CRUDE"))


def test_stale_pending_signal_ttl_prevents_execution():
    svc = TradingSessionService(broker=Mock(), gen_ai_service=Mock())
    svc.set_symbol_trading_state("CRUDE", "TRADABLE", None)

    cache = svc._get_cache("CRUDE")
    cache.set_pending_signal("CRUDE", _make_sample_signal("2026-01-01T09:00:00Z"))

    svc._event_router = Mock()
    svc._on_tick = Mock()
    svc.process_tick("CRUDE", _tick("2026-01-01T09:12:00Z"))

    svc._event_router.execute_signal.assert_not_called()


def test_entry_coordination_contract_records_broker_then_storage():
    """Execution persistence contract: broker execution must precede durable write."""
    trace = Mock()

    broker = Mock()
    storage = Mock()
    risk_coordinator = Mock()
    risk_coordinator.validate_entry.return_value = True
    lifecycle_handler = Mock()
    event_logger = Mock()
    event_logger._decision_attribution.return_value = ("llm", "model")
    option_selector = Mock()
    option_selector.select_strike.return_value = 8800
    option_selector._lot_size_for.return_value = 25
    state_manager = Mock()

    position = Position(
        id="pos-1",
        symbol="CRUDE",
        side=Side.LONG,
        source=Source.LLM,
        entry_price=Decimal("100"),
        size=Decimal("1"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        entry_time="2026-01-01T09:00:00Z",
    )

    def execute_order(*_args, **_kwargs):
        trace("broker.execute_order")
        return position

    def save_open_position(*_args, **_kwargs):
        trace("storage.save_open_position")

    broker.execute_order.side_effect = execute_order
    storage.save_open_position.side_effect = save_open_position

    coordinator = EntryCoordinator(
        broker=broker,
        lifecycle_handler=lifecycle_handler,
        event_logger=event_logger,
        storage=storage,
        risk_coordinator=risk_coordinator,
        option_selector=option_selector,
        state_manager=state_manager,
    )

    session = SessionStateManager().get_or_create_session("CRUDE")
    coordinator.execute_signal("CRUDE", _make_sample_signal("2026-01-01T09:00:00Z"), session)

    assert trace.mock_calls == [call("broker.execute_order"), call("storage.save_open_position")]


def test_shutdown_contract_requires_storage_flush_and_close(monkeypatch):
    app, _container, fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("SYM_A",),
        startup_symbols=("FALLBACK_X",),
    )

    with TestClient(app):
        pass

    assert fake_storage.flush_calls >= 1
    assert fake_storage.close_calls >= 1
