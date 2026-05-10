"""Integration tests for scanner initialization and public scanner endpoints."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover
    TestClient = None
    _TESTCLIENT_IMPORT_ERROR = exc

from app.api import main


class _StubScanner:
    def __init__(self, *_, **__):
        pass

    def scan_top_n(self, *_, **__):
        return [
            SimpleNamespace(symbol="NIFTY", score=90.0),
            SimpleNamespace(symbol="BANKNIFTY", score=82.0),
            SimpleNamespace(symbol="FINNIFTY", score=79.0),
        ]


def test_system_config_prefers_runtime_symbols(monkeypatch):
    if TestClient is None:
        raise RuntimeError("TestClient unavailable")

    monkeypatch.setattr("app.bootstrap.lifespan.OptionScannerService", lambda *_args, **_kwargs: _StubScanner())
    monkeypatch.setattr("app.api.routers.scanner.OptionScannerService", lambda *_args, **_kwargs: _StubScanner())

    with TestClient(main.app) as client:
        resp = client.get("/api/system/config")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["activeSymbols"] == list(main.app.state.active_symbols)
        assert payload["activeSymbols"][:3] == ["NIFTY", "BANKNIFTY", "FINNIFTY"]


def test_scanner_endpoints_rescan_and_status(monkeypatch):
    if TestClient is None:
        raise RuntimeError("TestClient unavailable")

    monkeypatch.setattr("app.bootstrap.lifespan.OptionScannerService", lambda *_args, **_kwargs: _StubScanner())
    monkeypatch.setattr("app.api.routers.scanner.OptionScannerService", lambda *_args, **_kwargs: _StubScanner())

    with TestClient(main.app) as client:
        status_resp = client.get("/api/scanner/status")
        assert status_resp.status_code == 200
        assert "active_symbols" in status_resp.json()

        rescan_resp = client.post("/api/scanner/rescan", params={"n": 2})
        assert rescan_resp.status_code == 200
        res = rescan_resp.json()
        assert res["active_symbols"] == ["NIFTY", "BANKNIFTY"]
