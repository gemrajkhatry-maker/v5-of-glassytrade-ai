"""
Tests for Dhan Infrastructure Layer.

This module tests all infrastructure layer components:
    - DhanHttpClient: HTTP client with retry logic
    - DhanWebSocketClient: WebSocket client with reconnection
    - DhanSymbolMapper: Symbol to security ID mapping
    - DhanAuthProvider: Authentication provider
    - TokenBucketRateLimiter: Rate limiting implementation
    - DhanCircuitBreaker: Circuit breaker pattern implementation
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from brokers.broker.dhan.infrastructure import (
    DhanHttpClient,
    DhanWebSocketClient,
    DhanSymbolMapper,
    DhanAuthProvider,
    TokenBucketRateLimiter,
    DhanCircuitBreaker,
    RetryConfig,
    DEFAULT_RATE_LIMITS,
)

from brokers.broker.dhan.ports import (
    IHttpClient,
    IWebSocketClient,
    ISymbolMapper,
    IAuthProvider,
    IRateLimiter,
    ICircuitBreaker,
    HttpRequest,
    HttpResponse,
    WSMessage,
)

# Broker-agnostic imports for tests
from brokers.broker.entities import Instrument
from brokers.broker.types import Exchange

from brokers.broker.dhan.domain import (
    DhanError,
    DhanNetworkError,
    DhanConnectionError,
    DhanTimeoutError,
    ORDERS,
    DhanRateLimitError,
    DhanAuthError,
    DhanTokenInvalidError,
    DhanTokenExpiredError,
    DhanSymbolNotFoundError,
    DhanHistoricalDataError,
    ExchangeSegment,
    InstrumentTypeEnum,
    OptionType,
    HISTORICAL_MAX_DAYS,
    RATE_LIMIT_HISTORICAL,
)


# =============================================================================
# Tests for DhanHttpClient
# =============================================================================

class TestDhanHttpClient:
    """Tests for DhanHttpClient implementation."""
    
    def test_create_client(self, http_client_config):
        """Test creating HTTP client."""
        client = DhanHttpClient(
            base_url=http_client_config["base_url"],
            access_token=http_client_config["access_token"],
            timeout=http_client_config["timeout"],
        )
        
        assert client.base_url == "https://api.dhan.co"
        assert client.access_token == "test_access_token_12345"
        assert client.is_closed is False
    
    def test_client_implements_protocol(self, dhan_http_client):
        """Test that DhanHttpClient implements IHttpClient protocol."""
        assert isinstance(dhan_http_client, IHttpClient)
    
    def test_get_headers(self, dhan_http_client):
        """Test _get_headers method returns Dhan v2 headers (access-token, client-id)."""
        headers = dhan_http_client._get_headers()
        
        assert "access-token" in headers
        assert headers["access-token"] == "test_access_token_12345"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
    
    def test_repr(self, dhan_http_client):
        """Test string representation."""
        repr_str = repr(dhan_http_client)
        assert "DhanHttpClient" in repr_str
        assert "https://api.dhan.co" in repr_str
    
    @pytest.mark.asyncio
    async def test_close(self, dhan_http_client):
        """Test closing the client."""
        await dhan_http_client.close()
        assert dhan_http_client.is_closed is True
    
    @pytest.mark.asyncio
    async def test_context_manager(self, http_client_config):
        """Test async context manager usage."""
        async with DhanHttpClient(
            base_url=http_client_config["base_url"],
            access_token=http_client_config["access_token"],
        ) as client:
            assert client.is_closed is False
        
        assert client.is_closed is True
    
    @pytest.mark.asyncio
    async def test_get_success(self, dhan_http_client, mock_aiohttp_session, mock_aiohttp_response):
        """Test successful GET request."""
        mock_aiohttp_response.status = 200
        mock_aiohttp_response.json.return_value = {"data": "test"}

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_aiohttp_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_aiohttp_session.request = MagicMock(return_value=ctx)

        with patch.object(dhan_http_client, '_get_session', return_value=mock_aiohttp_session):
            response = await dhan_http_client.get("/test")

            assert response.status_code == 200
            assert response.data == {"data": "test"}

    @pytest.mark.asyncio
    async def test_post_success(self, dhan_http_client, mock_aiohttp_session, mock_aiohttp_response):
        """Test successful POST request."""
        mock_aiohttp_response.status = 200
        mock_aiohttp_response.json.return_value = {"orderId": "12345"}

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_aiohttp_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_aiohttp_session.request = MagicMock(return_value=ctx)

        with patch.object(dhan_http_client, '_get_session', return_value=mock_aiohttp_session):
            response = await dhan_http_client.post("/orders", json={"symbol": "NIFTY"})

            assert response.status_code == 200
            assert response.data["orderId"] == "12345"

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, dhan_http_client, mock_aiohttp_session, mock_aiohttp_response):
        """Test rate limit error handling."""
        mock_aiohttp_response.status = 429
        mock_aiohttp_response.headers = {"Retry-After": "60"}
        mock_aiohttp_response.json.return_value = {"message": "Rate limit exceeded"}

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_aiohttp_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_aiohttp_session.request = MagicMock(return_value=ctx)

        with patch.object(dhan_http_client, '_get_session', return_value=mock_aiohttp_session):
            with pytest.raises(DhanRateLimitError) as exc_info:
                await dhan_http_client.get("/test")

            assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    async def test_timeout_error(self, dhan_http_client, mock_aiohttp_session, mock_aiohttp_response):
        """Test timeout error handling."""
        mock_aiohttp_response.status = 408
        mock_aiohttp_response.json.return_value = {"message": "Request timeout"}

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_aiohttp_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_aiohttp_session.request = MagicMock(return_value=ctx)

        with patch.object(dhan_http_client, '_get_session', return_value=mock_aiohttp_session):
            with pytest.raises(DhanTimeoutError):
                await dhan_http_client.get("/test")

    @pytest.mark.asyncio
    async def test_auth_error_401(self, dhan_http_client, mock_aiohttp_session, mock_aiohttp_response):
        """Test authentication error handling (401)."""
        mock_aiohttp_response.status = 401
        mock_aiohttp_response.json.return_value = {
            "errorCode": "DH-1001",
            "message": "Invalid token"
        }

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_aiohttp_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_aiohttp_session.request = MagicMock(return_value=ctx)

        with patch.object(dhan_http_client, '_get_session', return_value=mock_aiohttp_session):
            with pytest.raises(DhanTokenInvalidError):
                await dhan_http_client.get("/test")

    @pytest.mark.asyncio
    async def test_auth_error_403(self, dhan_http_client, mock_aiohttp_session, mock_aiohttp_response):
        """Test authentication error handling (403)."""
        mock_aiohttp_response.status = 403
        mock_aiohttp_response.json.return_value = {
            "errorCode": "DH-1002",
            "message": "Token expired"
        }

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_aiohttp_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_aiohttp_session.request = MagicMock(return_value=ctx)

        with patch.object(dhan_http_client, '_get_session', return_value=mock_aiohttp_session):
            with pytest.raises(DhanTokenExpiredError):
                await dhan_http_client.get("/test")


class TestRetryConfig:
    """Tests for RetryConfig."""
    
    def test_default_config(self):
        """Test default retry configuration."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.backoff_factor == 0.5
        assert config.max_delay == 30.0
    
    def test_get_delay(self):
        """Test delay calculation with exponential backoff."""
        config = RetryConfig(backoff_factor=0.5)
        
        # First retry: 0.5 * 2^0 = 0.5
        assert config.get_delay(0) == 0.5
        
        # Second retry: 0.5 * 2^1 = 1.0
        assert config.get_delay(1) == 1.0
        
        # Third retry: 0.5 * 2^2 = 2.0
        assert config.get_delay(2) == 2.0
    
    def test_delay_capped_at_max(self):
        """Test that delay is capped at max_delay."""
        config = RetryConfig(backoff_factor=1.0, max_delay=10.0)
        
        # Large attempt number
        delay = config.get_delay(10)
        assert delay == 10.0  # Capped at max_delay


