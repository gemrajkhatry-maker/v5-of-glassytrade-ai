"""
Pytest fixtures for Dhan broker tests.

This module provides shared fixtures for testing the Dhan broker implementation.
All fixtures are available for use in test files.

Usage:
    def test_something(mock_http_client):
        # Use mock_http_client
        pass
"""

import os
import pytest
from datetime import datetime, date
from typing import Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Domain imports
from brokers.broker.dhan.domain import (
    DhanInstrument,
    DhanQuote,
    DhanTick,
    DhanOption,
    DhanOptionChain,
    DhanOrder,
    DhanPosition,
    ExchangeSegment,
    InstrumentTypeEnum,
    OptionType,
    DepthLevel,
    OHLC,
    Greeks,
)

# Infrastructure imports
from brokers.broker.dhan.infrastructure import (
    DhanHttpClient,
    DhanWebSocketClient,
    DhanSymbolMapper,
    DhanAuthProvider,
    TokenBucketRateLimiter,
    DhanCircuitBreaker,
    RetryConfig,
)

# Application imports
from brokers.broker.dhan.application import DhanConfig, DhanConverter

# Port imports
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

# Broker-agnostic imports
from brokers.broker.entities import Instrument, Quote, Tick, Order, Position
from brokers.broker.types import Exchange, OrderSide, OrderType, OrderStatus


# =============================================================================
# Domain Fixtures
# =============================================================================

@pytest.fixture
def sample_exchange_segment() -> ExchangeSegment:
    """Sample exchange segment for NSE F&O."""
    return ExchangeSegment.NSE_FNO


@pytest.fixture
def sample_instrument() -> DhanInstrument:
    """Sample DhanInstrument for testing."""
    return DhanInstrument(
        security_id="12345",
        trading_symbol="NIFTY23FEB18000CE",
        symbol="NIFTY",
        exchange_segment=ExchangeSegment.NSE_FNO,
        instrument_type=InstrumentTypeEnum.INDEX_OPTION,
        expiry_date=date(2023, 2, 23),
        strike=18000.0,
        option_type=OptionType.CALL,
        lot_size=25,
        tick_size=0.05,
    )


@pytest.fixture
def sample_equity_instrument() -> DhanInstrument:
    """Sample equity DhanInstrument for testing."""
    return DhanInstrument(
        security_id="10001",
        trading_symbol="TCS-EQ",
        symbol="TCS",
        exchange_segment=ExchangeSegment.NSE_EQ,
        instrument_type=InstrumentTypeEnum.EQUITY,
        lot_size=1,
        tick_size=0.05,
        isin="INE467B01029",
    )


@pytest.fixture
def sample_future_instrument() -> DhanInstrument:
    """Sample future DhanInstrument for testing."""
    return DhanInstrument(
        security_id="20001",
        trading_symbol="NIFTY23FEBFUT",
        symbol="NIFTY",
        exchange_segment=ExchangeSegment.NSE_FNO,
        instrument_type=InstrumentTypeEnum.INDEX_FUTURE,
        expiry_date=date(2023, 2, 23),
        lot_size=25,
        tick_size=0.05,
    )


@pytest.fixture
def sample_depth_levels() -> tuple:
    """Sample market depth levels."""
    return (
        DepthLevel(price=18050.00, quantity=500, orders=3),
        DepthLevel(price=18049.50, quantity=1000, orders=5),
        DepthLevel(price=18049.00, quantity=750, orders=4),
    )


@pytest.fixture
def sample_quote(sample_instrument: DhanInstrument, sample_depth_levels: tuple) -> DhanQuote:
    """Sample DhanQuote for testing."""
    return DhanQuote(
        security_id="12345",
        ltp=18050.50,
        open=18000.00,
        high=18100.00,
        low=17950.00,
        close=17980.00,
        volume=1000000,
        bid=18050.00,
        ask=18051.00,
        oi=500000,
        timestamp=datetime.now(),
        bid_depth=sample_depth_levels,
        ask_depth=sample_depth_levels,
        instrument=sample_instrument,
    )


