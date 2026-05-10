"""
Tests for testing mocks (DryRunBroker).
"""

import pytest
from decimal import Decimal

from brokersv2.testing.mocks import DryRunBroker


class TestDryRunBroker:
    """Test DryRunBroker mock implementation."""
    
    @pytest.fixture
    def broker(self):
        """Create a DryRunBroker instance."""
        return DryRunBroker()
    
    def test_place_order_mock(self, broker):
        """Should generate mock order with DRY_RUN prefix."""
        result = broker.place_order_mock(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=10,
            side="BUY",
            order_type="MARKET",
            price=None,
        )
        
        assert result["operation"] == "place_order"
        assert result["symbol"] == "RELIANCE"
        assert result["quantity"] == 10
        assert result["side"] == "BUY"
        assert result["status"] == "COMPLETED"
        assert result["dry_run"] is True
        assert result["order_id"].startswith("DRY_RUN_")
        assert len(broker.operation_log) == 1
    
    def test_cancel_order_mock(self, broker):
        """Should generate mock cancellation."""
        result = broker.cancel_order_mock("DRY_RUN_123")
        
        assert result["operation"] == "cancel_order"
        assert result["order_id"] == "DRY_RUN_123"
        assert result["cancelled"] is True
        assert result["dry_run"] is True
        assert len(broker.operation_log) == 1
    
    def test_get_quote_mock_known_symbol(self, broker):
        """Should return realistic quote for known symbol."""
        result = broker.get_quote_mock("RELIANCE")
        
        assert result["symbol"] == "RELIANCE"
        assert result["ltp"] > 0
        assert result["open"] > 0
        assert result["high"] > 0
        assert result["low"] > 0
        assert result["close"] > 0
        assert result["volume"] > 0
        assert result["dry_run"] is True
        # RELIANCE base price is 2500
        assert 2400 < result["ltp"] < 2600
    
    def test_get_quote_mock_unknown_symbol(self, broker):
        """Should return default quote for unknown symbol."""
        result = broker.get_quote_mock("UNKNOWN")
        
        assert result["symbol"] == "UNKNOWN"
        assert result["ltp"] > 0
        # Default base price is 1000
        assert 900 < result["ltp"] < 1100
    
    def test_get_historical_mock(self, broker):
        """Should return mock historical candles."""
        result = broker.get_historical_mock(
            symbol="RELIANCE",
            exchange="NSE",
            from_date="2024-01-01",
            to_date="2024-01-31",
            interval="1d",
        )
        
        assert result["symbol"] == "RELIANCE"
        assert result["exchange"] == "NSE"
        assert result["interval"] == "1d"
        assert result["count"] == 30
        assert len(result["candles"]) == 30
        assert result["dry_run"] is True
        
        # Check candle structure
        candle = result["candles"][0]
        assert "timestamp" in candle
        assert "open" in candle
        assert "high" in candle
        assert "low" in candle
        assert "close" in candle
        assert "volume" in candle
    
    def test_operation_log_accumulates(self, broker):
        """Should accumulate operations in log."""
        broker.place_order_mock("A", "NSE", 1, "BUY", "MARKET")
        broker.place_order_mock("B", "NSE", 2, "SELL", "LIMIT", 100.0)
        broker.cancel_order_mock("DRY_RUN_1")
        
        assert len(broker.operation_log) == 3
        assert broker.operation_log[0]["symbol"] == "A"
        assert broker.operation_log[1]["symbol"] == "B"
        assert broker.operation_log[2]["operation"] == "cancel_order"
