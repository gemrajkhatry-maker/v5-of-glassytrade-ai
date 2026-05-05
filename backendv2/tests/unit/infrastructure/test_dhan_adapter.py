"""Tests for Dhan broker adapter."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from app.infrastructure.adapters.dhan_adapter import DhanAdapter


class TestDhanAdapter:
    """Tests for Dhan adapter."""
    
    @pytest.fixture
    def dhan(self):
        return DhanAdapter(
            client_id="test_client",
            access_token="test_token",
            testnet=True
        )
    
    @pytest.mark.asyncio
    async def test_place_order_success(self, dhan):
        """Test successful order placement."""
        mock_response = AsyncMock()
        mock_response.json = MagicMock(return_value={"orderId": "12345", "status": "PENDING"})
        mock_response.raise_for_status = MagicMock()
        
        dhan._client.post = AsyncMock(return_value=mock_response)
        
        result = await dhan.place_order("RELIANCE", "BUY", 10, 2500.0)
        
        assert result["order_id"] == "12345"
        assert result["symbol"] == "RELIANCE"
        assert result["side"] == "BUY"
    
    @pytest.mark.asyncio
    async def test_cancel_order_success(self, dhan):
        """Test successful order cancellation."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        
        dhan._client.delete = AsyncMock(return_value=mock_response)
        
        result = await dhan.cancel_order("12345")
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cancel_order_failure(self, dhan):
        """Test failed order cancellation."""
        dhan._client.delete = AsyncMock(side_effect=Exception("Order not found"))
        
        result = await dhan.cancel_order("nonexistent")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_position_found(self, dhan):
        """Test getting position when it exists."""
        mock_response = AsyncMock()
        mock_response.json = MagicMock(return_value=[
            {
                "tradingSymbol": "RELIANCE",
                "netQty": "10",
                "avgCostPrice": "2500.0",
                "pnl": "500.0"
            }
        ])
        mock_response.raise_for_status = MagicMock()
        
        dhan._client.get = AsyncMock(return_value=mock_response)
        
        result = await dhan.get_position("RELIANCE")
        
        assert result["symbol"] == "RELIANCE"
        assert result["quantity"] == Decimal("10")
    
    @pytest.mark.asyncio
    async def test_get_position_not_found(self, dhan):
        """Test getting position when it doesn't exist."""
        mock_response = AsyncMock()
        mock_response.json = MagicMock(return_value=[])
        mock_response.raise_for_status = MagicMock()
        
        dhan._client.get = AsyncMock(return_value=mock_response)
        
        result = await dhan.get_position("NONEXISTENT")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_close(self, dhan):
        """Test closing HTTP client."""
        await dhan.close()
        # Should not raise any errors