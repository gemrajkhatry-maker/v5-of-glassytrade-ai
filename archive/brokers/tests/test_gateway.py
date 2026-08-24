"""
TDD Tests for Broker Gateway.

Tests the factory pattern, circuit breaker, and unified API.
"""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import asyncio

from brokers.gateway import (
    BrokerType,
    BrokerFactory,
    CircuitBreaker,
    CircuitState,
    CircuitBreakerError,
    BrokerGateway,
    create_paper_gateway,
    create_dhan_gateway,
)
from brokers.broker.types import Exchange, OrderSide, OrderStatus
from brokers.broker.entities import Instrument, Quote, Tick, Order, Position


class TestBrokerType:
    """Test BrokerType enum."""
    
    def test_broker_type_values(self):
        """BrokerType should have expected values."""
        assert BrokerType.PAPER.value == "paper"
        assert BrokerType.DHAN.value == "dhan"


class TestBrokerFactory:
    """Test BrokerFactory."""
    
    def test_create_paper_broker(self):
        """Factory should create paper broker."""
        broker = BrokerFactory.create(BrokerType.PAPER)
        assert broker is not None
        assert hasattr(broker, 'get_quote')
    
    def test_create_paper_broker_with_prices(self):
        """Factory should pass kwargs to broker."""
        broker = BrokerFactory.create(
            BrokerType.PAPER,
            prices={'CUSTOM': 100.0}
        )
        assert broker is not None
    
    def test_create_unknown_broker_raises(self):
        """Factory should raise for unknown broker type."""
        with pytest.raises(ValueError):
            BrokerFactory.create("unknown_broker")
    
    def test_available_brokers(self):
        """Factory should list available brokers."""
        available = BrokerFactory.available_brokers()
        assert "paper" in available
        assert "dhan" in available
    
    def test_register_custom_broker(self):
        """Factory should allow custom broker registration."""
        from brokers.broker.ports import IBrokerPort
        
        class CustomBroker(IBrokerPort):
            def get_quote(self, instrument): pass
            def get_quotes_batch(self, instruments): return {}
            def get_historical(self, instrument, from_date, to_date, interval="1d"): pass
            async def stream_ticker(self, instruments): pass
            async def stream_quotes(self, instruments): pass
            async def stream_depth(self, instruments, depth_level=20): pass
            def get_option_chain(self, underlying, exchange, expiry_index=0): pass
            def get_expiry_list(self, underlying, exchange): return []
            def place_order(self, order): return order
            def cancel_order(self, order_id): return True
            def get_order_status(self, order_id): pass
            def get_positions(self): return []
            def get_orderbook(self): return []
        
        # Save original registry
        original = BrokerFactory._registry.copy()
        
        try:
            # Register custom broker with PAPER type (override for test)
            BrokerFactory._registry[BrokerType.PAPER] = CustomBroker
            
            # Create should work
            broker = BrokerFactory.create(BrokerType.PAPER)
            assert isinstance(broker, CustomBroker)
        finally:
            # Restore original registry
            BrokerFactory._registry = original


