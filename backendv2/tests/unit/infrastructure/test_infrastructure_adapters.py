"""Unit tests for infrastructure adapters."""
import pytest
from decimal import Decimal
from app.infrastructure.adapters.infrastructure_adapters import (
    SQLiteStorage, SQLiteConfig, BinanceAdapter, BinanceMarketDataAdapter
)
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus
import tempfile
import os


def _legacy_binance_enabled() -> bool:
    return os.getenv("ENABLE_LEGACY_BINANCE_ADAPTERS", "").lower() in {"1", "true", "yes", "on"}


class TestSQLiteStorage:
    """Tests for SQLite storage adapter."""
    
    def setup_method(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.config = SQLiteConfig(db_path=self.temp_db.name)
        self.storage = SQLiteStorage(self.config)
    
    def teardown_method(self):
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)
    
    def test_saves_and_retrieves_position(self):
        """Test position persistence."""
        position = Position(
            id="test_123",
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=Decimal("50000"),
            size=Decimal("0.1"),
            stop_loss=Decimal("49500"),
            take_profit=Decimal("51000"),
            status=PositionStatus.OPEN
        )
        
        # Save
        self.storage.save_position(position)
        
        # Retrieve
        loaded = self.storage.get_position("test_123")
        
        assert loaded is not None
        assert loaded.symbol == "BTCUSDT"
        assert loaded.side == Side.LONG
        assert loaded.entry_price == Decimal("50000")
    
    def test_returns_none_for_missing_position(self):
        """Test retrieval of non-existent position."""
        result = self.storage.get_position("nonexistent")
        assert result is None


@pytest.mark.skipif(not _legacy_binance_enabled(), reason="Legacy Binance adapters are disabled by default.")
class TestBinanceAdapter:
    """Tests for Binance broker adapter."""
    
    def setup_method(self):
        self.adapter = BinanceAdapter(api_key="test", api_secret="test", testnet=True)
    
    @pytest.mark.asyncio
    async def test_place_order_returns_order_data(self):
        """Test order placement."""
        result = await self.adapter.place_order(
            symbol="BTCUSDT",
            side="BUY",
            qty=0.1,
            price=50000.0
        )
        
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "BUY"
        assert result["qty"] == 0.1


@pytest.mark.skipif(not _legacy_binance_enabled(), reason="Legacy Binance adapters are disabled by default.")
class TestBinanceMarketDataAdapter:
    """Tests for Binance market data adapter."""
    
    def setup_method(self):
        self.adapter = BinanceMarketDataAdapter(testnet=True)
    
    @pytest.mark.asyncio
    async def test_get_ticker_returns_data(self):
        """Test ticker retrieval."""
        result = await self.adapter.get_ticker("BTCUSDT")
        
        assert result["symbol"] == "BTCUSDT"
        assert "price" in result
    
    @pytest.mark.asyncio
    async def test_get_orderbook_returns_depth(self):
        """Test orderbook retrieval."""
        result = await self.adapter.get_orderbook("BTCUSDT", depth=10)
        
        assert len(result["bids"]) == 10
        assert len(result["asks"]) == 10