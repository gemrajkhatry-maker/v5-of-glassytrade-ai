"""Shell for frontend contract tests against BackendV2 public HTTP and WS interfaces.

TODO:
- Add contract tests for /api/system/config and /api/ai/history payloads.
- Add websocket message-shape tests for /api/trading/ws/gameloop.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover
    TestClient = None
    _TESTCLIENT_IMPORT_ERROR = exc

try:
    from app.api.main import app
except Exception as exc:  # pragma: no cover
    app = None
    _APP_IMPORT_ERROR = exc


@pytest.mark.skip(reason="not yet implemented")
def test_system_config_endpoint_contract() -> None:
    """GET /api/system/config returns fields expected by useServerTradingSystem."""
    if app is None or TestClient is None:
        raise RuntimeError("app import unavailable")
    with TestClient(app) as client:
        # TODO: perform request and assert response schema
        # expected: status-like response contains backendPort and activeSymbols/defaultSymbol
        _resp: dict[str, object] = {}
        assert isinstance(_resp, dict)


@pytest.mark.skip(reason="not yet implemented")
def test_ai_history_endpoint_contract() -> None:
    """GET /api/ai/history returns an object with decisions list."""
    if app is None or TestClient is None:
        raise RuntimeError("app import unavailable")
    with TestClient(app) as client:
        # TODO: call endpoint and assert known keys (symbol, direction, confidence, ...)
        response = SimpleNamespace(json=lambda: {"decisions": []})
        payload = response.json()
        assert isinstance(payload, dict)
        assert "decisions" in payload


@pytest.mark.skip(reason="not yet implemented")
def test_trading_ws_gameloop_shape_contract() -> None:
    """Validate the /api/trading/ws/gameloop stream message shapes used by UI."""
    if app is None or TestClient is None:
        raise RuntimeError("app import unavailable")
    with TestClient(app) as client:
        # TODO:
        # - open websocket
        # - send {"subscribe": "<symbol>"}
        # - assert messages include status/server_mode/history_loaded/full/delta patterns
        with client.websocket_connect("/api/trading/ws/gameloop") as ws:
            ws.send_text('{"subscribe":"CRUDEOIL"}')
            message = ws.receive_text()
            assert isinstance(message, str)
