"""Runtime contract checks for startup and trading-cycle invariants."""

from __future__ import annotations

import os
from collections import deque
import re
from decimal import Decimal
from types import MappingProxyType
from pathlib import Path
from typing import Any, Callable
from unittest.mock import Mock, call

from fastapi.testclient import TestClient

import app.main as main
from app.application.services.entry_coordinator import EntryCoordinator
from app.application.services.session_state_manager import SessionStateManager
from quant.contracts.ports.broker import IBroker
from quant.contracts.ports.llm_inference import ILLMInference
from quant.contracts.ports.market_data import IMarketData
from quant.contracts.ports.storage import IStorage
from quant.contracts.entities import Position, Signal
from quant.contracts.enums import SetupType, SignalType, Source, Side
from quant.contracts.value_objects import OHLC
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
        self.last_kv_set = None
        self.saved_open_positions: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.saved_trades: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.open_positions_deleted: list[Any] = []

    def flush(self) -> None:
        self.flush_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def load_open_positions(self) -> list[dict[str, str]]:
        return []

    def save_open_position(self, *args, **kwargs) -> None:
        self.saved_open_positions.append((args, kwargs))

    def delete_open_position(self, *args, **kwargs) -> None:
        self.open_positions_deleted.append(args[0] if args else kwargs.get("position_id", ""))

    def save_trade(self, *args, **kwargs) -> None:
        self.saved_trades.append((args, kwargs))

    def kv_set(self, *args, **kwargs) -> None:
        self.last_kv_set = (args, kwargs)


class _FakeBroker:
    def __init__(self) -> None:
        self.get_positions_calls = 0
        self.get_account_positions_calls = 0
        self.execute_order_calls = 0
        self.cancel_order_calls = 0
        self.get_positions_return: list[dict[str, str]] = []

    def get_positions(self) -> list[dict[str, str]]:
        self.get_positions_calls += 1
        return list(self.get_positions_return)

    def get_account_positions(self) -> list[dict[str, str]]:
        self.get_account_positions_calls += 1
        return []

    def execute_order(self, *_args, **_kwargs):
        self.execute_order_calls += 1
        return None

    def cancel_order(self, *_args, **_kwargs):
        self.cancel_order_calls += 1
        return None