@pytest.fixture
def sample_tick(sample_instrument: DhanInstrument) -> DhanTick:
    """Sample DhanTick for testing."""
    return DhanTick(
        security_id="12345",
        ltp=18050.50,
        volume=1000000,
        timestamp=datetime.now(),
        trade_type="BUY",
        quantity=100,
        instrument=sample_instrument,
    )


@pytest.fixture
def sample_option(sample_instrument: DhanInstrument) -> DhanOption:
    """Sample DhanOption for testing."""
    return DhanOption(
        strike=18000.0,
        option_type="CE",
        ltp=150.50,
        bid=150.00,
        ask=151.00,
        oi=500000,
        volume=10000,
        iv=0.18,
        delta=0.55,
        gamma=0.02,
        theta=-5.5,
        vega=12.5,
        instrument=sample_instrument,
    )


@pytest.fixture
def sample_option_chain(sample_option: DhanOption) -> DhanOptionChain:
    """Sample DhanOptionChain for testing."""
    # Create call and put options for multiple strikes
    strikes = {}
    for strike_price in [17900, 18000, 18100]:
        call = DhanOption(
            strike=strike_price,
            option_type="CE",
            ltp=150.0 + (18000 - strike_price) * 0.5,
            bid=149.0 + (18000 - strike_price) * 0.5,
            ask=151.0 + (18000 - strike_price) * 0.5,
            oi=500000,
            volume=10000,
        )
        put = DhanOption(
            strike=strike_price,
            option_type="PE",
            ltp=150.0 + (strike_price - 18000) * 0.5,
            bid=149.0 + (strike_price - 18000) * 0.5,
            ask=151.0 + (strike_price - 18000) * 0.5,
            oi=400000,
            volume=8000,
        )
        strikes[strike_price] = (call, put)
    
    return DhanOptionChain(
        underlying="NIFTY",
        expiry=date(2023, 2, 23),
        spot_price=18000.0,
        strikes=strikes,
        timestamp=datetime.now(),
        step_size=100.0,
    )


@pytest.fixture
def sample_order() -> DhanOrder:
    """Sample DhanOrder for testing."""
    return DhanOrder(
        order_id="ORDER123",
        security_id="12345",
        trading_symbol="NIFTY23FEB18000CE",
        order_type="LIMIT",
        transaction_type="BUY",
        quantity=50,
        price=150.00,
        trigger_price=0.0,
        status="PENDING",
        filled_quantity=0,
        average_price=0.0,
        product_type="M",
        validity="DAY",
        timestamp=datetime.now(),
        message="",
    )


@pytest.fixture
def sample_filled_order() -> DhanOrder:
    """Sample filled DhanOrder for testing."""
    return DhanOrder(
        order_id="ORDER123",
        security_id="12345",
        trading_symbol="NIFTY23FEB18000CE",
        order_type="LIMIT",
        transaction_type="BUY",
        quantity=50,
        price=150.00,
        trigger_price=0.0,
        status="TRADED",
        filled_quantity=50,
        average_price=150.50,
        product_type="M",
        validity="DAY",
        timestamp=datetime.now(),
        message="Order executed successfully",
    )


@pytest.fixture
def sample_position() -> DhanPosition:
    """Sample DhanPosition for testing."""
    return DhanPosition(
        security_id="12345",
        trading_symbol="NIFTY23FEB18000CE",
        quantity=50,
        average_price=150.00,
        ltp=155.00,
        pnl=250.00,
        pnl_percent=3.33,
        product_type="M",
    )


# =============================================================================
# Infrastructure Fixtures
# =============================================================================