# =============================================================================
# Tests for DhanWebSocketClient
# =============================================================================

class TestDhanWebSocketClient:
    """Tests for DhanWebSocketClient implementation."""
    
    def test_create_client(self):
        """Test creating WebSocket client."""
        client = DhanWebSocketClient(
            ws_url="wss://api.dhan.co/ws",
            access_token="test_token",
            client_id="CLIENT123",
        )
        
        assert client._ws_url == "wss://api.dhan.co/ws"
        assert client._access_token == "test_token"
        assert client._client_id == "CLIENT123"
        assert client.is_connected is False
    
    def test_client_implements_protocol(self, dhan_ws_client):
        """Test that DhanWebSocketClient implements IWebSocketClient protocol."""
        assert isinstance(dhan_ws_client, IWebSocketClient)
    
    def test_repr(self, dhan_ws_client):
        """Test string representation."""
        repr_str = repr(dhan_ws_client)
        assert "DhanWebSocketClient" in repr_str
        assert "connected=" in repr_str
    
    def test_subscriptions_property(self, dhan_ws_client):
        """Test subscriptions property."""
        assert dhan_ws_client.subscriptions == set()
        
        # Add subscription
        dhan_ws_client._subscriptions.add("12345")
        assert "12345" in dhan_ws_client.subscriptions
    
    def test_parse_message_tick(self, dhan_ws_client):
        """Test parsing tick message."""
        raw_message = json.dumps({"LTP": 18050.50, "SecurityId": "12345"})
        message = dhan_ws_client._parse_message(raw_message)
        
        assert message is not None
        assert message.type == "tick"
        assert message.data["LTP"] == 18050.50
    
    def test_parse_message_quote(self, dhan_ws_client):
        """Test parsing quote message."""
        raw_message = json.dumps({
            "LTP": 18050.50,
            "Open": 18000.00,
            "High": 18100.00,
            "Low": 17950.00
        })
        message = dhan_ws_client._parse_message(raw_message)
        
        assert message is not None
        assert message.type == "quote"
    
    def test_parse_message_order(self, dhan_ws_client):
        """Test parsing order message."""
        raw_message = json.dumps({
            "orderId": "ORDER123",
            "orderStatus": "TRADED"
        })
        message = dhan_ws_client._parse_message(raw_message)
        
        assert message is not None
        assert message.type == "order"
    
    def test_parse_message_error(self, dhan_ws_client):
        """Test parsing error message."""
        raw_message = json.dumps({"error": "Something went wrong"})
        message = dhan_ws_client._parse_message(raw_message)
        
        assert message is not None
        assert message.type == "error"
    
    def test_parse_message_invalid_json(self, dhan_ws_client):
        """Test parsing invalid JSON message."""
        raw_message = "not valid json"
        message = dhan_ws_client._parse_message(raw_message)
        
        assert message is not None
        assert message.type == "raw"
        assert "raw" in message.data
    
    def test_determine_message_type(self, dhan_ws_client):
        """Test _classify_json method (JSON text frame classifier)."""
        assert dhan_ws_client._classify_json({"LTP": 100}) == "tick"
        assert dhan_ws_client._classify_json({"Open": 100}) == "quote"
        assert dhan_ws_client._classify_json({"orderId": "123"}) == "order"
        assert dhan_ws_client._classify_json({"error": "msg"}) == "error"
        assert dhan_ws_client._classify_json({"status": "ok"}) == "status"
        assert dhan_ws_client._classify_json({}) == "unknown"

    @pytest.mark.asyncio
    async def test_subscribe_populates_ws_sid_to_rest(self, dhan_ws_client):
        """Subscribe must pre-populate _ws_sid_to_rest so binary decode resolves IDs."""
        from unittest.mock import AsyncMock, PropertyMock, patch

        # Mock is_connected to return True and _send_subscription to no-op
        with patch.object(type(dhan_ws_client), "is_connected", new_callable=PropertyMock, return_value=True):
            dhan_ws_client._send_subscription = AsyncMock()
            await dhan_ws_client.subscribe(["1333", "45678", "99"])

        assert dhan_ws_client._ws_sid_to_rest[1333] == "1333"
        assert dhan_ws_client._ws_sid_to_rest[45678] == "45678"
        assert dhan_ws_client._ws_sid_to_rest[99] == "99"

    @pytest.mark.asyncio
    async def test_subscribe_handles_non_numeric_ids(self, dhan_ws_client):
        """Non-numeric security IDs should not crash subscribe."""
        from unittest.mock import AsyncMock, PropertyMock, patch

        with patch.object(type(dhan_ws_client), "is_connected", new_callable=PropertyMock, return_value=True):
            dhan_ws_client._send_subscription = AsyncMock()
            await dhan_ws_client.subscribe(["abc", "1333"])

        assert 1333 in dhan_ws_client._ws_sid_to_rest
        # "abc" silently skipped — no crash


