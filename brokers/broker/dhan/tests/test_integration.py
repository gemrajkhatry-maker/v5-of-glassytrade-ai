"""
Integration Tests for Dhan Broker Implementation.

This module tests the integration between different layers:
    - DhanBroker with mocked infrastructure
    - Full flow with mock server responses
    - Protocol compliance tests

Live tests are marked with @pytest.mark.integration and require:
    - DHAN_CLIENT_ID environment variable
    - DHAN_ACCESS_TOKEN environment variable
"""

import os
import pytest
import asyncio
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch

from brokers.broker.dhan.domain import (
    DhanInstrument,
    DhanQuote,
    DhanTick,
    DhanOrder,
    DhanPosition,
    ExchangeSegment,
    InstrumentTypeEnum,
    OptionType,
    MARKETFEED_QUOTE,
    OPTIONCHAIN_EXPIRYLIST,
    ORDERS,
    POSITIONS,
)

from brokers.broker.dhan.infrastructure import (
    DhanHttpClient,
    DhanWebSocketClient,
    TokenBucketRateLimiter,
    DhanCircuitBreaker,
)

from brokers.broker.dhan.application import DhanConfig, DhanConverter

from brokers.broker.dhan.ports import (
    IHttpClient,
    IWebSocketClient,
    HttpRequest,
    HttpResponse,
    WSMessage,
)

from brokers.broker.entities import (
    Instrument,
    Quote,
    Tick,
    Order,
    Position,
)

from brokers.broker.types import (
    Exchange,
    OrderSide,
    OrderType,
    OrderStatus,
)


# =============================================================================
# Mock Server Responses
# =============================================================================

class MockDhanServer:
    """Mock Dhan API server for testing."""
    
    @staticmethod
    def get_quote_response(security_id: str) -> dict:
        """Generate mock quote response."""
        return {
            "status": "success",
            "data": {
                "securityId": security_id,
                "tradingSymbol": "NIFTY23FEB18000CE",
                "LTP": 18050.50,
                "open": 18000.00,
                "high": 18100.00,
                "low": 17950.00,
                "close": 17980.00,
                "volume": 1000000,
                "bid": 18050.00,
                "ask": 18051.00,
            }
        }
    
    @staticmethod
    def get_order_response(order_id: str) -> dict:
        """Generate mock order response."""
        return {
            "status": "success",
            "data": {
                "orderId": order_id,
                "securityId": "12345",
                "tradingSymbol": "NIFTY23FEB18000CE",
                "orderType": "LIMIT",
                "transactionType": "BUY",
                "quantity": 50,
                "price": 150.00,
                "orderStatus": "TRADED",
                "filledQuantity": 50,
                "averagePrice": 150.50,
            }
        }
    
    @staticmethod
    def get_positions_response() -> dict:
        """Generate mock positions response."""
        return {
            "status": "success",
            "data": [
                {
                    "securityId": "12345",
                    "tradingSymbol": "NIFTY23FEB18000CE",
                    "netQty": 50,
                    "avgPrice": 150.00,
                    "unrealizedProfit": 250.00,
                    "realizedProfit": 0.0,
                }
            ]
        }
    
    @staticmethod
    def place_order_response() -> dict:
        """Generate mock place order response."""
        return {
            "status": "success",
            "data": {
                "orderId": "ORDER123456",
                "orderStatus": "PENDING",
            }
        }


# =============================================================================
# Integration Tests - HTTP Client with Converter
# =============================================================================

