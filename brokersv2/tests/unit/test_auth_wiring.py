"""Auth provider wiring tests for Phase 1."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from brokersv2.infrastructure.dhan_adapter.client import DhanHttpClient, DhanConfig
from brokersv2.infrastructure.dhan_adapter.auth_provider import DhanAuthProvider


class TestAuthWiring:
    """Verify auth provider is properly wired into HTTP client."""

    def test_auth_provider_wired_to_http_client(self):
        """Auth provider should be stored on HTTP client."""
        config = DhanConfig(client_id="test", access_token="test-token")
        auth_provider = DhanAuthProvider(client_id="test")
        auth_provider.set_current_token("wired-token")

        client = DhanHttpClient(config, auth_provider=auth_provider)

        assert client._auth_provider is auth_provider
        assert client._headers["access-token"] == "wired-token"

    def test_http_client_falls_back_to_config_token_without_auth(self):
        """Without auth provider, client uses config token."""
        config = DhanConfig(client_id="test", access_token="config-token")
        client = DhanHttpClient(config)

        assert client._auth_provider is None
        assert client._headers["access-token"] == "config-token"


class TestTokenRefreshBeforeRequest:
    """Verify token is refreshed before each request."""

    @pytest.mark.asyncio
    async def test_ensure_valid_token_called_before_request(self):
        """_request() should call auth_provider.ensure_valid_token()."""
        config = DhanConfig(client_id="test", access_token="old-token")
        auth_provider = MagicMock()
        auth_provider.ensure_valid_token = AsyncMock(return_value="fresh-token")

        client = DhanHttpClient(config, auth_provider=auth_provider)

        # Mock the session to avoid real HTTP calls
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"success": True})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session.closed = False
        client._session = mock_session

        await client._request("GET", "/test")

        # Should have called ensure_valid_token
        auth_provider.ensure_valid_token.assert_awaited_once()
        # Headers should be updated
        assert client._headers["access-token"] == "fresh-token"

    @pytest.mark.asyncio
    async def test_token_refresh_failure_logged_not_raised(self):
        """If ensure_valid_token fails, request should still proceed."""
        config = DhanConfig(client_id="test", access_token="fallback-token")
        auth_provider = MagicMock()
        auth_provider.ensure_valid_token = AsyncMock(side_effect=Exception("Auth failed"))

        client = DhanHttpClient(config, auth_provider=auth_provider)

        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"success": True})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session.closed = False
        client._session = mock_session

        # Should not raise — just log warning and proceed with existing token
        result = await client._request("GET", "/test")
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_401_triggers_token_refresh_and_retry(self):
        """401 response should trigger token refresh and retry."""
        config = DhanConfig(client_id="test", access_token="expired-token")
        auth_provider = MagicMock()
        auth_provider.ensure_valid_token = AsyncMock(
            side_effect=["refreshed-token", "refreshed-token"]
        )

        client = DhanHttpClient(config, auth_provider=auth_provider)

        mock_session = AsyncMock()
        # First response: 401
        mock_401 = AsyncMock()
        mock_401.status = 401
        mock_401.text = AsyncMock("Unauthorized")
        mock_401.__aenter__ = AsyncMock(return_value=mock_401)
        mock_401.__aexit__ = AsyncMock(return_value=None)

        # Second response (retry): 200
        mock_200 = AsyncMock()
        mock_200.status = 200
        mock_200.json = AsyncMock(return_value={"retry": "success"})
        mock_200.__aenter__ = AsyncMock(return_value=mock_200)
        mock_200.__aexit__ = AsyncMock(return_value=None)

        mock_session.request = MagicMock(side_effect=[mock_401, mock_200])
        mock_session.closed = False
        client._session = mock_session

        result = await client._request("GET", "/test")

        assert result == {"retry": "success"}
        # ensure_valid_token should be called: once before request, once for 401 refresh
        assert auth_provider.ensure_valid_token.await_count >= 2


class TestBootstrapAuthWiring:
    """Verify auth provider is wired in bootstrap path."""

    def test_auth_provider_wired_manually(self):
        """Verify auth provider can be wired manually to adapter and client."""
        from brokersv2.infrastructure.dhan_adapter.client import DhanConfig, DhanHttpClient
        from brokersv2.infrastructure.dhan_adapter.auth_provider import DhanAuthProvider
        from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
        from brokersv2.infrastructure.dhan_adapter.adapter import DhanBrokerAdapter

        config = DhanConfig(client_id="test", access_token="test-token")
        mapper = InstrumentMapper()
        auth = DhanAuthProvider(client_id="test")
        auth.set_current_token("test-token")

        adapter = DhanBrokerAdapter(
            config=config,
            mapper=mapper,
            dry_run=True,
            auth_provider=auth,
        )

        assert adapter._auth_provider is auth
        assert adapter._client._auth_provider is auth
