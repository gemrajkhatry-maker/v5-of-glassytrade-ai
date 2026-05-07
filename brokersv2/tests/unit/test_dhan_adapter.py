"""Tests for Dhan Broker Adapter - TDD-first approach."""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime

from brokersv2.infrastructure.dhan_adapter.adapter import DhanBrokerAdapter
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
from brokersv2.domain.order.models import Order
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import (
    OrderId,
    OrderSide,
    OrderType,
    Exchange,
    SecurityId,
)
from brokersv2.core.errors import BrokerConnectionError, BrokerAuthenticationError


class TestDhanBrokerAdapter:
    """Tests for DhanBrokerAdapter."""

    @pytest.fixture
    def mapper(self):
        """Create instrument mapper."""
        mapper = InstrumentMapper()
        
        # Register test instrument
        instrument = CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE
        )
        mapper.register(instrument, SecurityId("12345"), "NSE_EQ")
        
        return mapper

    @pytest.fixture
    def config(self):
        """Create Dhan config."""
        return DhanConfig(
            client_id="test_client",
            access_token="test_token",
        )

    @pytest.fixture
    def adapter(self, config, mapper):
        """Create broker adapter."""
        return DhanBrokerAdapter(config, mapper)

    @pytest.mark.asyncio
    async def test_place_order_async(self, adapter):
        """Test async order placement."""
        # Mock the HTTP client
        adapter._client.place_order = AsyncMock(return_value="broker_order_123")
        
        instrument = CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE
        )
        order = Order(
            order_id=OrderId("test_order_1"),
            instrument=instrument,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        
        # Should be fully async - no asyncio.run()
        result = await adapter.place_order(order)
        
        assert result == "broker_order_123"
        adapter._client.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_order_async(self, adapter):
        """Test async order cancellation."""
        adapter._client.cancel_order = AsyncMock(return_value=True)
        
        result = await adapter.cancel_order("broker_order_123")
        
        assert result is True
        adapter._client.cancel_order.assert_called_once_with("broker_order_123")

    @pytest.mark.asyncio
    async def test_get_order_status_async(self, adapter):
        """Test async order status retrieval."""
        mock_order = Mock()
        adapter._client.get_order_status = AsyncMock(return_value=mock_order)
        
        result = await adapter.get_order_status("broker_order_123")
        
        assert result == mock_order
        adapter._client.get_order_status.assert_called_once_with("broker_order_123")

    @pytest.mark.asyncio
    async def test_get_quote_async(self, adapter, mapper):
        """Test async quote retrieval."""
        from brokersv2.domain.market.models import Quote
        
        mock_quote = Mock(spec=Quote)
        adapter._client.get_quote = AsyncMock(return_value=mock_quote)
        
        instrument = CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE
        )
        
        result = await adapter.get_quote(instrument)
        
        assert result == mock_quote
        adapter._client.get_quote.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_historical_async(self, adapter):
        """Test async historical data retrieval."""
        adapter._client.get_historical = AsyncMock(return_value=[])
        
        instrument = CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE
        )
        
        result = await adapter.get_historical(
            instrument,
            from_date="2024-01-01",
            to_date="2024-12-31",
            interval="1d"
        )
        
        assert result == []
        adapter._client.get_historical.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_adapter(self, adapter):
        """Test async adapter cleanup."""
        adapter._client.close = AsyncMock()
        
        await adapter.close()
        
        adapter._client.close.assert_called_once()

    def test_no_asyncio_run_in_place_order(self, adapter):
        """Verify place_order doesn't use asyncio.run() anti-pattern."""
        import inspect
        
        # Should be a coroutine function
        assert asyncio.iscoroutinefunction(adapter.place_order), \
            "place_order should be async def"
        
        # Check actual code lines (not docstrings or comments)
        source_lines = inspect.getsourcelines(adapter.place_order)[0]
        code_lines = []
        in_docstring = False
        for line in source_lines:
            stripped = line.strip()
            if '"""' in stripped or "'''" in stripped:
                in_docstring = not in_docstring
                continue
            if not in_docstring and not stripped.startswith('#'):
                code_lines.append(line)
        code_text = ''.join(code_lines)
        
        # Should NOT contain asyncio.run() in actual code
        assert "asyncio.run(" not in code_text, \
            "place_order should not call asyncio.run()"

    def _check_no_asyncio_run(self, method):
        """Helper to check a method doesn't use asyncio.run()."""
        import inspect
        
        assert asyncio.iscoroutinefunction(method), \
            f"{method.__name__} should be async def"
        
        source_lines = inspect.getsourcelines(method)[0]
        code_lines = []
        in_docstring = False
        for line in source_lines:
            stripped = line.strip()
            if '"""' in stripped or "'''" in stripped:
                in_docstring = not in_docstring
                continue
            if not in_docstring and not stripped.startswith('#'):
                code_lines.append(line)
        code_text = ''.join(code_lines)
        
        assert "asyncio.run(" not in code_text, \
            f"{method.__name__} should not call asyncio.run()"

    def test_no_asyncio_run_in_cancel_order(self, adapter):
        """Verify cancel_order doesn't use asyncio.run() anti-pattern."""
        self._check_no_asyncio_run(adapter.cancel_order)

    def test_no_asyncio_run_in_get_order_status(self, adapter):
        """Verify get_order_status doesn't use asyncio.run() anti-pattern."""
        self._check_no_asyncio_run(adapter.get_order_status)

    def test_no_asyncio_run_in_get_quote(self, adapter):
        """Verify get_quote doesn't use asyncio.run() anti-pattern."""
        self._check_no_asyncio_run(adapter.get_quote)

    def test_no_asyncio_run_in_get_historical(self, adapter):
        """Verify get_historical doesn't use asyncio.run() anti-pattern."""
        self._check_no_asyncio_run(adapter.get_historical)