@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession."""
    session = AsyncMock()
    session.closed = False
    return session


@pytest.fixture
def mock_aiohttp_response():
    """Mock aiohttp response."""
    response = AsyncMock()
    response.status = 200
    response.headers = {"content-type": "application/json"}
    response.json = AsyncMock(return_value={"status": "success"})
    response.text = AsyncMock(return_value="")
    return response


@pytest.fixture
def http_client_config() -> Dict[str, Any]:
    """Configuration for HTTP client."""
    return {
        "base_url": "https://api.dhan.co",
        "access_token": "test_access_token_12345",
        "timeout": 10.0,
    }


@pytest.fixture
def dhan_http_client(http_client_config: Dict[str, Any]) -> DhanHttpClient:
    """DhanHttpClient instance for testing."""
    return DhanHttpClient(
        base_url=http_client_config["base_url"],
        access_token=http_client_config["access_token"],
        timeout=http_client_config["timeout"],
    )


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Mock HTTP client implementing IHttpClient protocol."""
    client = AsyncMock(spec=IHttpClient)
    client.get = AsyncMock(return_value=HttpResponse(
        status_code=200,
        data={"status": "success"},
        headers={},
    ))
    client.post = AsyncMock(return_value=HttpResponse(
        status_code=200,
        data={"orderId": "ORDER123"},
        headers={},
    ))
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_websocket() -> AsyncMock:
    """Mock WebSocket client implementing IWebSocketClient protocol."""
    ws = AsyncMock(spec=IWebSocketClient)
    ws.is_connected = True
    ws.connect = AsyncMock()
    ws.disconnect = AsyncMock()
    ws.subscribe = AsyncMock()
    ws.unsubscribe = AsyncMock()
    ws.messages = AsyncMock()
    return ws


@pytest.fixture
def dhan_ws_client() -> DhanWebSocketClient:
    """DhanWebSocketClient instance for testing."""
    return DhanWebSocketClient(
        ws_url="wss://api.dhan.co/ws",
        access_token="test_token",
        client_id="CLIENT123",
    )


@pytest.fixture
def rate_limiter() -> TokenBucketRateLimiter:
    """TokenBucketRateLimiter instance for testing."""
    return TokenBucketRateLimiter()


@pytest.fixture
def circuit_breaker() -> DhanCircuitBreaker:
    """DhanCircuitBreaker instance for testing."""
    return DhanCircuitBreaker()


# =============================================================================
# Application Fixtures
# =============================================================================

@pytest.fixture
def dhan_config() -> DhanConfig:
    """DhanConfig instance for testing."""
    return DhanConfig(
        client_id="CLIENT123",
        access_token="test_access_token_12345",
        base_url="https://api.dhan.co",
        ws_url="wss://api.dhan.co/ws",
        timeout=10.0,
        max_retries=3,
        retry_delay=1.0,
        rate_limit_per_second=10.0,
        circuit_breaker_threshold=5,
        circuit_breaker_timeout=60.0,
    )


@pytest.fixture
def clean_env():
    """Clean environment variables for testing from_env."""
    # Store original values
    original_values = {}
    env_vars = [
        "DHAN_CLIENT_ID",
        "DHAN_ACCESS_TOKEN",
        "DHAN_BASE_URL",
        "DHAN_WS_URL",
        "DHAN_TIMEOUT",
        "DHAN_MAX_RETRIES",
        "DHAN_RATE_LIMIT",
    ]
    
    for var in env_vars:
        if var in os.environ:
            original_values[var] = os.environ[var]
            del os.environ[var]
    
    yield
    
    # Restore original values
    for var in env_vars:
        if var in original_values:
            os.environ[var] = original_values[var]
        elif var in os.environ:
            del os.environ[var]


# =============================================================================
# Broker-Agnostic Entity Fixtures
# =============================================================================

@pytest.fixture
def broker_agnostic_instrument() -> Instrument:
    """Sample broker-agnostic Instrument for testing."""
    return Instrument(
        symbol="NIFTY",
        exchange=Exchange.NFO,
        security_id="12345",
        option_type=OptionType.CALL,
        strike=18000.0,
        expiry=date(2023, 2, 23),
    )


