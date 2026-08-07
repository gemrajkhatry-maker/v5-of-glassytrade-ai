"""Tests for auth provider wiring in DhanBroker factory and components."""
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDhanConfigTotpSecret:
    """DhanConfig should load DHAN_TOTP_SECRET from env."""

    def test_totp_secret_default_empty(self):
        from brokers.broker.dhan.application.config import DhanConfig
        config = DhanConfig(client_id="C1", access_token="T1")
        assert config.totp_secret == ""

    def test_totp_secret_explicit(self):
        from brokers.broker.dhan.application.config import DhanConfig
        config = DhanConfig(client_id="C1", access_token="T1", totp_secret="SECRET")
        assert config.totp_secret == "SECRET"

    def test_totp_secret_from_env(self):
        from brokers.broker.dhan.application.config import DhanConfig
        env = {
            "DHAN_CLIENT_ID": "C1",
            "DHAN_ACCESS_TOKEN": "T1",
            "DHAN_TOTP_SECRET": "MYSECRET",
        }
        with patch.dict(os.environ, env, clear=False):
            config = DhanConfig.from_env()
        assert config.totp_secret == "MYSECRET"

    def test_with_access_token_preserves_totp(self):
        from brokers.broker.dhan.application.config import DhanConfig
        config = DhanConfig(client_id="C1", access_token="T1", totp_secret="SEC")
        new_config = config.with_access_token("T2")
        assert new_config.access_token == "T2"
        assert new_config.totp_secret == "SEC"


class TestBrokerCreateAuthWiring:
    """DhanBroker.create() should wire auth_provider."""

    def test_create_wires_auth_provider(self):
        from brokers.broker.dhan.application.broker import DhanBroker
        broker = DhanBroker.create(client_id="C1", access_token="TOKEN123")
        assert broker._auth_provider is not None
        assert broker._auth_provider.access_token == "TOKEN123"
        assert broker._auth_provider.client_id == "C1"

    def test_create_wires_auth_to_http_client(self):
        from brokers.broker.dhan.application.broker import DhanBroker
        broker = DhanBroker.create(client_id="C1", access_token="TOKEN123")
        assert broker._http_client._auth_provider is broker._auth_provider

    def test_create_wires_auth_to_ws_client(self):
        from brokers.broker.dhan.application.broker import DhanBroker
        broker = DhanBroker.create(client_id="C1", access_token="TOKEN123")
        assert broker._ws_client._auth_provider is broker._auth_provider

    def test_create_with_totp_secret(self):
        from brokers.broker.dhan.application.broker import DhanBroker
        broker = DhanBroker.create(
            client_id="C1", access_token="TOKEN123", totp_secret="TOTP_SEC"
        )
        assert broker._auth_provider._totp_generator is not None


class TestWebSocketAuthRefresh:
    """WS client should refresh token before reconnect."""

    @pytest.mark.asyncio
    async def test_reconnect_refreshes_token(self):
        from brokers.broker.dhan.infrastructure.websocket_client import DhanWebSocketClient

        mock_auth = AsyncMock()
        mock_auth.ensure_valid_token = AsyncMock(return_value="NEW_TOKEN")

        ws = DhanWebSocketClient(
            access_token="OLD_TOKEN",
            client_id="C1",
            max_reconnect_attempts=1,
            reconnect_delay=0.01,
            auth_provider=mock_auth,
        )

        # _attempt_reconnect will try to connect (and fail), but should refresh first
        await ws._attempt_reconnect()

        mock_auth.ensure_valid_token.assert_called_once()
        assert ws._access_token == "NEW_TOKEN"