# =============================================================================
# Tests for TokenBucketRateLimiter
# =============================================================================

class TestTokenBucketRateLimiter:
    """Tests for TokenBucketRateLimiter implementation."""
    
    def test_create_rate_limiter(self, rate_limiter):
        """Test creating rate limiter."""
        assert rate_limiter is not None
        assert isinstance(rate_limiter, IRateLimiter)
    
    def test_initial_tokens(self, rate_limiter):
        """Test initial token count."""
        # Should start with burst capacity
        tokens = rate_limiter.get_tokens("default")
        assert tokens > 0
    
    def test_get_tokens_unknown_category(self, rate_limiter):
        """Test get_tokens for unknown category."""
        tokens = rate_limiter.get_tokens("unknown_category")
        # Should create bucket with default config
        assert tokens >= 0
    
    def test_get_wait_time(self, rate_limiter):
        """Test get_wait_time method."""
        wait_time = rate_limiter.get_wait_time("default")
        assert wait_time >= 0
    
    @pytest.mark.asyncio
    async def test_acquire_token(self, rate_limiter):
        """Test acquiring a token."""
        # Should succeed immediately with tokens available
        await rate_limiter.acquire("default")
        
        # Token count should decrease
        tokens = rate_limiter.get_tokens("default")
        assert tokens < 20  # Default burst is 20
    
    @pytest.mark.asyncio
    async def test_acquire_multiple_tokens(self, rate_limiter):
        """Test acquiring multiple tokens."""
        # Acquire several tokens
        for _ in range(5):
            await rate_limiter.acquire("market_data")
        
        tokens = rate_limiter.get_tokens("market_data")
        assert tokens < 20  # Should have consumed tokens
    
    def test_repr(self, rate_limiter):
        """Test string representation."""
        repr_str = repr(rate_limiter)
        assert "TokenBucketRateLimiter" in repr_str


# =============================================================================
# Tests for DhanCircuitBreaker
# =============================================================================

class TestDhanCircuitBreaker:
    """Tests for DhanCircuitBreaker implementation."""
    
    def test_create_circuit_breaker(self, circuit_breaker):
        """Test creating circuit breaker."""
        assert circuit_breaker is not None
        assert isinstance(circuit_breaker, ICircuitBreaker)
    
    def test_initial_state(self, circuit_breaker):
        """Test initial state is closed."""
        assert circuit_breaker.state == "closed"
        assert circuit_breaker.is_closed is True
        assert circuit_breaker.is_open is False
        assert circuit_breaker.is_half_open is False
    
    def test_failure_count(self, circuit_breaker):
        """Test failure_count property."""
        assert circuit_breaker.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_execute_success(self, circuit_breaker):
        """Test executing successful operation."""
        async def success_op():
            return "success"
        
        result = await circuit_breaker.execute(success_op)
        assert result == "success"
        assert circuit_breaker.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_execute_failure(self, circuit_breaker):
        """Test executing failed operation."""
        async def fail_op():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            await circuit_breaker.execute(fail_op)
        
        assert circuit_breaker.failure_count == 1
    
    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        """Test circuit opens after failure threshold."""
        circuit_breaker = DhanCircuitBreaker()
        circuit_breaker._config.failure_threshold = 3
        
        async def fail_op():
            raise ValueError("Test error")
        
        # Trigger failures up to threshold
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker.execute(fail_op)
        
        assert circuit_breaker.is_open is True
    
    @pytest.mark.asyncio
    async def test_circuit_fails_fast_when_open(self):
        """Test circuit fails fast when open."""
        circuit_breaker = DhanCircuitBreaker()
        circuit_breaker._config.failure_threshold = 1
        circuit_breaker._config.timeout = 60.0  # Long timeout
        
        async def fail_op():
            raise ValueError("Test error")
        
        # Trigger failure to open circuit
        with pytest.raises(ValueError):
            await circuit_breaker.execute(fail_op)
        
        assert circuit_breaker.is_open is True
        
        # Next call should fail fast with DhanNetworkError
        with pytest.raises(DhanNetworkError):
            await circuit_breaker.execute(lambda: None)
    
    def test_reset(self, circuit_breaker):
        """Test reset method."""
        circuit_breaker._failure_count = 5
        circuit_breaker._state = circuit_breaker._state.__class__.OPEN
        
        circuit_breaker.reset()
        
        assert circuit_breaker.state == "closed"
        assert circuit_breaker.failure_count == 0
    
    def test_force_open(self, circuit_breaker):
        """Test force_open method."""
        circuit_breaker.force_open()
        
        assert circuit_breaker.is_open is True
    
    def test_repr(self, circuit_breaker):
        """Test string representation."""
        repr_str = repr(circuit_breaker)
        assert "DhanCircuitBreaker" in repr_str
        assert "state=" in repr_str


# =============================================================================
# Tests for DhanSymbolMapper
# =============================================================================

class TestDhanSymbolMapper:
    """Tests for DhanSymbolMapper implementation."""
    
    @pytest.fixture
    def symbol_mapper(self):
        """Create a DhanSymbolMapper instance."""
        return DhanSymbolMapper()
    
    def test_create_mapper(self, symbol_mapper):
        """Test creating symbol mapper."""
        assert symbol_mapper is not None
        assert isinstance(symbol_mapper, ISymbolMapper)
    
    def test_mapper_has_instruments(self, symbol_mapper):
        """Test that mapper has instruments property."""
        # Instruments should be a dict or similar
        assert hasattr(symbol_mapper, '_instruments') or hasattr(symbol_mapper, 'instruments')