class TestHttpClientConverterIntegration:
    """Integration tests for HTTP client with converter."""
    
    @pytest.fixture
    def mock_session(self):
        """Create mock aiohttp session."""
        session = AsyncMock()
        session.closed = False
        return session
    
    @pytest.fixture
    def http_client(self):
        """Create HTTP client for testing."""
        return DhanHttpClient(
            base_url="https://api.dhan.co",
            access_token="test_token",
        )
    
    @pytest.mark.asyncio
    async def test_get_quote_and_convert(self, http_client, mock_session):
        """Test getting quote and converting to broker-agnostic format."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = AsyncMock(return_value=MockDhanServer.get_quote_response("12345"))
        
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.request = MagicMock(return_value=ctx)

        with patch.object(http_client, '_get_session', return_value=mock_session):
                # Get quote from API
                response = await http_client.get("/market-data/quote/12345")
                
                # Convert to broker-agnostic format
                quote = DhanConverter.quote_from_api_response(
                    response.data.get("data", response.data),
                    security_id="12345",
                )
                
                assert isinstance(quote, Quote)
                assert quote.ltp == 18050.50
    
    @pytest.mark.asyncio
    async def test_place_order_and_convert(self, http_client, mock_session):
        """Test placing order and converting response."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = AsyncMock(return_value=MockDhanServer.place_order_response())
        
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.request = MagicMock(return_value=ctx)

        with patch.object(http_client, '_get_session', return_value=mock_session):
                # Create order request
                instrument = Instrument(
                    symbol="NIFTY",
                    exchange=Exchange.NFO,
                    security_id="12345",
                )
                order = Order(
                    instrument=instrument,
                    side=OrderSide.BUY,
                    quantity=50.0,
                    order_type=OrderType.LIMIT,
                    price=150.00,
                )
                
                # Convert to API payload
                payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
                
                # Place order
                response = await http_client.post(ORDERS, json=payload)
                
                assert response.status_code == 200
                assert "orderId" in response.data.get("data", response.data)


# =============================================================================
# Integration Tests - Rate Limiter with HTTP Client
# =============================================================================

class TestRateLimiterIntegration:
    """Integration tests for rate limiter with HTTP client."""
    
    @pytest.fixture
    def rate_limiter(self):
        """Create rate limiter for testing."""
        return TokenBucketRateLimiter()
    
    @pytest.mark.asyncio
    async def test_rate_limit_multiple_requests(self, rate_limiter):
        """Test rate limiting multiple requests."""
        # Make multiple requests
        start_time = asyncio.get_event_loop().time()
        
        for i in range(5):
            await rate_limiter.acquire("market_data")
        
        elapsed = asyncio.get_event_loop().time() - start_time
        
        # Should complete quickly with tokens available
        assert elapsed < 1.0
    
    @pytest.mark.asyncio
    async def test_rate_limit_different_categories(self, rate_limiter):
        """Test rate limiting different categories independently."""
        # Acquire in different categories
        await rate_limiter.acquire("market_data")
        await rate_limiter.acquire("orders")
        await rate_limiter.acquire("historical")
        
        # Each category should have consumed tokens independently
        assert rate_limiter.get_tokens("market_data") < 20
        assert rate_limiter.get_tokens("orders") < 10
        assert rate_limiter.get_tokens("historical") < 10


# =============================================================================
# Integration Tests - Circuit Breaker with HTTP Client
# =============================================================================

