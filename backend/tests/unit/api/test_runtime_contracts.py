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


class _ReadyAdapter:
    def is_ready(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_system_config_reports_runtime_port_and_symbols(monkeypatch):
    active = ["NIFTY25000CE", "NIFTY25000PE"]
    fake_app = SimpleNamespace(state=SimpleNamespace(service_graph=None))
    fake_request = SimpleNamespace(app=fake_app)
    
    def _mock_get_active_symbols():
        return active
    
    monkeypatch.setattr(health, "get_active_symbols", _mock_get_active_symbols)

    payload = await health.system_config(fake_request)

    assert payload["backendPort"] == settings.PORT
    assert payload["activeSymbols"] == active
    assert payload["defaultSymbol"] == active[0]


def test_bootstrap_active_symbols_never_empty(monkeypatch):
    class _EmptySettings:
        DHAN_SYMBOLS: list = []

    monkeypatch.setattr(health, "settings", _EmptySettings())
    graph = SimpleNamespace(
        active_symbols=["", "  ", None],
        _config=SimpleNamespace(trading=SimpleNamespace(default_symbol="")),
    )
    assert health._bootstrap_active_symbols(graph) == ["CRUDEOIL"]



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


@pytest.mark.asyncio
async def test_health_reports_live_oms_unwired(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(coordinator=None))
    )
    storage = SimpleNamespace(kv_set=lambda *a, **k: None)
    payload = await health.health_check(
        request, broker=object(), storage=storage, config=object()
    )
    assert payload["checks"]["live_oms"] == "unwired"


@pytest.mark.asyncio
async def test_health_reports_journal_ok_without_coordinator(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(coordinator=None))
    )
    storage = SimpleNamespace(kv_set=lambda *a, **k: None)
    payload = await health.health_check(
        request, broker=object(), storage=storage, config=object()
    )
    assert payload["checks"]["journal"] == "ok"