# =============================================================================
# Tests for DhanAuthProvider
# =============================================================================

class TestDhanAuthProvider:
    """Tests for DhanAuthProvider implementation."""
    
    @pytest.fixture
    def auth_provider(self):
        """Create a DhanAuthProvider instance."""
        return DhanAuthProvider()
    
    @pytest.fixture
    def auth_provider_with_token(self):
        """Create a DhanAuthProvider instance with token set."""
        auth = DhanAuthProvider()
        auth.set_token("test_token", client_id="CLIENT123")
        return auth
    
    def test_create_auth_provider(self, auth_provider):
        """Test creating auth provider."""
        assert auth_provider is not None
        assert isinstance(auth_provider, IAuthProvider)
    
    def test_get_credentials(self, auth_provider_with_token):
        """Test getting credentials."""
        assert auth_provider_with_token.access_token == "test_token"
        assert auth_provider_with_token.client_id == "CLIENT123"
    
    def test_is_authenticated(self, auth_provider_with_token):
        """Test is_authenticated property."""
        assert auth_provider_with_token.is_authenticated is True
    
    def test_is_authenticated_no_token(self, auth_provider):
        """Test is_authenticated with no token."""
        assert auth_provider.is_authenticated is False
    
    def test_set_token(self, auth_provider):
        """Test setting token directly."""
        auth_provider.set_token("new_token", client_id="CLIENT456")
        
        assert auth_provider.access_token == "new_token"
        assert auth_provider.client_id == "CLIENT456"
        assert auth_provider.is_authenticated is True
    
    def test_set_token_with_totp_secret(self, auth_provider):
        """Test setting token with TOTP secret."""
        auth_provider.set_token("new_token", client_id="CLIENT456", totp_secret="JBSWY3DPEHPK3PXP")
        
        assert auth_provider.access_token == "new_token"
        assert auth_provider._totp_secret == "JBSWY3DPEHPK3PXP"
    
    def test_set_totp_secret(self, auth_provider):
        """Test setting TOTP secret."""
        auth_provider.set_totp_secret("JBSWY3DPEHPK3PXP")
        
        assert auth_provider._totp_secret == "JBSWY3DPEHPK3PXP"
    
    def test_token_age(self, auth_provider_with_token):
        """Test token_age property."""
        from datetime import timedelta
        
        age = auth_provider_with_token.token_age
        assert age is not None
        assert age < timedelta(seconds=1)  # Just created
    
    def test_token_expires_at_epoch(self, auth_provider_with_token):
        """Test token_expires_at_epoch property."""
        import time

        expires_at = auth_provider_with_token.token_expires_at_epoch
        assert expires_at is not None
        # Default expiry is 24 hours
        expected = time.time() + 24 * 3600
        assert abs(expires_at - expected) < 1
    
    def test_time_until_expiry(self, auth_provider_with_token):
        """Test time_until_expiry property."""
        from datetime import timedelta
        
        time_remaining = auth_provider_with_token.time_until_expiry
        assert time_remaining is not None
        # Should be close to 24 hours
        assert time_remaining > timedelta(hours=23, minutes=59)
    
    def test_needs_refresh_new_token(self, auth_provider_with_token):
        """Test needs_refresh with new token."""
        # New token should not need refresh
        assert auth_provider_with_token.needs_refresh is False
    
    def test_needs_refresh_near_expiry(self, auth_provider):
        """Test needs_refresh when token is near expiry."""
        import time as _time

        # Set token as if it was created 23h55m ago
        auth_provider.set_token("test_token", client_id="CLIENT123")
        auth_provider._authenticated_at = _time.time() - (23 * 3600 + 55 * 60)

        # Should need refresh (within 5 minute threshold)
        assert auth_provider.needs_refresh is True

    def test_is_expired(self, auth_provider):
        """Test is_expired property."""
        import time as _time

        # Set token as if it was created 25 hours ago
        auth_provider.set_token("test_token", client_id="CLIENT123")
        auth_provider._authenticated_at = _time.time() - 25 * 3600
        
        assert auth_provider.is_expired is True
    
    def test_clear(self, auth_provider_with_token):
        """Test clearing authentication data."""
        auth_provider_with_token.clear()
        
        assert auth_provider_with_token.access_token is None
        assert auth_provider_with_token.client_id is None
        assert auth_provider_with_token.is_authenticated is False
    
    def test_repr(self, auth_provider_with_token):
        """Test string representation."""
        repr_str = repr(auth_provider_with_token)
        assert "DhanAuthProvider" in repr_str
        assert "authenticated=True" in repr_str
    
    @pytest.mark.asyncio
    async def test_ensure_valid_token_valid(self, auth_provider_with_token):
        """Test ensure_valid_token with valid token."""
        token = await auth_provider_with_token.ensure_valid_token()
        assert token == "test_token"
    
    @pytest.mark.asyncio
    async def test_ensure_valid_token_no_token(self, auth_provider):
        """Test ensure_valid_token with no token."""
        with pytest.raises(DhanAuthError):
            await auth_provider.ensure_valid_token()
    
    @pytest.mark.asyncio
    async def test_handle_auth_error_token_expired(self, auth_provider_with_token):
        """Test handle_auth_error with expired token error."""
        # Without HTTP client, should return False
        error = DhanTokenExpiredError("Token expired")
        result = await auth_provider_with_token.handle_auth_error(error)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_handle_auth_error_other_error(self, auth_provider_with_token):
        """Test handle_auth_error with non-auth error."""
        error = ValueError("Some error")
        result = await auth_provider_with_token.handle_auth_error(error)
        assert result is False


