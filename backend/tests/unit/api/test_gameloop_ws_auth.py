"""P1-12 — the gameloop WebSocket must require authentication.

Before this, ``/api/trading/ws/gameloop`` accepted any connection: any client
on the network could stream the live position book, stop levels and risk state.

Policy under test:
  * a configured ``GAMELOOP_JWT_SECRET`` -> a valid HS256 JWT is REQUIRED;
  * live mode with no secret -> refuse (fail-closed);
  * paper/development with no secret -> allow, but log loudly (design-spec
    invariant 2 keeps paper operational).

Rejections accept the socket first and then send
``{"error": "unauthorized", ...}`` before closing with 4401, so a client can
tell an auth failure apart from a dead backend.
"""

from __future__ import annotations

import time

import jwt
import pytest
from app.api.websocket import auth as ws_auth
from app.main import app as _live_app
from fastapi.testclient import TestClient

WS_PATH = "/api/trading/ws/gameloop"
SECRET = "test-secret-not-for-production"


def _token(secret: str = SECRET, *, expires_in: int = 300, sub: str = "operator") -> str:
    return jwt.encode(
        {"sub": sub, "exp": int(time.time()) + expires_in}, secret, algorithm="HS256"
    )


@pytest.fixture
def paper_client(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    return TestClient(_live_app)


@pytest.fixture
def configured_secret(monkeypatch):
    monkeypatch.setenv(ws_auth.SECRET_ENV_VAR, SECRET)
    return SECRET


def _first_payload(client: TestClient, url: str) -> dict:
    """Connect, read the first server frame, and return it."""
    with client.websocket_connect(url) as ws:
        return ws.receive_json()


class TestSecretResolution:
    """``resolve_secret`` must be explicit and must not borrow other secrets."""

    def test_uses_the_dedicated_env_var(self, monkeypatch):
        monkeypatch.setenv(ws_auth.SECRET_ENV_VAR, "abc")
        assert ws_auth.resolve_secret() == "abc"

    def test_unset_is_none(self, monkeypatch):
        monkeypatch.delenv(ws_auth.SECRET_ENV_VAR, raising=False)
        assert ws_auth.resolve_secret() is None

    def test_does_not_borrow_the_broker_api_secret(self, monkeypatch):
        """Key hygiene: the Dhan API secret must not double as the WS secret."""
        monkeypatch.delenv(ws_auth.SECRET_ENV_VAR, raising=False)
        monkeypatch.setenv("API_SECRET", "dhan-api-secret")
        assert ws_auth.resolve_secret() is None

    def test_blank_value_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv(ws_auth.SECRET_ENV_VAR, "   ")
        assert ws_auth.resolve_secret() is None


class TestTokenVerification:
    """HS256 only; expiry required; no algorithm confusion."""

    def test_valid_token_returns_claims(self):
        claims = ws_auth.verify_token(_token(), SECRET)
        assert claims["sub"] == "operator"

    def test_wrong_secret_rejected(self):
        with pytest.raises(ws_auth.WebSocketAuthError):
            ws_auth.verify_token(_token(secret="other"), SECRET)

    def test_expired_token_rejected(self):
        with pytest.raises(ws_auth.WebSocketAuthError):
            ws_auth.verify_token(_token(expires_in=-60), SECRET)

    def test_token_without_expiry_rejected(self):
        """A never-expiring token must not be accepted."""
        token = jwt.encode({"sub": "operator"}, SECRET, algorithm="HS256")
        with pytest.raises(ws_auth.WebSocketAuthError):
            ws_auth.verify_token(token, SECRET)

    def test_alg_none_token_rejected(self):
        """The classic alg=none forgery must not pass."""
        import base64
        import json as _json

        def _b64(segment: dict) -> str:
            raw = _json.dumps(segment, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")

        # alg=none means an EMPTY signature segment.
        forged = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': 'x', 'exp': 9999999999})}."
        with pytest.raises(ws_auth.WebSocketAuthError):
            ws_auth.verify_token(forged, SECRET)

    def test_garbage_token_rejected(self):
        with pytest.raises(ws_auth.WebSocketAuthError):
            ws_auth.verify_token("not-a-jwt", SECRET)

    def test_empty_token_rejected(self):
        with pytest.raises(ws_auth.WebSocketAuthError):
            ws_auth.verify_token("", SECRET)


class TestTokenExtraction:
    """Query param, Authorization header and bearer subprotocol are accepted."""

    def test_query_param_with_bearer_prefix(self, paper_client):
        with paper_client.websocket_connect(f"{WS_PATH}?token=bearer%20{_token()}"):
            pass

    def test_subprotocol_bearer_form(self):
        assert ws_auth.token_from_subprotocol("bearer.abc.def") == "abc.def"

    def test_non_bearer_subprotocol_yields_none(self):
        assert ws_auth.token_from_subprotocol("graphql-ws") is None

    def test_authorization_header_form(self):
        assert ws_auth.token_from_authorization("Bearer abc.def") == "abc.def"

    def test_authorization_header_requires_bearer_scheme(self):
        assert ws_auth.token_from_authorization("Basic abc") is None
        assert ws_auth.token_from_authorization(None) is None


class TestWebSocketEnforcement:
    """End-to-end behaviour through the real router."""

    def test_missing_token_is_rejected(self, paper_client, configured_secret):
        payload = _first_payload(paper_client, WS_PATH)
        assert payload.get("error") == "unauthorized"
        assert "token" in payload.get("reason", "").lower()

    def test_invalid_token_is_rejected(self, paper_client, configured_secret):
        payload = _first_payload(paper_client, f"{WS_PATH}?token=garbage")
        assert payload.get("error") == "unauthorized"

    def test_wrong_secret_is_rejected(self, paper_client, configured_secret):
        payload = _first_payload(
            paper_client, f"{WS_PATH}?token={_token(secret='other-secret')}"
        )
        assert payload.get("error") == "unauthorized"

    def test_expired_token_is_rejected(self, paper_client, configured_secret):
        payload = _first_payload(
            paper_client, f"{WS_PATH}?token={_token(expires_in=-1)}"
        )
        assert payload.get("error") == "unauthorized"

    def test_valid_token_passes_auth(self, paper_client, configured_secret):
        """Past auth, the handler proceeds (no coordinator -> different error)."""
        payload = _first_payload(paper_client, f"{WS_PATH}?token={_token()}")
        assert payload.get("error") != "unauthorized"

    def test_live_mode_without_secret_refuses_connection(self, monkeypatch):
        monkeypatch.setenv("GLASSYTRADE_ENV", "live")
        monkeypatch.delenv("TRADING_MODE", raising=False)
        monkeypatch.delenv(ws_auth.SECRET_ENV_VAR, raising=False)
        client = TestClient(_live_app)
        payload = _first_payload(client, WS_PATH)
        assert payload.get("error") == "unauthorized"

    def test_paper_mode_without_secret_stays_operational(self, paper_client, monkeypatch):
        """Invariant 2: paper mode must keep working during the migration."""
        monkeypatch.delenv(ws_auth.SECRET_ENV_VAR, raising=False)
        payload = _first_payload(paper_client, WS_PATH)
        assert payload.get("error") != "unauthorized"
