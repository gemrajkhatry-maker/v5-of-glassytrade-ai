"""Tests for error hierarchy."""

import pytest
from brokersv2.core.errors import (
    BrokersV2Error,
    BrokerConnectionError,
    BrokerAuthenticationError,
    BrokerRateLimitError,
    BrokerOrderError,
    BrokerDataError,
    CircuitBreakerOpenError,
    InstrumentNotFoundError,
)


class TestErrorHierarchy:
    """Tests for error class hierarchy."""

    def test_base_error(self):
        """Test base error can be raised and caught."""
        with pytest.raises(BrokersV2Error):
            raise BrokersV2Error("Base error")

    def test_connection_error_inheritance(self):
        """Test connection error inherits from base."""
        error = BrokerConnectionError("Connection failed")
        assert isinstance(error, BrokersV2Error)
        assert str(error) == "Connection failed"

    def test_authentication_error(self):
        """Test authentication error."""
        error = BrokerAuthenticationError("Token expired")
        assert isinstance(error, BrokersV2Error)
        assert isinstance(error, BrokerAuthenticationError)

    def test_rate_limit_error(self):
        """Test rate limit error."""
        error = BrokerRateLimitError("Rate limit exceeded")
        assert isinstance(error, BrokersV2Error)
        assert "Rate limit" in str(error)

    def test_order_error(self):
        """Test order error."""
        error = BrokerOrderError("Order rejected")
        assert isinstance(error, BrokersV2Error)

    def test_data_error(self):
        """Test data error."""
        error = BrokerDataError("Invalid data")
        assert isinstance(error, BrokersV2Error)

    def test_circuit_breaker_error(self):
        """Test circuit breaker error."""
        error = CircuitBreakerOpenError("Circuit open")
        assert isinstance(error, BrokersV2Error)

    def test_instrument_not_found_error(self):
        """Test instrument not found error."""
        error = InstrumentNotFoundError("RELIANCE")
        assert isinstance(error, BrokersV2Error)
        assert "RELIANCE" in str(error)

    def test_catch_all_brokersv2_errors(self):
        """Test catching all BrokersV2Error subclasses."""
        errors = [
            BrokerConnectionError("conn"),
            BrokerAuthenticationError("auth"),
            BrokerRateLimitError("rate"),
            BrokerOrderError("order"),
        ]
        
        for error in errors:
            try:
                raise error
            except BrokersV2Error as e:
                assert isinstance(e, BrokersV2Error)

    def test_error_with_context(self):
        """Test error with additional context."""
        error = BrokerOrderError(
            "Order rejected",
            order_id="12345",
            reason="Insufficient margin",
        )
        assert hasattr(error, 'order_id')
        assert error.order_id == "12345"
        assert error.reason == "Insufficient margin"