class TestDhanAuthProviderTokenRefresh:
    """Tests for DhanAuthProvider token refresh functionality."""

    @pytest.fixture
    def mock_http_client(self):
        """Create a mock HTTP client."""
        client = AsyncMock(spec=IHttpClient)
        return client

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, mock_http_client):
        """Test successful token refresh."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_token("old_token", client_id="CLIENT123")

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "new_token"}
            mock_req.get.return_value = mock_resp

            new_token = await auth.refresh_token()

        assert new_token == "new_token"
        assert auth.access_token == "new_token"

    @pytest.mark.asyncio
    async def test_refresh_token_expired_session(self, mock_http_client):
        """Test token refresh with expired session."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_token("old_token", client_id="CLIENT123")

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.json.return_value = {"message": "Session expired"}
            mock_req.get.return_value = mock_resp

            with pytest.raises(DhanTokenExpiredError):
                await auth.refresh_token()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_refreshes_near_expiry(self, mock_http_client):
        """Test ensure_valid_token refreshes when near expiry."""
        import time as _time
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_token("old_token", client_id="CLIENT123")
        # Set token as near expiry (23h55m ago)
        auth._authenticated_at = _time.time() - (23 * 3600 + 55 * 60)

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "refreshed_token"}
            mock_req.get.return_value = mock_resp

            token = await auth.ensure_valid_token()

        assert token == "refreshed_token"
        mock_req.get.assert_called_once()


