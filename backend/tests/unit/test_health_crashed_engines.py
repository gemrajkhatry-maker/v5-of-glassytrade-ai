"""Crashed engines must degrade /health and fail /health/ready.

Route-level tests: call the actual ``health_check`` / ``readiness_check``
route functions with a stub Request and stubbed module dependencies. A
coordinator reporting crashed engine threads must flip /health to
"degraded" and make /health/ready report the dead engines.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_module(name: str, relative_path: str):
    backend_root = Path(__file__).resolve().parents[2]
    mod_path = backend_root / relative_path
    spec = importlib.util.spec_from_file_location(name, mod_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


health = _load_module("health_crashed_engines_test_mod", "app/api/routers/health.py")


class _FakeStorage:
    """Minimal storage double covering what the health routes call."""

    def __init__(self) -> None:
        self._data: dict = {}

    def kv_set(self, key, value):
        self._data[key] = value

    def kv_get(self, key):
        return self._data.get(key)


class _Coord:
    """Coordinator double with a controllable crashed-engine list."""

    def __init__(self, crashed: list[str]) -> None:
        self.started = True
        self._crashed = crashed

    def symbols(self) -> list[str]:
        return ["NIFTY 25000 CALL"]

    def crashed_engines(self) -> list[str]:
        return self._crashed


def _request(coordinator) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                coordinator=coordinator,
                engine_start_failed=False,
                startup_contracts={},
            )
        )
    )


def _paper_mode(monkeypatch) -> None:
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.delenv("TRADING_MODE", raising=False)


@pytest.mark.asyncio
async def test_health_degraded_when_engines_crashed(monkeypatch):
    _paper_mode(monkeypatch)

    resp = await health.health_check(
        _request(_Coord(["NIFTY 25000 CALL"])),
        broker=object(),
        storage=_FakeStorage(),
        config=object(),
    )
    assert resp["status"] == "degraded"
    assert resp["checks"]["coordinator"]["crashedEngines"] == ["NIFTY 25000 CALL"]

    resp_ok = await health.health_check(
        _request(_Coord([])),
        broker=object(),
        storage=_FakeStorage(),
        config=object(),
    )
    assert resp_ok["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_fails_when_engines_crashed(monkeypatch):
    _paper_mode(monkeypatch)
    monkeypatch.setattr(health, "get_storage", lambda: _FakeStorage())
    monkeypatch.setattr(health, "get_active_symbols", lambda: ["NIFTY"])

    resp = await health.readiness_check(_request(_Coord(["NIFTY 25000 CALL"])))
    assert "crashed" in str(resp["checks"]["engine"])
    assert resp["status"] != "ready"

    resp_ok = await health.readiness_check(_request(_Coord([])))
    assert resp_ok["checks"]["engine"] == "ok"
