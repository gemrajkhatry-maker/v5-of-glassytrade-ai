from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import settings


def _load_module(name: str, relative_path: str):
    backend_root = Path(__file__).resolve().parents[3]
    mod_path = backend_root / relative_path
    spec = importlib.util.spec_from_file_location(name, mod_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


health = _load_module("health_router_test_mod", "app/api/routers/health.py")
gameloop = _load_module("gameloop_ws_test_mod", "app/api/websocket/gameloop.py")


class _ReadyAdapter:
    def is_ready(self) -> bool:
        return True


class _StubTradingSession:
    _experiment = None
    
    def cleanup(self):
        pass


@pytest.mark.asyncio
async def test_system_config_reports_runtime_port_and_symbols(monkeypatch):
    graph = SimpleNamespace(
        llm_inference=_ReadyAdapter(),
        probability_engine=_ReadyAdapter(),
        active_symbols=["NIFTY25000CE", "NIFTY25000PE"],
        trading_session=_StubTradingSession(),
    )
    fake_app = SimpleNamespace(state=SimpleNamespace(service_graph=graph))
    fake_request = SimpleNamespace(app=fake_app)
    
    # Mock get_trading_session to return the stub session
    def _mock_get_session():
        return graph.trading_session
    
    # Mock get_active_symbols to return the graph's active symbols
    def _mock_get_active_symbols():
        return graph.active_symbols
    
    # Mock get_gen_ai_service to return a ready adapter
    def _mock_get_gen_ai():
        return _ReadyAdapter()
    
    monkeypatch.setattr(health, "get_trading_session", _mock_get_session)
    monkeypatch.setattr(health, "get_active_symbols", _mock_get_active_symbols)
    monkeypatch.setattr(health, "get_gen_ai_service", _mock_get_gen_ai)

    payload = await health.system_config(fake_request)

    assert payload["backendPort"] == settings.PORT
    assert payload["activeSymbols"] == graph.active_symbols
    assert payload["defaultSymbol"] == graph.active_symbols[0]


def test_bootstrap_active_symbols_never_empty(monkeypatch):
    class _EmptySettings:
        DHAN_SYMBOLS: list = []

    monkeypatch.setattr(health, "settings", _EmptySettings())
    graph = SimpleNamespace(
        active_symbols=["", "  ", None],
        _config=SimpleNamespace(trading=SimpleNamespace(default_symbol="")),
    )
    assert health._bootstrap_active_symbols(graph) == ["CRUDEOIL"]


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class _FakeEngine:
    generation = 1

    def get_active_symbols(self) -> list[str]:
        return ["NIFTY25000CE"]

    def get_history(self, _sym: str):
        return []

    def get_latest_state(self, sym: str):
        return {"_symbol": sym, "lastPrice": 100.0}

    async def wait_for_update(self, known_gen: int, timeout: float = 5.0) -> int:
        await asyncio.sleep(0)
        return known_gen


@pytest.mark.asyncio
async def test_viewer_loop_sends_server_mode_and_full_snapshot(monkeypatch):
    async def _stop_client_listener(_ws):
        return

    monkeypatch.setattr(gameloop, "_listen_for_client", _stop_client_listener)

    ws = _FakeWebSocket()
    graph = SimpleNamespace(engine=_FakeEngine())

    await gameloop._viewer_loop(ws, graph, "NIFTY25000CE")

    assert ws.sent
    first = ws.sent[0]
    assert first["status"] == "server_mode"
    assert "activeSymbols" in first
    assert any(msg.get("_type") == "full" for msg in ws.sent)


@pytest.mark.asyncio
async def test_scanner_rescan_timeout_returns_504(monkeypatch):
    async def _timeout(*args, **_kwargs):
        if args and asyncio.iscoroutine(args[0]):
            args[0].close()
        raise TimeoutError()

    monkeypatch.setattr(health.asyncio, "wait_for", _timeout)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                service_graph=SimpleNamespace(market_data=object(), active_symbols=[])
            )
        )
    )

    with pytest.raises(HTTPException) as err:
        await health.scanner_rescan(request)

    assert err.value.status_code == 504
    assert "timed out" in err.value.detail.lower()