class TestDhanAuthProviderTOTPGeneration:
    """Tests for DhanAuthProvider TOTP-based token generation."""
    
    @pytest.fixture
    def mock_http_client(self):
        """Create a mock HTTP client."""
        client = AsyncMock(spec=IHttpClient)
        return client
    
    @pytest.fixture
    def totp_secret(self):
        """Return a test TOTP secret."""
        return "JBSWY3DPEHPK3PXP"  # Standard test secret
    
    @pytest.mark.asyncio
    async def test_generate_token_with_totp_secret(self, mock_http_client, totp_secret):
        """Test generating token using TOTP secret."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_pin("123456")

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "generated_token"}
            mock_req.post.return_value = mock_resp

            token = await auth.generate_token("CLIENT123", totp_secret=totp_secret)

        assert token == "generated_token"
        assert auth.access_token == "generated_token"
        assert auth._totp_secret == totp_secret
        mock_req.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_token_with_stored_totp_secret(self, mock_http_client, totp_secret):
        """Test generating token using stored TOTP secret."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_totp_secret(totp_secret)
        auth.set_pin("123456")

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "generated_token"}
            mock_req.post.return_value = mock_resp

            token = await auth.generate_token("CLIENT123")

        assert token == "generated_token"
        assert auth.access_token == "generated_token"
    
    @pytest.mark.asyncio
    async def test_generate_token_fails_without_totp_secret(self, mock_http_client):
        """Test generate_token fails when no TOTP secret is available."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider
        
        auth = DhanAuthProvider(http_client=mock_http_client)
        
        with pytest.raises(DhanAuthError) as exc_info:
            await auth.generate_token("CLIENT123")
        
        assert "TOTP secret not configured" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_ensure_valid_token_generates_when_expired_with_totp(self, mock_http_client, totp_secret):
        """Test ensure_valid_token generates new token when expired and TOTP is available."""
        import time as _time
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_token("old_token", client_id="CLIENT123", totp_secret=totp_secret)
        auth.set_pin("123456")
        # Set token as expired (25 hours ago)
        auth._authenticated_at = _time.time() - 25 * 3600

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "regenerated_token"}
            mock_req.post.return_value = mock_resp

            token = await auth.ensure_valid_token()

        assert token == "regenerated_token"
        mock_req.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_generates_when_no_token_with_totp(self, mock_http_client, totp_secret):
        """Test ensure_valid_token generates new token when no token and TOTP is available."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_totp_secret(totp_secret)
        auth.set_pin("123456")
        auth._client_id = "CLIENT123"  # Set client_id directly for test

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "new_token"}
            mock_req.post.return_value = mock_resp

            token = await auth.ensure_valid_token()

        assert token == "new_token"
        mock_req.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_auth_error_regenerates_with_totp(self, mock_http_client, totp_secret):
        """Test handle_auth_error regenerates token using TOTP."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_token("old_token", client_id="CLIENT123", totp_secret=totp_secret)
        auth.set_pin("123456")

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "regenerated_token"}
            mock_req.post.return_value = mock_resp

            error = DhanTokenExpiredError("Token expired")
            result = await auth.handle_auth_error(error)

        assert result is True
        assert auth.access_token == "regenerated_token"
    
    def test_set_totp_secret_initializes_generator(self, totp_secret):
        """Test set_totp_secret initializes TOTPGenerator."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider
        
        auth = DhanAuthProvider()
        auth.set_totp_secret(totp_secret)
        
        assert auth._totp_secret == totp_secret
        assert auth._totp_generator is not None
    
    def test_set_token_with_totp_secret(self, totp_secret):
        """Test set_token with TOTP secret initializes generator."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider
        
        auth = DhanAuthProvider()
        auth.set_token("test_token", client_id="CLIENT123", totp_secret=totp_secret)
        
        assert auth._totp_secret == totp_secret
        assert auth._totp_generator is not None


class TestDhanAuthProviderRefreshToken:
    """Tests for DhanAuthProvider refresh_token storage and usage."""
    
    @pytest.fixture
    def mock_http_client(self):
        """Create a mock HTTP client."""
        client = AsyncMock(spec=IHttpClient)
        return client
    
    @pytest.mark.asyncio
    async def test_authenticate_stores_access_token(self, mock_http_client):
        """Test authenticate stores access_token from response."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_pin("123456")

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "access_token"}
            mock_req.post.return_value = mock_resp

            await auth.authenticate("CLIENT123", totp="654321")

        assert auth.access_token == "access_token"
        assert auth.client_id == "CLIENT123"

    @pytest.mark.asyncio
    async def test_refresh_token_uses_access_token_header(self, mock_http_client):
        """Test refresh_token sends access-token header."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_token("old_token", client_id="CLIENT123")

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "new_access_token"}
            mock_req.get.return_value = mock_resp

            await auth.refresh_token()

            # Verify access-token header was sent
            call_args = mock_req.get.call_args
            assert call_args[1]["headers"]["access-token"] == "old_token"
            assert call_args[1]["headers"]["dhanClientId"] == "CLIENT123"

    @pytest.mark.asyncio
    async def test_refresh_updates_access_token(self, mock_http_client):
        """Test refresh updates the stored access token."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider(http_client=mock_http_client)
        auth.set_token("old_token", client_id="CLIENT123")

        with patch("brokers.broker.dhan.infrastructure.auth_provider._requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"accessToken": "new_access_token"}
            mock_req.get.return_value = mock_resp

            await auth.refresh_token()

        assert auth.access_token == "new_access_token"
    
    def test_set_token_and_clear(self):
        """Test set_token stores token and clear() resets state."""
        from brokers.broker.dhan.infrastructure import DhanAuthProvider

        auth = DhanAuthProvider()
        auth.set_token("access_token", client_id="CLIENT123")

        assert auth.access_token == "access_token"
        assert auth.client_id == "CLIENT123"

        auth.clear()

        assert auth.access_token is None
        assert auth.client_id is None


class TestDhanHttpClientAuthRefresh:
    """Tests for DhanHttpClient auto token refresh functionality."""
    
    @pytest.fixture
    def mock_auth_provider(self):
        """Create a mock auth provider."""
        auth = AsyncMock(spec=DhanAuthProvider)
        auth.access_token = "test_token"
        auth.needs_refresh = False
        auth.ensure_valid_token = AsyncMock(return_value="test_token")
        auth.handle_auth_error = AsyncMock(return_value=True)
        return auth
    
    @pytest.mark.asyncio
    async def test_proactive_token_refresh(self, mock_auth_provider):
        """Test proactive token refresh before request."""
        from brokers.broker.dhan.infrastructure import DhanHttpClient
        
        # Setup auth provider to indicate refresh needed
        mock_auth_provider.needs_refresh = True
        mock_auth_provider.ensure_valid_token = AsyncMock(return_value="new_token")
        
        client = DhanHttpClient(
            base_url="https://api.dhan.co",
            access_token="old_token",
            auth_provider=mock_auth_provider,
        )
        
        # Mock the _execute_with_retry method to avoid actual HTTP calls
        with patch.object(client, '_execute_with_retry') as mock_execute:
            mock_execute.return_value = HttpResponse(
                status_code=200,
                data={"data": "test"},
                headers={},
            )
            
            response = await client.get("/test")
            
            assert response.status_code == 200
            mock_auth_provider.ensure_valid_token.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_auto_refresh_on_401(self, mock_auth_provider):
        """Test auto token refresh on 401 error."""
        from brokers.broker.dhan.infrastructure import DhanHttpClient
        
        mock_auth_provider.access_token = "refreshed_token"
        
        client = DhanHttpClient(
            base_url="https://api.dhan.co",
            access_token="old_token",
            auth_provider=mock_auth_provider,
        )
        
        # Mock _execute_request to raise 401 on first call, succeed on second
        call_count = 0
        
        async def mock_execute_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            if call_count == 1:
                raise DhanTokenInvalidError(
                    message="Invalid token",
                    code="DH-1001",
                    details={},
                )
            else:
                return HttpResponse(
                    status_code=200,
                    data={"data": "test"},
                    headers={},
                )
        
        with patch.object(client, '_execute_request', side_effect=mock_execute_request):
            response = await client.get("/test")
            
            assert response.status_code == 200
            mock_auth_provider.handle_auth_error.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_no_refresh_without_auth_provider(self):
        """Test that no refresh happens without auth provider."""
        from brokers.broker.dhan.infrastructure import DhanHttpClient
        
        client = DhanHttpClient(
            base_url="https://api.dhan.co",
            access_token="test_token",
            auth_provider=None,  # No auth provider
        )
        
        # Mock _execute_request to raise 401
        with patch.object(client, '_execute_request') as mock_execute:
            mock_execute.side_effect = DhanTokenInvalidError(
                message="Invalid token",
                code="DH-1001",
                details={},
            )
            
            with pytest.raises(DhanTokenInvalidError):
                await client.get("/test")
    
    def test_set_access_token(self):
        """Test set_access_token method."""
        from brokers.broker.dhan.infrastructure import DhanHttpClient
        
        client = DhanHttpClient(
            base_url="https://api.dhan.co",
            access_token="old_token",
        )
        
        client.set_access_token("new_token")
        
        assert client.access_token == "new_token"


# =============================================================================
# Tests for Protocol Compliance
# =============================================================================

class TestProtocolCompliance:
    """Tests for protocol compliance of infrastructure implementations."""
    
    def test_http_client_protocol_compliance(self, dhan_http_client):
        """Test DhanHttpClient implements IHttpClient protocol."""
        # Check required methods exist
        assert hasattr(dhan_http_client, 'get')
        assert hasattr(dhan_http_client, 'post')
        assert hasattr(dhan_http_client, 'request')
        assert hasattr(dhan_http_client, 'close')
        
        # Check methods are async
        import asyncio
        assert asyncio.iscoroutinefunction(dhan_http_client.get)
        assert asyncio.iscoroutinefunction(dhan_http_client.post)
        assert asyncio.iscoroutinefunction(dhan_http_client.request)
        assert asyncio.iscoroutinefunction(dhan_http_client.close)
    
    def test_websocket_client_protocol_compliance(self, dhan_ws_client):
        """Test DhanWebSocketClient implements IWebSocketClient protocol."""
        # Check required methods exist
        assert hasattr(dhan_ws_client, 'connect')
        assert hasattr(dhan_ws_client, 'disconnect')
        assert hasattr(dhan_ws_client, 'subscribe')
        assert hasattr(dhan_ws_client, 'unsubscribe')
        assert hasattr(dhan_ws_client, 'messages')
        
        # Check methods are async
        import asyncio
        assert asyncio.iscoroutinefunction(dhan_ws_client.connect)
        assert asyncio.iscoroutinefunction(dhan_ws_client.disconnect)
        assert asyncio.iscoroutinefunction(dhan_ws_client.subscribe)
        assert asyncio.iscoroutinefunction(dhan_ws_client.unsubscribe)
    
    def test_rate_limiter_protocol_compliance(self, rate_limiter):
        """Test TokenBucketRateLimiter implements IRateLimiter protocol."""
        # Check required methods exist
        assert hasattr(rate_limiter, 'acquire')
        
        # Check methods are async
        import asyncio
        assert asyncio.iscoroutinefunction(rate_limiter.acquire)
    
    def test_circuit_breaker_protocol_compliance(self, circuit_breaker):
        """Test DhanCircuitBreaker implements ICircuitBreaker protocol."""
        # Check required methods exist
        assert hasattr(circuit_breaker, 'execute')
        assert hasattr(circuit_breaker, 'state')
        
        # Check methods are async
        import asyncio
        assert asyncio.iscoroutinefunction(circuit_breaker.execute)


# =============================================================================
# Tests for HttpRequest and HttpResponse
# =============================================================================

class TestHttpRequestResponse:
    """Tests for HttpRequest and HttpResponse data classes."""
    
    def test_create_http_request(self):
        """Test creating HttpRequest (endpoint from api_contracts)."""
        request = HttpRequest(
            method="GET",
            endpoint=ORDERS,
            params={"status": "open"},
        )
        
        assert request.method == "GET"
        assert request.endpoint == ORDERS
        assert request.params == {"status": "open"}
        assert request.json is None
        assert request.headers is None
    
    def test_create_http_request_with_body(self):
        """Test creating HttpRequest with JSON body (endpoint from api_contracts)."""
        request = HttpRequest(
            method="POST",
            endpoint=ORDERS,
            json={"symbol": "NIFTY", "quantity": 50},
        )
        
        assert request.method == "POST"
        assert request.json == {"symbol": "NIFTY", "quantity": 50}
    
    def test_http_request_is_frozen(self):
        """Test that HttpRequest is immutable."""
        request = HttpRequest(method="GET", endpoint="/test")
        
        with pytest.raises(Exception):  # FrozenInstanceError
            request.method = "POST"
    
    def test_create_http_response(self):
        """Test creating HttpResponse."""
        response = HttpResponse(
            status_code=200,
            data={"orderId": "12345"},
            headers={"content-type": "application/json"},
        )
        
        assert response.status_code == 200
        assert response.data == {"orderId": "12345"}
        assert response.headers == {"content-type": "application/json"}
    
    def test_http_response_is_frozen(self):
        """Test that HttpResponse is immutable."""
        response = HttpResponse(
            status_code=200,
            data={},
            headers={},
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            response.status_code = 404


class TestWSMessage:
    """Tests for WSMessage data class."""
    
    def test_create_ws_message(self):
        """Test creating WSMessage."""
        message = WSMessage(
            type="tick",
            data={"LTP": 18050.50},
            timestamp=datetime.now(),
        )
        
        assert message.type == "tick"
        assert message.data == {"LTP": 18050.50}
        assert isinstance(message.timestamp, datetime)
    
    def test_ws_message_is_frozen(self):
        """Test that WSMessage is immutable."""
        message = WSMessage(
            type="tick",
            data={},
            timestamp=datetime.now(),
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            message.type = "quote"


# =============================================================================
# Tests for Historical Data Rate Limits
# =============================================================================

class TestHistoricalDataRateLimits:
    """Tests for historical data rate limiting and validation."""
    
    @pytest.fixture
    def mock_rate_limiter(self):
        """Create a mock rate limiter."""
        limiter = AsyncMock(spec=IRateLimiter)
        limiter.acquire = AsyncMock()
        return limiter
    
    @pytest.fixture
    def mock_http_for_historical(self):
        """Create a mock HTTP client for historical data (v2 POST /charts/historical response shape)."""
        client = AsyncMock(spec=IHttpClient)
        client.post = AsyncMock(return_value=HttpResponse(
            status_code=200,
            data={"open": [], "high": [], "low": [], "close": [], "volume": [], "timestamp": []},
            headers={},
        ))
        return client
    
    def test_historical_max_days_constant(self):
        """Test that HISTORICAL_MAX_DAYS is set to 90."""
        from brokers.broker.dhan.domain import HISTORICAL_MAX_DAYS
        
        assert HISTORICAL_MAX_DAYS == 90
    
    def test_rate_limit_historical_is_10(self):
        """Test that RATE_LIMIT_HISTORICAL is set to 10 req/sec."""
        from brokers.broker.dhan.domain import RATE_LIMIT_HISTORICAL
        
        assert RATE_LIMIT_HISTORICAL == 10
    
    @pytest.mark.asyncio
    async def test_historical_rate_limit_category_exists(self):
        """Test that 'historical' rate limit category is configured."""
        from brokers.broker.dhan.infrastructure import TokenBucketRateLimiter, DEFAULT_RATE_LIMITS
        
        # Check that 'historical' category exists in default rate limits
        assert "historical" in DEFAULT_RATE_LIMITS
        
        # Create rate limiter and verify historical category
        limiter = TokenBucketRateLimiter()
        
        # Should be able to acquire for historical category
        await limiter.acquire("historical")
        
        # Verify tokens were consumed
        tokens = limiter.get_tokens("historical")
        assert tokens < 10  # Default burst for historical
    
    @pytest.mark.asyncio
    async def test_historical_date_range_exceeds_90_days_auto_batches(
        self, mock_rate_limiter, mock_http_for_historical
    ):
        """Test that requesting more than 90 days auto-batches and returns merged DataFrame."""
        from brokers.broker.dhan.application import DhanBroker, DhanConfig
        from datetime import timedelta
        
        # Create broker with mocks
        config = DhanConfig(
            client_id="CLIENT123",
            access_token="test_token",
        )
        
        broker = DhanBroker(
            config=config,
            http_client=mock_http_for_historical,
            rate_limiter=mock_rate_limiter,
        )
        broker._initialized = True
        
        # Create instrument
        instrument = Instrument(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            security_id="12345",
        )
        
        # Request 91 days of data (should trigger 2 batches: 90 + 1)
        from_date = datetime(2024, 1, 1)
        to_date = from_date + timedelta(days=91)
        
        # Should succeed with auto-batching (no raise)
        result = await broker._get_historical_async(
            instrument, from_date, to_date, "1d"
        )
        
        assert result is not None
        import pandas as pd
        assert isinstance(result, pd.DataFrame)
        # Should have called HTTP POST for each batch (2 batches for 91 days)
        assert mock_http_for_historical.post.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_historical_date_range_exactly_90_days_succeeds(
        self, mock_rate_limiter, mock_http_for_historical
    ):
        """Test that requesting exactly 90 days succeeds."""
        from brokers.broker.dhan.application import DhanBroker, DhanConfig
        from datetime import timedelta
        
        # Create broker with mocks
        config = DhanConfig(
            client_id="CLIENT123",
            access_token="test_token",
        )
        
        broker = DhanBroker(
            config=config,
            http_client=mock_http_for_historical,
            rate_limiter=mock_rate_limiter,
        )
        broker._initialized = True
        
        # Create instrument
        instrument = Instrument(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            security_id="12345",
        )
        
        # Request exactly 90 days of data
        from_date = datetime(2024, 1, 1)
        to_date = from_date + timedelta(days=90)
        
        # Should succeed
        result = await broker._get_historical_async(instrument, from_date, to_date, "1d")
        
        # Verify rate limiter was called with 'historical' category
        mock_rate_limiter.acquire.assert_called_once_with("historical")
    
    @pytest.mark.asyncio
    async def test_historical_invalid_date_range_from_after_to(
        self, mock_rate_limiter, mock_http_for_historical
    ):
        """Test that from_date after to_date raises error."""
        from brokers.broker.dhan.application import DhanBroker, DhanConfig
        from brokers.broker.dhan.domain import DhanHistoricalDataError
        
        # Create broker with mocks
        config = DhanConfig(
            client_id="CLIENT123",
            access_token="test_token",
        )
        
        broker = DhanBroker(
            config=config,
            http_client=mock_http_for_historical,
            rate_limiter=mock_rate_limiter,
        )
        broker._initialized = True
        
        # Create instrument
        instrument = Instrument(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            security_id="12345",
        )
        
        # Invalid date range: from_date after to_date
        from_date = datetime(2024, 2, 1)
        to_date = datetime(2024, 1, 1)
        
        # Should raise DhanHistoricalDataError
        with pytest.raises(DhanHistoricalDataError) as exc_info:
            await broker._get_historical_async(instrument, from_date, to_date, "1d")
        
        # Verify error code
        error = exc_info.value
        assert error.code == "INVALID_DATE_RANGE"
        
        # Verify rate limiter was NOT called
        mock_rate_limiter.acquire.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_historical_rate_limiter_applied_for_valid_request(
        self, mock_rate_limiter, mock_http_for_historical
    ):
        """Test that rate limiter is applied for valid historical data requests."""
        from brokers.broker.dhan.application import DhanBroker, DhanConfig
        from datetime import timedelta
        
        # Create broker with mocks
        config = DhanConfig(
            client_id="CLIENT123",
            access_token="test_token",
        )
        
        broker = DhanBroker(
            config=config,
            http_client=mock_http_for_historical,
            rate_limiter=mock_rate_limiter,
        )
        broker._initialized = True
        
        # Create instrument
        instrument = Instrument(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            security_id="12345",
        )
        
        # Valid date range
        from_date = datetime(2024, 1, 1)
        to_date = datetime(2024, 1, 31)
        
        # Make request
        await broker._get_historical_async(instrument, from_date, to_date, "1d")
        
        # Verify rate limiter was called with 'historical' category
        mock_rate_limiter.acquire.assert_called_once_with("historical")


class TestHistoricalDataRateLimiterIntegration:
    """Integration tests for historical data rate limiting."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_historical_config(self):
        """Test that historical rate limiter is properly configured."""
        from brokers.broker.dhan.infrastructure import (
            TokenBucketRateLimiter,
            DEFAULT_RATE_LIMITS,
        )
        from brokers.broker.dhan.domain import (
            RATE_LIMIT_HISTORICAL,
            RATE_BURST_HISTORICAL,
        )
        
        # Verify default rate limits
        assert "historical" in DEFAULT_RATE_LIMITS
        historical_config = DEFAULT_RATE_LIMITS["historical"]
        
        # Verify rate is 10 req/sec
        assert historical_config.rate == RATE_LIMIT_HISTORICAL
        assert historical_config.rate == 10
        
        # Verify burst limit
        assert historical_config.burst == RATE_BURST_HISTORICAL
    
    @pytest.mark.asyncio
    async def test_rate_limiter_enforces_historical_limit(self):
        """Test that rate limiter enforces 10 req/sec for historical data."""
        from brokers.broker.dhan.infrastructure import TokenBucketRateLimiter
        import time
        
        # Create rate limiter
        limiter = TokenBucketRateLimiter()
        
        # Record start time
        start_time = time.monotonic()
        
        # Make 15 requests (more than burst capacity of 10)
        for _ in range(15):
            await limiter.acquire("historical")
        
        elapsed = time.monotonic() - start_time
        
        # Should have taken at least 0.5 seconds (5 extra requests / 10 req/sec)
        # due to rate limiting after burst is exhausted
        assert elapsed >= 0.4  # Allow some tolerance
    
    @pytest.mark.asyncio
    async def test_rate_limiter_categories_are_independent(self):
        """Test that rate limit categories are independent."""
        from brokers.broker.dhan.infrastructure import TokenBucketRateLimiter
        
        limiter = TokenBucketRateLimiter()
        
        # Consume tokens from 'historical' category
        await limiter.acquire("historical")
        historical_tokens = limiter.get_tokens("historical")
        
        # 'market_data' category should still have full tokens
        market_data_tokens = limiter.get_tokens("market_data")
        
        # They should be different (historical consumed, market_data not)
        assert historical_tokens < market_data_tokens