def _build_runtime_app_fixture(
    monkeypatch,
    selected_symbols: tuple[str, ...],
    startup_symbols: tuple[str, ...],
    session_factory: callable | None = None,
    broker_factory: callable | None = None,
    storage_factory: callable | None = None,
) -> tuple[Any, _FakeContainer, _FakeStorage, _FakeTradingSession]:
    if session_factory is None:
        session_factory = _FakeTradingSession
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

    fake_session = session_factory()
    fake_storage = _FakeStorage()
    fake_broker = broker_factory() if broker_factory else _FakeBroker()
    if storage_factory is not None:
        fake_storage = storage_factory()
        container_storage = fake_storage
    else:
        container_storage = fake_storage

    if not hasattr(fake_session, "_broker"):
        fake_session._broker = fake_broker
    if not hasattr(fake_session, "_storage"):
        fake_session._storage = fake_storage
    container = _FakeContainer(
        {
            TradingSessionService: lambda c: fake_session,
            IBroker: lambda c: fake_broker,
            IStorage: lambda c: container_storage,
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
        "quant.amt.session.scanner.OptionScannerService",
        _FakeScanner,
    )
    monkeypatch.setattr("app.application.engine.TradingEngine", _FakeEngine)
    # Note: settings.* are read-only env/YAML-backed properties on
    # SettingsAdapter and cannot be monkeypatched here. The fake scanner and
    # fake container below make the actual config values irrelevant to these tests.

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


def test_readiness_contract_detects_position_close_capability(monkeypatch):
    class _ReadyCloseCoordinator:
        def on_position_closed(self, *_args, **_kwargs):
            return None

        def _resolve_position(self, *_args, **_kwargs):
            return None, ""

    class _ReadyTradingSession(_FakeTradingSession):
        def __init__(self) -> None:
            super().__init__()
            self._event_router = Mock()
            self._exit_coordinator = _ReadyCloseCoordinator()

        def process_tick(self, *_args, **_kwargs) -> None:
            return None

    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
        session_factory=_ReadyTradingSession,
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    assert body["checks"]["startup_close_contract"] == "ok"
    assert body["checks"]["startup_contracts"] == "ok"


def test_readiness_contract_rejects_missing_position_close_capability(monkeypatch):
    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    assert body["checks"]["startup_close_contract"].startswith("error")
    assert body["checks"]["startup_contracts"] != "ok"
    assert body["status"] == "not_ready"


def test_readiness_contract_rejects_missing_strategy_runtime(monkeypatch):
    class _CloseCoordinator:
        def on_position_closed(self, *_args, **_kwargs):
            return None

        def _resolve_position(self, *_args, **_kwargs):
            return None, ""

    class _ReadySession(_FakeTradingSession):
        def __init__(self) -> None:
            super().__init__()
            self._exit_coordinator = _CloseCoordinator()

        def process_tick(self, *_args, **_kwargs) -> None:
            return None

    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
        session_factory=_ReadySession,
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    assert body["checks"]["startup_strategy"] == "error: missing runtime contracts"
    assert body["checks"]["startup_close_contract"] == "ok"
    assert body["checks"]["startup_contracts"] != "ok"
    assert body["status"] == "not_ready"


def test_readiness_contract_reports_broker_storage_and_reconciliation_keys(monkeypatch):
    class _StrategyRouter:
        def execute_entry_path(self, *_args, **_kwargs) -> None:
            return None

        def trigger_llm_entry(self, *_args, **_kwargs) -> None:
            return None

        def should_trigger_llm(self, *_args, **_kwargs) -> bool:
            return False

    class _CloseCoordinator:
        def on_position_closed(self, *_args, **_kwargs):
            return None

        def _resolve_position(self, *_args, **_kwargs):
            return None, ""

    class _Session(_FakeTradingSession):
        def __init__(self) -> None:
            super().__init__()
            self._event_router = _StrategyRouter()
            self._exit_coordinator = _CloseCoordinator()
            self._event_router_ref = self._event_router

        def process_tick(self, *_args, **_kwargs) -> None:
            return None

    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
        session_factory=_Session,
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    checks = body["checks"]
    assert checks["startup_broker"] == "ok"
    assert checks["startup_storage"] == "ok"
    assert checks["startup_reconciliation"] == "ok"
    assert "startup_broker_runtime" in checks
    assert "startup_contract_id" in checks
    assert "startup_reconciliation_summary" in checks
    assert body["checks"]["startup_contracts"] == "ok"


def test_readiness_contract_rejects_missing_broker_runtime(monkeypatch):
    class _NoExecuteBroker:
        def get_positions(self):
            return []

        def get_account_positions(self):
            return []

    class _StrategyRouter:
        def execute_entry_path(self, *_args, **_kwargs) -> None:
            return None

        def trigger_llm_entry(self, *_args, **_kwargs) -> None:
            return None

        def should_trigger_llm(self, *_args, **_kwargs) -> bool:
            return False

    class _CloseCoordinator:
        def on_position_closed(self, *_args, **_kwargs):
            return None

        def _resolve_position(self, *_args, **_kwargs):
            return None, ""

    class _Session(_FakeTradingSession):
        def __init__(self) -> None:
            super().__init__()
            self._event_router = _StrategyRouter()
            self._exit_coordinator = _CloseCoordinator()

        def process_tick(self, *_args, **_kwargs) -> None:
            return None

    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
        session_factory=_Session,
        broker_factory=_NoExecuteBroker,
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    assert body["checks"]["startup_broker"].startswith("error")
    assert body["status"] == "not_ready"


def test_readiness_contract_rejects_missing_storage_runtime(monkeypatch):
    class _StorageWithoutSaveTrade:
        def __init__(self):
            self.flush_calls = 0
            self.close_calls = 0
            self.last_kv_set = None

        def flush(self) -> None:
            self.flush_calls += 1

        def close(self) -> None:
            self.close_calls += 1

        def load_open_positions(self):
            return []

        def save_open_position(self, *args, **kwargs):
            return None

        def delete_open_position(self, *args, **kwargs):
            return None

    class _StrategyRouter:
        def execute_entry_path(self, *_args, **_kwargs) -> None:
            return None

        def trigger_llm_entry(self, *_args, **_kwargs) -> None:
            return None

        def should_trigger_llm(self, *_args, **_kwargs) -> bool:
            return False

    class _CloseCoordinator:
        def on_position_closed(self, *_args, **_kwargs):
            return None

        def _resolve_position(self, *_args, **_kwargs):
            return None, ""

    class _Session(_FakeTradingSession):
        def __init__(self) -> None:
            super().__init__()
            self._event_router = _StrategyRouter()
            self._exit_coordinator = _CloseCoordinator()
            self._storage = _StorageWithoutSaveTrade()

        def process_tick(self, *_args, **_kwargs) -> None:
            return None

    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
        session_factory=_Session,
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    assert body["checks"]["startup_storage"].startswith("error")
    assert body["status"] == "not_ready"


def test_readiness_contract_rejects_zero_active_symbols(monkeypatch):
    # DHAN_SYMBOLS is a read-only property backed by the YAML mode config, so
    # force an empty symbol selection by replacing the mode config itself.
    from types import SimpleNamespace as _NS

    monkeypatch.setattr(
        "app.config.settings._mode_config",
        _NS(
            active_symbols=[],
            default_exchange="MCX",
            scanner_underlyings=[],
            scanner_config={"top_n": 4, "option_type": ""},
        ),
    )
    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=(),
        startup_symbols=(),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    assert body["checks"]["startup_active_symbols"].startswith("error")
    assert body["checks"]["startup_contracts"] == "degraded"
    assert body["status"] == "not_ready"


def test_readiness_contract_rejects_missing_broker_and_storage_runtime(monkeypatch):
    class _NoExecuteBroker:
        def get_positions(self):
            return []

        def get_account_positions(self):
            return []

    class _StorageWithoutTradePersistence:
        def __init__(self):
            self.flush_calls = 0
            self.close_calls = 0

        def flush(self) -> None:
            self.flush_calls += 1

        def close(self) -> None:
            self.close_calls += 1

        def load_open_positions(self):
            return []

        def save_open_position(self, *args, **kwargs):
            return None

    class _StrategyRouter:
        def execute_entry_path(self, *_args, **_kwargs) -> None:
            return None

        def trigger_llm_entry(self, *_args, **_kwargs) -> None:
            return None

        def should_trigger_llm(self, *_args, **_kwargs) -> bool:
            return False

    class _CloseCoordinator:
        def on_position_closed(self, *_args, **_kwargs):
            return None

        def _resolve_position(self, *_args, **_kwargs):
            return None, ""

    class _Session(_FakeTradingSession):
        def __init__(self) -> None:
            super().__init__()
            self._event_router = _StrategyRouter()
            self._exit_coordinator = _CloseCoordinator()
            self._storage = _StorageWithoutTradePersistence()

        def process_tick(self, *_args, **_kwargs) -> None:
            return None

    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
        session_factory=_Session,
        broker_factory=_NoExecuteBroker,
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    assert body["checks"]["startup_broker"].startswith("error")
    assert body["checks"]["startup_storage"].startswith("error")
    assert body["checks"]["startup_contracts"] == "degraded"
    assert body["status"] == "not_ready"


def test_readiness_contract_rejects_reconciliation_execution_failure(monkeypatch):
    class _BrokenReconciliation:
        def __init__(self, *_, **__) -> None:
            pass

        def reconcile(self):
            raise RuntimeError("reconciliation startup failure")

    class _StrategyRouter:
        def execute_entry_path(self, *_args, **_kwargs) -> None:
            return None

        def trigger_llm_entry(self, *_args, **_kwargs) -> None:
            return None

        def should_trigger_llm(self, *_args, **_kwargs) -> bool:
            return False

    class _CloseCoordinator:
        def on_position_closed(self, *_args, **_kwargs):
            return None

        def _resolve_position(self, *_args, **_kwargs):
            return None, ""

    class _Session(_FakeTradingSession):
        def __init__(self) -> None:
            super().__init__()
            self._event_router = _StrategyRouter()
            self._exit_coordinator = _CloseCoordinator()

        def process_tick(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(main, "StartupReconciliation", _BrokenReconciliation)

    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
        session_factory=_Session,
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()

    assert body["checks"]["startup_reconciliation"].startswith("error")
    assert body["checks"]["startup_contracts"] == "degraded"
    assert body["status"] == "not_ready"


def test_startup_dependency_refs_are_immutable(monkeypatch):
    app, _container, _fake_storage, _fake_session = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
    )

    with TestClient(app) as client:
        client.get("/health/ready")
        startup_refs = getattr(app.state, "startup_dependency_refs", None)
        assert startup_refs is not None
        assert isinstance(startup_refs, MappingProxyType)
        assert startup_refs["trading_session"] is _fake_session
        assert "broker" in startup_refs
        try:
            startup_refs["broker"] = Mock()
        except TypeError:
            pass
        else:  # pragma: no cover
            assert False, "startup_dependency_refs should be immutable"


def test_startup_lifecycle_does_not_emit_async_runtime_warnings(monkeypatch, capsys):
    """Fail fast if startup lifecycle emits unawaited/unraisable coroutine signals."""
    app, _, _, _ = _build_runtime_app_fixture(
        monkeypatch,
        selected_symbols=("NIFTY",),
        startup_symbols=("FALLBACK_X",),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200

    captured = capsys.readouterr()
    startup_output = captured.out + captured.err
    bad_patterns = [
        r"RuntimeWarning: coroutine '.*' was never awaited",
        r"NameError: name 'count' is not defined",
        r"unraisable",
    ]

    for pattern in bad_patterns:
        assert not re.search(pattern, startup_output), f"Found startup warning pattern {pattern!r}"


def test_startup_log_contract_file_is_clean():
    """Fail when persisted startup logs contain known async/runtime signatures."""
    log_path = Path(
        os.getenv("BACKEND_RUNTIME_LOG_PATH")
        or Path(__file__).resolve().parents[2] / "backend.log"
    )
    if not log_path.exists():
        return

    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        log_text = "".join(deque(fh, maxlen=2000))

    startup_marker = "Starting GlassyTrade AI application..."
    marker_index = log_text.rfind(startup_marker)
    if marker_index != -1:
        log_text = log_text[marker_index:]

    banned_patterns = (
        (r"RuntimeWarning: coroutine '.*' was never awaited", 0),
        (r"NameError: name 'count' is not defined", 0),
        (r"unraisable", re.IGNORECASE),
    )

    for item in banned_patterns:
        if isinstance(item, tuple):
            pattern, flags = item
        else:
            pattern, flags = item, 0
        if re.search(pattern, log_text, flags):
            assert False, f"Startup log contract violation: {pattern!r} in {log_path}"
