"""Unit tests for the greenfield QuantCoordinator REST + WS shell.

Exercises the coordinator branch of the existing endpoints (health,
scanner/rescan, ai/history, WS gameloop) using a fake coordinator injected
onto ``app.state.coordinator`` — no DI, no live market data.
"""

from __future__ import annotations

import pytest
from app.api.dependencies import get_coordinator
from app.main import app as _live_app
from fastapi.testclient import TestClient


class _RawView:
    """Shim exposing a fake snapshot dict as a ViewState-like object so the
    fake coordinator can route through ``view_state_to_ws`` exactly like the
    real ``QuantCoordinator.snapshot`` does."""

    def __init__(self, d: dict) -> None:
        self.symbol = d["_symbol"]
        self.tick = d.get("tick")
        self.ltp = d.get("ltp")
        self.oi = d.get("oi")
        self.quant_decision = d.get("quantDecision")
        self.risk_state = d.get("riskState")
        self.portfolio = d.get("portfolio")
        self.depth = d.get("depth")
        self.amt = d.get("amt")
        self.agent_decision = d.get("agentDecision")


class _FakeCoordinator:
    """Minimal double matching the QuantCoordinator surface the shell uses."""

    def __init__(self, symbols=("SYM",)) -> None:
        self._symbols = list(symbols)
        self._history: dict[str, list[dict]] = {s: [] for s in self._symbols}
        self._snapshots = {
            s: {
                "_symbol": s,
                "tick": {
                    "time": "2026-08-07T10:00:00Z",
                    "open": 24900.0,
                    "high": 25050.0,
                    "low": 24850.0,
                    "close": 25000.0,
                    "volume": 1200,
                },
                "portfolio": {"equity": 1_000_000.0, "positions": []},
                "depth": {"bids": [], "asks": []},
                "ltp": 25000.0,
                "oi": 12345,
            }
            for s in self._symbols
        }
        self.started = True
        self.rescanned = False
        self.switches: list[tuple[str, str]] = []

    def symbols(self) -> list[str]:
        return list(self._symbols)

    def snapshot(self, symbol: str) -> dict:
        # Mirror the real QuantCoordinator: route the projector state through
        # view_state_to_ws so the portfolio always carries the full contract.
        from quant.ws_adapter import view_state_to_ws

        raw = self._snapshots.get(symbol, {"_symbol": symbol})
        if "_symbol" not in raw:
            return raw
        return view_state_to_ws(_RawView(raw))

    def rescan(self) -> list[str]:
        self.rescanned = True
        return list(self._symbols)

    def switch_symbol(self, old: str, new: str) -> bool:
        self.switches.append((old, new))
        return True


@pytest.fixture
def client():
    from app.main import app as fastapi_app

    fake = _FakeCoordinator()
    previous = getattr(fastapi_app.state, "coordinator", None)
    fastapi_app.state.coordinator = fake
    try:
        yield TestClient(fastapi_app), fastapi_app, fake
    finally:
        if previous is None:
            # Starlette State stores attrs in _state, not __dict__ — popping
            # __dict__ is a no-op and leaks the fake coordinator into later
            # tests (deadlocks test_valid_token_passes_auth's first frame).
            try:
                del fastapi_app.state.coordinator
            except AttributeError:
                pass
        else:
            fastapi_app.state.coordinator = previous