@pytest.fixture
def broker_agnostic_quote(broker_agnostic_instrument: Instrument) -> Quote:
    """Sample broker-agnostic Quote for testing."""
    return Quote(
        instrument=broker_agnostic_instrument,
        ltp=18050.50,
        bid=18050.00,
        ask=18051.00,
        volume=1000000,
        open=18000.00,
        high=18100.00,
        low=17950.00,
        close=17980.00,
        timestamp=datetime.now(),
    )


@pytest.fixture
def broker_agnostic_order(broker_agnostic_instrument: Instrument) -> Order:
    """Sample broker-agnostic Order for testing."""
    return Order(
        instrument=broker_agnostic_instrument,
        side=OrderSide.BUY,
        quantity=50.0,
        price=150.00,
        order_id="ORDER123",
        order_type=OrderType.LIMIT,
        filled_quantity=0.0,
        status=OrderStatus.PENDING,
        timestamp=datetime.now(),
    )


@pytest.fixture
def broker_agnostic_position(broker_agnostic_instrument: Instrument) -> Position:
    """Sample broker-agnostic Position for testing."""
    return Position(
        instrument=broker_agnostic_instrument,
        quantity=50.0,
        avg_price=150.00,
        unrealized_pnl=250.00,
        realized_pnl=0.0,
    )


# =============================================================================
# API Response Fixtures
# =============================================================================

@pytest.fixture
def api_quote_response() -> Dict[str, Any]:
    """Sample API response for quote data."""
    return {
        "LTP": 18050.50,
        "open": 18000.00,
        "high": 18100.00,
        "low": 17950.00,
        "close": 17980.00,
        "volume": 1000000,
        "bid": 18050.00,
        "ask": 18051.00,
        "oi": 500000,
        "tradingSymbol": "NIFTY23FEB18000CE",
    }


@pytest.fixture
def api_order_response() -> Dict[str, Any]:
    """Sample API response for order data."""
    return {
        "orderId": "ORDER123",
        "securityId": "12345",
        "tradingSymbol": "NIFTY23FEB18000CE",
        "orderType": "LIMIT",
        "transactionType": "BUY",
        "quantity": 50,
        "price": 150.00,
        "orderStatus": "TRADED",
        "filledQuantity": 50,
        "exchangeSegment": "NSE_FNO",
    }


@pytest.fixture
def api_position_response() -> Dict[str, Any]:
    """Sample API response for position data."""
    return {
        "securityId": "12345",
        "tradingSymbol": "NIFTY23FEB18000CE",
        "netQty": 50,
        "avgPrice": 150.00,
        "unrealizedProfit": 250.00,
        "realizedProfit": 0.0,
        "exchangeSegment": "NSE_FNO",
    }


@pytest.fixture
def api_error_response() -> Dict[str, Any]:
    """Sample API error response."""
    return {
        "errorCode": "DH-1001",
        "message": "Invalid access token",
    }


# =============================================================================
# WebSocket Message Fixtures
# =============================================================================

@pytest.fixture
def ws_tick_message() -> Dict[str, Any]:
    """Sample WebSocket tick message."""
    return {
        "LTP": 18050.50,
        "volume": 1000000,
        "SecurityId": "12345",
    }


@pytest.fixture
def ws_quote_message() -> Dict[str, Any]:
    """Sample WebSocket quote message."""
    return {
        "LTP": 18050.50,
        "Open": 18000.00,
        "High": 18100.00,
        "Low": 17950.00,
        "volume": 1000000,
        "SecurityId": "12345",
    }


@pytest.fixture
def ws_order_message() -> Dict[str, Any]:
    """Sample WebSocket order update message."""
    return {
        "orderId": "ORDER123",
        "orderStatus": "TRADED",
        "filledQuantity": 50,
        "averagePrice": 150.50,
    }