class TestCircuitBreaker:
    """Test CircuitBreaker."""
    
    def test_initial_state_is_closed(self):
        """Circuit breaker should start closed."""
        breaker = CircuitBreaker()
        assert breaker.state == CircuitState.CLOSED
    
    def test_can_execute_when_closed(self):
        """Should allow execution when closed."""
        breaker = CircuitBreaker()
        assert breaker.can_execute() is True
    
    def test_opens_after_threshold_failures(self):
        """Should open after failure threshold."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        # Record failures
        for _ in range(3):
            breaker.record_failure()
        
        assert breaker.state == CircuitState.OPEN
    
    def test_cannot_execute_when_open(self):
        """Should block execution when open."""
        breaker = CircuitBreaker(failure_threshold=1)
        
        breaker.record_failure()
        
        assert breaker.can_execute() is False
    
    def test_context_manager_records_success(self):
        """Context manager should record success."""
        breaker = CircuitBreaker()
        
        with breaker:
            pass  # Success
        
        assert breaker._failure_count == 0
    
    def test_context_manager_records_failure(self):
        """Context manager should record failure."""
        breaker = CircuitBreaker()
        
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("test error")
        
        assert breaker._failure_count == 1
    
    def test_raises_when_open(self):
        """Should raise CircuitBreakerError when open."""
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure()  # Open the circuit
        
        with pytest.raises(CircuitBreakerError):
            with breaker:
                pass
    
    def test_half_open_after_recovery_timeout(self):
        """Should transition to half-open after timeout."""
        import time
        
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.1  # 100ms
        )
        
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        time.sleep(0.15)
        
        assert breaker.state == CircuitState.HALF_OPEN
    
    def test_closes_after_success_threshold_in_half_open(self):
        """Should close after enough successes in half-open."""
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0,
            success_threshold=2
        )
        
        # Force to half-open
        breaker._state = CircuitState.HALF_OPEN
        
        # Record successes
        breaker.record_success()
        assert breaker.state == CircuitState.HALF_OPEN
        
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED


class TestBrokerGateway:
    """Test BrokerGateway."""
    
    @pytest.fixture
    def paper_gateway(self):
        """Create paper gateway for testing."""
        return BrokerGateway.paper()
    
    def test_paper_factory_method(self):
        """Should create paper gateway."""
        gateway = BrokerGateway.paper()
        assert gateway is not None
        assert gateway.broker is not None
    
    def test_create_factory_method(self):
        """Should create gateway with create method."""
        gateway = BrokerGateway.create(BrokerType.PAPER)
        assert gateway is not None
    
    def test_get_quote(self, paper_gateway):
        """Should get quote for symbol."""
        quote = paper_gateway.get_quote("RELIANCE", Exchange.NSE)
        
        assert isinstance(quote, Quote)
        assert quote.instrument.symbol == "RELIANCE"
        assert quote.ltp > 0
    
    def test_get_quotes(self, paper_gateway):
        """Should get quotes for multiple symbols."""
        quotes = paper_gateway.get_quotes(
            ["RELIANCE", "TCS"],
            Exchange.NSE
        )
        
        assert isinstance(quotes, dict)
        assert "RELIANCE" in quotes
        assert "TCS" in quotes
    
    def test_get_positions(self, paper_gateway):
        """Should get positions."""
        positions = paper_gateway.get_positions()
        
        assert isinstance(positions, list)
    
    def test_place_order(self, paper_gateway):
        """Should place order."""
        order = paper_gateway.place_order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side="BUY",
            quantity=10
        )
        
        assert isinstance(order, Order)
        assert order.order_id is not None
        assert order.status == OrderStatus.FILLED  # Paper broker fills immediately
    
    def test_circuit_breaker_protects_gateway(self):
        """Gateway should use circuit breaker."""
        gateway = BrokerGateway.paper()
        
        # Circuit breaker should be available
        assert gateway.circuit_breaker is not None
        assert gateway.circuit_breaker.state == CircuitState.CLOSED
    
    def test_get_option_chain(self, paper_gateway):
        """Should get option chain."""
        chain = paper_gateway.get_option_chain("NIFTY", Exchange.NFO)
        
        assert chain is not None
        assert chain.underlying.symbol == "NIFTY"
    
    def test_get_expiries(self, paper_gateway):
        """Should get expiry list."""
        expiries = paper_gateway.get_expiries("NIFTY", Exchange.NFO)
        
        assert isinstance(expiries, list)
        assert len(expiries) > 0


class TestBrokerGatewayStreaming:
    """Test BrokerGateway streaming methods."""
    
    @pytest.fixture
    def paper_gateway(self):
        """Create paper gateway for testing."""
        return BrokerGateway.paper()
    
    @pytest.mark.asyncio
    async def test_stream_ticker(self, paper_gateway):
        """Should stream ticker data."""
        ticks = []
        
        async for tick in paper_gateway.stream_ticker(["RELIANCE"], Exchange.NSE):
            ticks.append(tick)
            if len(ticks) >= 3:
                break
        
        assert len(ticks) >= 1
        assert isinstance(ticks[0], Tick)
    
    @pytest.mark.asyncio
    async def test_stream_quotes(self, paper_gateway):
        """Should stream quote data."""
        quotes = []
        
        async for quote in paper_gateway.stream_quotes(["RELIANCE"], Exchange.NSE):
            quotes.append(quote)
            if len(quotes) >= 3:
                break
        
        assert len(quotes) >= 1
        assert isinstance(quotes[0], Quote)


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_create_paper_gateway(self):
        """Should create paper gateway."""
        gateway = create_paper_gateway()
        assert gateway is not None
        assert hasattr(gateway, 'get_quote')
    
    def test_create_dhan_gateway_with_mocks(self):
        """Should create Dhan gateway with mocked dependencies."""
        # Mock the infrastructure components
        with patch('brokers.broker.dhan.infrastructure.DhanHttpClient'), \
             patch('brokers.broker.dhan.infrastructure.DhanWebSocketClient'), \
             patch('brokers.broker.dhan.infrastructure.DhanSymbolMapper'), \
             patch('brokers.broker.dhan.infrastructure.DhanAuthProvider'), \
             patch('brokers.broker.dhan.infrastructure.TokenBucketRateLimiter'), \
             patch('brokers.broker.dhan.infrastructure.DhanCircuitBreaker'):
            
            gateway = create_dhan_gateway(
                client_id='test_id',
                access_token='test_token'
            )
            
            assert gateway is not None

    def test_gateway_dhan_get_quote_returns_quote(self):
        """Integration: BrokerGateway.dhan() -> get_quote returns Quote (with mocked broker)."""
        from unittest.mock import AsyncMock
        from brokers.broker.dhan.ports import IHttpClient
        from brokers.broker.dhan.ports import HttpResponse
        from brokers.broker.dhan.application import DhanBroker, DhanConfig

        mock_http = AsyncMock(spec=IHttpClient)
        mock_http.get = AsyncMock(return_value=HttpResponse(
            status_code=200,
            data={"data": {}},
            headers={},
        ))
        mock_http.post = AsyncMock(return_value=HttpResponse(
            status_code=200,
            data={"data": {"NSE_EQ": {"12345": {
                "last_price": 2500.0,
                "ohlc": {"open": 2480.0, "high": 2510.0, "low": 2475.0, "close": 2495.0},
                "volume": 1000000,
                "depth": {"buy": [{"price": 2499.0}], "sell": [{"price": 2501.0}]},
            }}}},
            headers={},
        ))
        mock_http.close = AsyncMock()
        mock_mapper = AsyncMock()
        mock_mapper.get_security_id = AsyncMock(return_value="12345")
        mock_mapper.refresh_cache = AsyncMock()

        config = DhanConfig(client_id="test", access_token="test")
        broker = DhanBroker(
            config=config,
            http_client=mock_http,
            symbol_mapper=mock_mapper,
            ws_client=None,
            rate_limiter=None,
            circuit_breaker=None,
        )
        gateway = BrokerGateway(broker=broker)
        quote = gateway.get_quote("RELIANCE", Exchange.NSE)
        assert quote is not None
        assert isinstance(quote, Quote)
        assert hasattr(quote, "ltp")
        assert quote.instrument.symbol == "RELIANCE"


class TestBrokerGatewayOrderManagement:
    """Test cancel_order and get_order_status on BrokerGateway."""

    @pytest.fixture
    def paper_gateway(self):
        return BrokerGateway.paper()

    def test_cancel_order_returns_bool(self, paper_gateway):
        """cancel_order should return bool."""
        # Place an order first so we have a real order_id
        order = paper_gateway.place_order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side="BUY",
            quantity=10,
        )
        result = paper_gateway.cancel_order(order.order_id)
        assert isinstance(result, bool)

    def test_cancel_nonexistent_order_returns_false(self, paper_gateway):
        """cancel_order on unknown id returns False (paper broker)."""
        result = paper_gateway.cancel_order("NONEXISTENT_999")
        assert result is False

    def test_get_order_status_returns_order(self, paper_gateway):
        """get_order_status should return an Order for a known id."""
        placed = paper_gateway.place_order(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            side="BUY",
            quantity=1,
        )
        result = paper_gateway.get_order_status(placed.order_id)
        assert isinstance(result, Order)
        assert result.order_id == placed.order_id

    def test_place_order_with_trigger_price_and_product_type(self, paper_gateway):
        """place_order accepts trigger_price and product_type kwargs."""
        order = paper_gateway.place_order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side="BUY",
            quantity=5,
            price=2490.0,
            trigger_price=2480.0,
            product_type="CNC",
        )
        assert isinstance(order, Order)
        assert order.trigger_price == 2480.0
        assert order.product_type == "CNC"

    def test_circuit_breaker_blocks_cancel_when_open(self):
        """Circuit breaker should block cancel_order when open."""
        mock_broker = MagicMock()
        mock_broker.cancel_order.side_effect = Exception("Network error")

        gateway = BrokerGateway(
            broker=mock_broker,
            circuit_breaker=CircuitBreaker(failure_threshold=1),
        )

        # First call fails and opens circuit
        try:
            gateway.cancel_order("ORDER1")
        except Exception:
            pass

        # Second call should be blocked by circuit breaker
        with pytest.raises(CircuitBreakerError):
            gateway.cancel_order("ORDER1")

    def test_circuit_breaker_blocks_get_order_status_when_open(self):
        """Circuit breaker should block get_order_status when open."""
        mock_broker = MagicMock()
        mock_broker.get_order_status.side_effect = Exception("Network error")

        gateway = BrokerGateway(
            broker=mock_broker,
            circuit_breaker=CircuitBreaker(failure_threshold=1),
        )

        try:
            gateway.get_order_status("ORDER1")
        except Exception:
            pass

        with pytest.raises(CircuitBreakerError):
            gateway.get_order_status("ORDER1")


class TestGatewayFaultTolerance:
    """Test gateway fault tolerance features."""
    
    def test_gateway_with_custom_circuit_breaker(self):
        """Should accept custom circuit breaker."""
        custom_breaker = CircuitBreaker(
            failure_threshold=10,
            recovery_timeout=120
        )
        
        gateway = BrokerGateway.paper()
        gateway._circuit_breaker = custom_breaker
        
        assert gateway.circuit_breaker.failure_threshold == 10
    
    def test_multiple_failures_open_circuit(self):
        """Multiple failures should open the circuit."""
        from brokers.broker.dhan.domain import DhanNetworkError
        
        # Create a mock broker that always fails
        mock_broker = MagicMock()
        mock_broker.get_quote.side_effect = Exception("API Error")
        
        gateway = BrokerGateway(
            broker=mock_broker,
            circuit_breaker=CircuitBreaker(failure_threshold=2)
        )
        
        # Make failing calls
        for _ in range(3):
            try:
                gateway.get_quote("TEST", Exchange.NSE)
            except Exception:
                pass
        
        # Circuit should be open
        assert gateway.circuit_breaker.state == CircuitState.OPEN
