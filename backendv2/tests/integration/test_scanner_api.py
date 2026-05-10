"""Integration coverage for `/api/scanner` endpoints."""
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
        ]


def test_scanner_status_has_state_fields(monkeypatch):
    if TestClient is None:
        raise RuntimeError("TestClient unavailable")
    monkeypatch.setattr("app.bootstrap.lifespan.OptionScannerService", lambda *_args, **_kwargs: _StubScanner())
    monkeypatch.setattr("app.api.routers.scanner.OptionScannerService", lambda *_args, **_kwargs: _StubScanner())

    with TestClient(main.app) as client:
        resp = client.get("/api/scanner/status")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["active_symbols"], list)
        assert isinstance(body["scanner"], dict)
        assert body["contract_guard"] is not None


def test_scanner_rescan_updates_active_symbols(monkeypatch):
    if TestClient is None:
        raise RuntimeError("TestClient unavailable")
    monkeypatch.setattr("app.bootstrap.lifespan.OptionScannerService", lambda *_args, **_kwargs: _StubScanner())
    monkeypatch.setattr("app.api.routers.scanner.OptionScannerService", lambda *_args, **_kwargs: _StubScanner())

    with TestClient(main.app) as client:
        resp = client.post("/api/scanner/rescan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["active_symbols"] == ["NIFTY", "BANKNIFTY"]
        assert body["scan_count"] == 2