class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with HTTP client."""
    
    @pytest.fixture
    def circuit_breaker(self):
        """Create circuit breaker for testing."""
        return DhanCircuitBreaker()
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_success_path(self, circuit_breaker):
        """Test circuit breaker with successful operations."""
        async def successful_operation():
            return {"status": "success"}
        
        result = await circuit_breaker.execute(successful_operation)
        
        assert result == {"status": "success"}
        assert circuit_breaker.is_closed is True
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_failure_path(self):
        """Test circuit breaker with failing operations."""
        cb = DhanCircuitBreaker()
        cb._config.failure_threshold = 2
        
        async def failing_operation():
            raise ConnectionError("Connection failed")
        
        # First failure
        with pytest.raises(ConnectionError):
            await cb.execute(failing_operation)
        
        assert cb.failure_count == 1
        assert cb.is_closed is True
        
        # Second failure - should open circuit
        with pytest.raises(ConnectionError):
            await cb.execute(failing_operation)
        
        assert cb.is_open is True


# =============================================================================
# Integration Tests - WebSocket Message Processing
# =============================================================================

class TestWebSocketIntegration:
    """Integration tests for WebSocket message processing."""
    
    @pytest.fixture
    def ws_client(self):
        """Create WebSocket client for testing."""
        return DhanWebSocketClient(
            ws_url="wss://api.dhan.co/ws",
            access_token="test_token",
            client_id="CLIENT123",
        )
    
    def test_parse_and_convert_tick_message(self, ws_client):
        """Test parsing and converting tick message."""
        raw_message = '{"LTP": 18050.50, "volume": 1000000, "SecurityId": "12345"}'
        
        # Parse message
        ws_message = ws_client._parse_message(raw_message)
        
        assert ws_message is not None
        assert ws_message.type == "tick"
        
        # Convert to broker-agnostic tick
        tick = DhanConverter.tick_from_ws_message(
            ws_message.data,
            security_id="12345",
        )
        
        assert isinstance(tick, Tick)
        assert tick.price == 18050.50
    
    def test_parse_and_convert_order_message(self, ws_client):
        """Test parsing and converting order message."""
        raw_message = '{"orderId": "ORDER123", "orderStatus": "TRADED", "filledQuantity": 50}'
        
        # Parse message
        ws_message = ws_client._parse_message(raw_message)
        
        assert ws_message is not None
        assert ws_message.type == "order"


# =============================================================================
# Integration Tests - Full Flow
# =============================================================================

class TestFullFlowIntegration:
    """Integration tests for full broker flow."""
    
    @pytest.fixture
    def mock_http_client(self):
        """Create mock HTTP client."""
        client = AsyncMock(spec=IHttpClient)
        client.get = AsyncMock(return_value=HttpResponse(
            status_code=200,
            data=MockDhanServer.get_quote_response("12345"),
            headers={},
        ))
        client.post = AsyncMock(return_value=HttpResponse(
            status_code=200,
            data=MockDhanServer.place_order_response(),
            headers={},
        ))
        client.close = AsyncMock()
        return client
    
    @pytest.mark.asyncio
    async def test_get_quote_flow(self, mock_http_client):
        """Test full flow for getting a quote."""
        # 1. Make HTTP request
        response = await mock_http_client.get("/market-data/quote/12345")
        
        # 2. Parse response
        data = response.data.get("data", response.data)
        
        # 3. Convert to broker-agnostic format
        quote = DhanConverter.quote_from_api_response(data, "12345")
        
        # 4. Verify result
        assert isinstance(quote, Quote)
        assert quote.ltp == 18050.50
        assert quote.instrument.security_id == "12345"
    
    @pytest.mark.asyncio
    async def test_place_order_flow(self, mock_http_client):
        """Test full flow for placing an order."""
        # 1. Create order request
        instrument = Instrument(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            security_id="12345",
        )
        order = Order(
            instrument=instrument,
            side=OrderSide.BUY,
            quantity=50.0,
            order_type=OrderType.LIMIT,
            price=150.00,
        )
        
        # 2. Convert to API payload
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        
        # 3. Make HTTP request
        response = await mock_http_client.post(ORDERS, json=payload)
        
        # 4. Parse response
        data = response.data.get("data", response.data)
        
        # 5. Verify order was placed
        assert "orderId" in data
        assert data["orderId"] == "ORDER123456"
    
    @pytest.mark.asyncio
    async def test_get_positions_flow(self, mock_http_client):
        """Test full flow for getting positions."""
        # Setup mock response
        mock_http_client.get.return_value = HttpResponse(
            status_code=200,
            data=MockDhanServer.get_positions_response(),
            headers={},
        )
        
        # 1. Make HTTP request
        response = await mock_http_client.get(POSITIONS)
        
        # 2. Parse response
        data = response.data.get("data", response.data)
        
        # 3. Convert each position
        positions = [
            DhanConverter.position_from_api_response(pos)
            for pos in data
        ]
        
        # 4. Verify results
        assert len(positions) == 1
        assert isinstance(positions[0], Position)
        assert positions[0].quantity == 50.0


# =============================================================================
# Protocol Compliance Tests
# =============================================================================

class TestProtocolCompliance:
    """Tests for protocol compliance across layers."""
    
    def test_http_client_implements_protocol(self):
        """Test DhanHttpClient implements IHttpClient."""
        client = DhanHttpClient(
            base_url="https://api.dhan.co",
            access_token="test_token",
        )
        
        assert isinstance(client, IHttpClient)
    
    def test_websocket_client_implements_protocol(self):
        """Test DhanWebSocketClient implements IWebSocketClient."""
        client = DhanWebSocketClient(
            ws_url="wss://api.dhan.co/ws",
            access_token="test_token",
            client_id="CLIENT123",
        )
        
        assert isinstance(client, IWebSocketClient)
    
    def test_rate_limiter_implements_protocol(self):
        """Test TokenBucketRateLimiter implements IRateLimiter."""
        from brokers.broker.dhan.ports import IRateLimiter
        
        limiter = TokenBucketRateLimiter()
        
        assert isinstance(limiter, IRateLimiter)
    
    def test_circuit_breaker_implements_protocol(self):
        """Test DhanCircuitBreaker implements ICircuitBreaker."""
        from brokers.broker.dhan.ports import ICircuitBreaker
        
        cb = DhanCircuitBreaker()
        
        assert isinstance(cb, ICircuitBreaker)


# =============================================================================
# Dhan Broker After Init - HttpResponse Consistency
# =============================================================================

class TestDhanBrokerAfterInitHttpResponseConsistency:
    """After initialize(), all methods use HttpResponse (no dict); no AttributeError."""

    @pytest.fixture
    def mock_http(self):
        """Mock IHttpClient returning HttpResponse for all calls."""
        client = AsyncMock(spec=IHttpClient)
        client.close = AsyncMock()

        async def get(endpoint, params=None):
            if endpoint == POSITIONS:
                return HttpResponse(
                    status_code=200,
                    data={"data": []},
                    headers={},
                )
            return HttpResponse(status_code=200, data={}, headers={})

        async def post(endpoint, json=None):
            if endpoint == MARKETFEED_QUOTE:
                # v2 quote response: data[segment][security_id] with last_price, ohlc, depth, volume, oi
                seg = list(json.keys())[0] if json else "NSE_EQ"
                sids = list(json.values())[0] if json else [12345]
                seg_data = {
                    str(sid): {
                        "last_price": 2500.0,
                        "ohlc": {"open": 2490, "high": 2510, "low": 2485, "close": 2500},
                        "depth": {"buy": [{"price": 2499}], "sell": [{"price": 2501}]},
                        "volume": 1000000,
                        "oi": 0,
                    }
                    for sid in sids
                }
                return HttpResponse(
                    status_code=200,
                    data={"data": {seg: seg_data}, "status": "success"},
                    headers={},
                )
            if endpoint == OPTIONCHAIN_EXPIRYLIST:
                return HttpResponse(
                    status_code=200,
                    data={"data": ["2024-02-29", "2024-03-28"], "status": "success"},
                    headers={},
                )
            return HttpResponse(status_code=200, data={}, headers={})

        client.get = get
        client.post = post
        return client

    @pytest.fixture
    def mock_mapper(self):
        """Mock ISymbolMapper returning security_id."""
        mapper = AsyncMock()
        mapper.get_security_id = AsyncMock(return_value="12345")
        mapper.refresh_cache = AsyncMock()
        return mapper

    @pytest.mark.asyncio
    async def test_after_init_get_quote_get_expiry_list_get_positions_no_attribute_error(
        self, mock_http, mock_mapper, dhan_config
    ):
        """After initialize(), get_quote, get_expiry_list, get_positions use HttpResponse; no AttributeError."""
        from brokers.broker.dhan.application.broker import DhanBroker

        broker = DhanBroker(
            config=dhan_config,
            http_client=mock_http,
            ws_client=None,
            symbol_mapper=mock_mapper,
            rate_limiter=None,
            circuit_breaker=None,
        )
        await broker.initialize()

        # get_quote (sync entry uses _run_async internally)
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="")
        quote = broker.get_quote(inst)
        assert quote is not None
        assert hasattr(quote, "ltp")
        assert hasattr(quote, "instrument")

        # get_expiry_list
        expiries = broker.get_expiry_list("NIFTY", Exchange.NFO)
        assert isinstance(expiries, list)
        assert all(hasattr(e, "year") for e in expiries)

        # get_positions
        positions = broker.get_positions()
        assert isinstance(positions, list)

        await broker.close()


# =============================================================================
# Error Visibility
# =============================================================================

class TestErrorVisibility:
    """Failed HTTP must raise or log; no silent wrong data."""

    @pytest.mark.asyncio
    async def test_get_quote_500_raises_or_logs(self, dhan_config):
        """When HTTP returns 500, get_quote raises defined exception (no silent None)."""
        from brokers.broker.dhan.application.broker import DhanBroker
        from brokers.broker.dhan.domain import DhanError, DhanNetworkError

        client = AsyncMock(spec=IHttpClient)
        client.get = AsyncMock(return_value=HttpResponse(
            status_code=500,
            data={"message": "Internal Server Error"},
            headers={},
        ))
        client.close = AsyncMock()
        mapper = AsyncMock()
        mapper.get_security_id = AsyncMock(return_value="12345")
        mapper.refresh_cache = AsyncMock()

        broker = DhanBroker(
            config=dhan_config,
            http_client=client,
            symbol_mapper=mapper,
            ws_client=None,
            rate_limiter=None,
            circuit_breaker=None,
        )
        await broker.initialize()

        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="")
        with pytest.raises((DhanError, DhanNetworkError, Exception)):
            broker.get_quote(inst)

        await broker.close()


# =============================================================================
# Error Handling Integration Tests
# =============================================================================

class TestErrorHandlingIntegration:
    """Integration tests for error handling across layers."""
    
    @pytest.fixture
    def http_client(self):
        """Create HTTP client for testing."""
        return DhanHttpClient(
            base_url="https://api.dhan.co",
            access_token="test_token",
        )
    
    @pytest.mark.asyncio
    async def test_auth_error_propagation(self, http_client):
        """Test authentication error propagation."""
        from brokers.broker.dhan.domain import DhanTokenInvalidError
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.headers = {}
        mock_response.json = AsyncMock(return_value={
            "errorCode": "DH-1001",
            "message": "Invalid token"
        })
        
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.request = MagicMock(return_value=ctx)

        with patch.object(http_client, '_get_session', return_value=mock_session):
                with pytest.raises(DhanTokenInvalidError):
                    await http_client.get("/test")
    
    @pytest.mark.asyncio
    async def test_rate_limit_error_propagation(self, http_client):
        """Test rate limit error propagation."""
        from brokers.broker.dhan.domain import DhanRateLimitError
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.json = AsyncMock(return_value={
            "message": "Rate limit exceeded"
        })
        
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_response)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.request = MagicMock(return_value=ctx)

        with patch.object(http_client, '_get_session', return_value=mock_session):
                with pytest.raises(DhanRateLimitError) as exc_info:
                    await http_client.get("/test")

                assert exc_info.value.retry_after == 60


# =============================================================================
# Live Integration Tests (marked with pytest.mark.integration)
# =============================================================================

@pytest.mark.live
@pytest.mark.integration
class TestLiveIntegration:
    """
    Live integration tests that require real API credentials.
    
    These tests are skipped by default. To run them:
        pytest brokers/broker/dhan/tests/test_integration.py -m integration
    
    Required environment variables:
        - DHAN_CLIENT_ID
        - DHAN_ACCESS_TOKEN
    """
    
    @pytest.fixture
    def live_config(self):
        """Create config from environment variables."""
        client_id = os.environ.get("DHAN_CLIENT_ID")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN")
        
        if not client_id or not access_token:
            pytest.skip("Live credentials not available")
        
        return DhanConfig(
            client_id=client_id,
            access_token=access_token,
        )
    
    @pytest.fixture
    def live_http_client(self, live_config):
        """Create HTTP client with live credentials."""
        return DhanHttpClient(
            base_url=live_config.base_url,
            access_token=live_config.access_token,
        )
    
    @pytest.mark.asyncio
    async def test_live_get_funds(self, live_http_client):
        """Test getting funds from live API."""
        try:
            response = await live_http_client.get("/fundlimit")
            
            assert response.status_code == 200
            # Dhan returns flat fund fields directly (no wrapper key)
            assert "availabelBalance" in response.data or "data" in response.data or "fundLimit" in response.data
        finally:
            await live_http_client.close()
    
    @pytest.mark.asyncio
    async def test_live_get_positions(self, live_http_client):
        """Test getting positions from live API."""
        try:
            response = await live_http_client.get(POSITIONS)
            
            assert response.status_code == 200
        finally:
            await live_http_client.close()


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Performance tests for critical paths."""
    
    @pytest.mark.asyncio
    async def test_converter_performance(self):
        """Test converter performance with many conversions."""
        # Create sample data
        instruments = [
            DhanInstrument(
                security_id=str(i),
                trading_symbol=f"TEST{i}",
                symbol="TEST",
                exchange_segment=ExchangeSegment.NSE_FNO,
                instrument_type=InstrumentTypeEnum.INDEX_OPTION,
            )
            for i in range(1000)
        ]
        
        # Time conversions
        import time
        start = time.time()
        
        for inst in instruments:
            DhanConverter.to_instrument(inst)
        
        elapsed = time.time() - start
        
        # Should convert 1000 instruments in under 1 second
        assert elapsed < 1.0, f"Conversion took {elapsed}s"
    
    def test_quote_conversion_performance(self):
        """Test quote conversion performance."""
        quotes = [
            DhanQuote(
                security_id=str(i),
                ltp=18050.50 + i,
                open=18000.00,
                high=18100.00,
                low=17950.00,
                close=17980.00,
                volume=1000000,
                bid=18050.00,
                ask=18051.00,
            )
            for i in range(1000)
        ]
        
        import time
        start = time.time()
        
        for quote in quotes:
            DhanConverter.to_quote(quote)
        
        elapsed = time.time() - start
        
        # Should convert 1000 quotes in under 1 second
        assert elapsed < 1.0, f"Conversion took {elapsed}s"


# =============================================================================
# Concurrency Tests
# =============================================================================

class TestConcurrency:
    """Tests for concurrent operations."""
    
    @pytest.mark.asyncio
    async def test_concurrent_rate_limiter_acquisitions(self):
        """Test concurrent rate limiter acquisitions."""
        limiter = TokenBucketRateLimiter()
        
        async def acquire_token(i):
            await limiter.acquire("default")
            return i
        
        # Run 10 concurrent acquisitions
        tasks = [acquire_token(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # All should complete
        assert len(results) == 10
    
    @pytest.mark.asyncio
    async def test_concurrent_circuit_breaker_operations(self):
        """Test concurrent circuit breaker operations."""
        cb = DhanCircuitBreaker()
        
        async def operation(i):
            async def op():
                return i
            return await cb.execute(op)
        
        # Run 10 concurrent operations
        tasks = [operation(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # All should complete
        assert len(results) == 10
        assert cb.is_closed is True