def test_scanner_rescan_uses_coordinator(client):
    c, app, fake = client
    resp = c.post("/api/scanner/rescan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["contracts"][0]["symbol"] == "SYM"
    assert body["contracts"][0]["ltp"] == 25000.0
    assert body["contracts"][0]["oi"] == 12345
    assert fake.rescanned is True


def test_health_includes_coordinator_check(client):
    c, app, fake = client
    resp = c.get("/api/health")
    assert resp.status_code == 200
    checks = resp.json()["checks"]
    assert checks["coordinator"] == {
        "started": True,
        "symbols": ["SYM"],
        "crashedEngines": [],  # F1 liveness surface (engine crash guard)
        "staleEngines": [],  # tick-starvation liveness surface
        "status": "ok",
    }


def test_ws_gameloop_streams_coordinator_snapshot(client):
    c, app, fake = client
    with c.websocket_connect("/api/trading/ws/gameloop") as ws:
        ws.send_json({"subscribe": "SYM"})

        first = ws.receive_json()
        assert first["status"] == "server_mode"
        assert first["activeSymbols"] == ["SYM"]

        full = ws.receive_json()
        assert full["_type"] == "full"
        assert full["_symbol"] == "SYM"
        for key in ("_symbol", "tick", "portfolio", "ltp", "oi", "depth"):
            assert key in full

        ws.send_json({"ping": True})
        pong = ws.receive_json()
        assert pong == {"type": "pong"}


class _UnhaltingCoordinator(_FakeCoordinator):
    """Fake WITH unhalt_all (mirrors QuantCoordinator.unhalt_all -> int)."""

    def __init__(self, unhalted: int = 2) -> None:
        super().__init__()
        self._unhalted = unhalted

    def unhalt_all(self) -> int:
        return self._unhalted


class _NoUnhaltCoordinator:
    """Fake WITHOUT unhalt_all (coordinator present but halt surface absent)."""


def test_unhalt_via_dependency():
    # Fake coordinator WITH unhalt_all -> {"status": "ok", "unhalted_engines": N}
    _live_app.dependency_overrides[get_coordinator] = lambda: _UnhaltingCoordinator(unhalted=2)
    try:
        c = TestClient(_live_app)
        resp = c.post("/api/trading/risk/unhalt")
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "ok",
            "unhalted_engines": 2,
            "message": "Cleared risk halts across 2 engines",
        }
    finally:
        _live_app.dependency_overrides.pop(get_coordinator, None)


def test_unhalt_via_dependency_no_coordinator():
    # Fake coordinator WITHOUT unhalt_all -> {"status": "ok", "unhalted_engines": 0, ...}
    _live_app.dependency_overrides[get_coordinator] = lambda: _NoUnhaltCoordinator()
    try:
        c = TestClient(_live_app)
        resp = c.post("/api/trading/risk/unhalt")
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "ok",
            "unhalted_engines": 0,
            "message": "Coordinator not active",
        }
    finally:
        _live_app.dependency_overrides.pop(get_coordinator, None)


def test_unhalt_via_lifespan_sync():
    # Lifespan-sync path: set_coordinator(fake) then hit route with NO
    # dependency override — proves the DI singleton (not app.state) serves it.
    from app.api.dependencies import get_coordinator as _get_coord
    from app.api.dependencies import set_coordinator

    _live_app.dependency_overrides.pop(_get_coord, None)
    previous = _get_coord()
    set_coordinator(_UnhaltingCoordinator(unhalted=2))
    try:
        c = TestClient(_live_app)
        resp = c.post("/api/trading/risk/unhalt")
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "ok",
            "unhalted_engines": 2,
            "message": "Cleared risk halts across 2 engines",
        }
    finally:
        set_coordinator(previous)


def test_ws_portfolio_always_full_contract_shape(client):
    """The portfolio DTO must carry balance/equity/leverage + arrays on EVERY
    message — the frontend reduces over these fields unconditionally."""
    c, app, fake = client
    fake._snapshots["SYM"]["portfolio"] = {"positions": []}  # partial backend object
    with c.websocket_connect("/api/trading/ws/gameloop") as ws:
        ws.send_json({"subscribe": "SYM"})
        ws.receive_json()  # server_mode
        full = ws.receive_json()
        p = full["portfolio"]
        assert "balance" in p and "equity" in p and "leverage" in p
        assert isinstance(p["positions"], list)
        assert isinstance(p["closedTrades"], list)


def test_ws_never_sends_llm_history_status(client):
    """The WS viewer is deterministic-only: no llm_history_loaded status is
    ever emitted after the LLM layer removal."""
    c, app, fake = client
    with c.websocket_connect("/api/trading/ws/gameloop") as ws:
        ws.send_json({"subscribe": "SYM"})
        ws.receive_json()  # server_mode
        full = ws.receive_json()
        assert full["_type"] == "full"
        assert full.get("status") != "llm_history_loaded"