class TestDhanBrokerAdapterIntegration:
    """Integration tests for DhanBrokerAdapter."""

    @pytest.mark.asyncio
    async def test_full_order_lifecycle(self):
        """Test complete order placement flow."""
        mapper = InstrumentMapper()
        instrument = CanonicalInstrument.create_equity(
            symbol="TCS",
            exchange=Exchange.NSE
        )
        mapper.register(instrument, SecurityId("11111"), "NSE_EQ")
        
        config = DhanConfig(
            client_id="test_client",
            access_token="test_token",
        )
        
        adapter = DhanBrokerAdapter(config, mapper)
        
        # Mock client methods
        adapter._client.place_order = AsyncMock(return_value="order_456")
        adapter._client.get_order_status = AsyncMock(return_value=Mock())
        adapter._client.cancel_order = AsyncMock(return_value=True)
        
        # Place order
        order = Order(
            order_id=OrderId("test_1"),
            instrument=instrument,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("5"),
            price=Decimal("3500"),
        )
        
        broker_id = await adapter.place_order(order)
        assert broker_id == "order_456"
        
        # Check status
        status = await adapter.get_order_status(broker_id)
        assert status is not None
        
        # Cancel order
        cancelled = await adapter.cancel_order(broker_id)
        assert cancelled is True

    @pytest.mark.asyncio
    async def test_adapter_with_circuit_breaker(self):
        """Test adapter integrates with circuit breaker."""
        from brokersv2.core.resilience import CircuitBreaker
        
        mapper = InstrumentMapper()
        config = DhanConfig(
            client_id="test",
            access_token="test",
        )
        
        adapter = DhanBrokerAdapter(config, mapper)
        
        # Circuit breaker can be attached
        adapter._circuit_breaker = CircuitBreaker(failure_threshold=3)
        
        # Should work normally when circuit is closed
        adapter._client.get_quote = AsyncMock(return_value=Mock())
        
        instrument = CanonicalInstrument.create_equity(
            symbol="INFY",
            exchange=Exchange.NSE
        )
        
        result = await adapter.get_quote(instrument)
        assert result is not None
