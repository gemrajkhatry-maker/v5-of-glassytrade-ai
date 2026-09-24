from dataclasses import FrozenInstanceError

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_coordinator
from app.api.routers.trading import router as trading_router
from app.api.security import AuthContext, require_operator


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.setenv("GLASSYTRADE_DEV_OPERATOR_TOKEN", "paper-test-token")
    app = FastAPI()
    app.include_router(trading_router, prefix="/api")
    app.dependency_overrides[get_coordinator] = lambda: type(
        "Coordinator",
        (),
        {
            "reset_all_risk": lambda self: 1,
            "unhalt_all": lambda self: 1,
        },
    )()
    return TestClient(app)


def test_risk_reset_requires_operator_auth(client: TestClient):
    response = client.post("/api/trading/risk/reset")
    assert response.status_code in (401, 403)


def test_paper_operator_token_allows_mutating_route(client: TestClient):
    response = client.post(
        "/api/trading/risk/reset",
        headers={"Authorization": "Bearer paper-test-token"},
    )
    assert response.status_code == 200


def test_invalid_paper_token_is_rejected(client: TestClient):
    response = client.post(
        "/api/trading/risk/unhalt",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code in (401, 403)


def test_live_mode_requires_hs256_token_with_expiration(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("GAMELOOP_JWT_SECRET", "test-secret")
    token = jwt.encode(
        {"sub": "operator-1", "roles": ["operator"], "exp": 4_102_444_800},
        "test-secret",
        algorithm="HS256",
    )

    class Request:
        pass

    auth = require_operator(
        credentials=type("Credentials", (), {"scheme": "Bearer", "credentials": token})(),
        request=Request(),
    )

    assert isinstance(auth, AuthContext)
    assert auth.subject == "operator-1"


def test_unknown_mode_fails_closed(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("GLASSYTRADE_ENV", "development")
    monkeypatch.setenv("GLASSYTRADE_DEV_OPERATOR_TOKEN", "paper-test-token")

    class Request:
        pass

    with pytest.raises(HTTPException) as error:
        require_operator(
            credentials=type("Credentials", (), {"scheme": "Bearer", "credentials": "paper-test-token"})(),
            request=Request(),
        )
    assert error.value.status_code == 403


def test_live_mode_rejects_token_without_expiration(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("GAMELOOP_JWT_SECRET", "test-secret")
    token = jwt.encode(
        {"sub": "operator-1", "roles": ["operator"]},
        "test-secret",
        algorithm="HS256",
    )

    class Request:
        pass

    with pytest.raises(Exception):
        require_operator(
            credentials=type("Credentials", (), {"scheme": "Bearer", "credentials": token})(),
            request=Request(),
        )


def test_runtime_config_is_frozen_and_live_rejects_destructive_defaults():
    from glassytrade.bootstrap.runtime_config import RuntimeConfig, StartupError

    with pytest.raises(StartupError, match="unsafe live settings enabled"):
        RuntimeConfig.from_mapping(
            {
                "mode": "live",
                "account_id": "paper-account",
                "exchange": "NSE",
                "database_path": "/tmp/live.sqlite3",
                "evidence_policy": "EXACT_ONLY",
                "risk_policy": {},
                "broker_capabilities": frozenset({"native_stop"}),
                "config_fingerprint": "test",
                "clear_positions_on_restart": True,
                "reconcile_delete_stale": True,
                "allow_proxy_cvd": True,
            }
        )

    config = RuntimeConfig.from_mapping(
        {
            "mode": "paper",
            "account_id": "paper-account",
            "exchange": "nse",
            "database_path": "/tmp/paper.sqlite3",
            "evidence_policy": "EXACT_ONLY",
            "risk_policy": {"max_positions": 2},
            "broker_capabilities": ["native_stop"],
            "config_fingerprint": "paper-test",
        }
    )
    with pytest.raises(FrozenInstanceError):
        config.mode = "live"  # type: ignore[misc]
    with pytest.raises(TypeError):
        config.risk_policy["max_positions"] = 3  # type: ignore[index]
