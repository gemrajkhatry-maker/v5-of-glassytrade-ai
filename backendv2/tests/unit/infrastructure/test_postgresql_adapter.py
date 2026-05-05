"""Tests for PostgreSQL storage adapter."""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.infrastructure.adapters.postgresql_adapter import (
    PostgreSQLStorage, PostgreSQLConfig
)
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus, CushionState, CushionState


class TestPostgreSQLStorage:
    """Tests for PostgreSQL storage."""
    
    @pytest.fixture
    def config(self):
        return PostgreSQLConfig(
            host="localhost",
            database="test_trading",
            username="test_user",
            password="test_pass"
        )
    
    @pytest.fixture
    def storage(self, config):
        return PostgreSQLStorage(config)
    
    @pytest.fixture
    def sample_position(self):
        return Position(
            id="pos-123",
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=Decimal("50000"),
            size=Decimal("0.001"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            status=PositionStatus.OPEN
        )
    
    def test_has_asyncpg_check(self):
        """Test that missing asyncpg raises proper error."""
        storage = PostgreSQLStorage(PostgreSQLConfig())
        
        async def connect_without_asyncpg():
            with patch('app.infrastructure.adapters.postgresql_adapter.HAS_ASYNCPG', False):
                storage._pool = None
                with pytest.raises(ImportError):
                    await storage.connect()
        
        import asyncio
        asyncio.run(connect_without_asyncpg())
    
    @pytest.mark.asyncio
    async def test_save_and_load_position(self, storage, sample_position):
        """Test saving and loading a position."""
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        
        # Mock execute for INSERT
        mock_conn.execute = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            'id': 'pos-123',
            'symbol': 'BTCUSDT',
            'side': 'LONG',
            'entry_price': '50000',
            'size': '0.001',
            'stop_loss': '49000',
            'take_profit': '52000',
            'status': 'OPEN',
            'exit_price': None,
            'pnl': None
        })
        
        # Create async context manager mock
        mock_acm = AsyncMock()
        mock_acm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acm)
        storage._pool = mock_pool
        
        await storage.save_position(sample_position)
        
        # Verify execute was called
        assert mock_conn.execute.called
        
        loaded = await storage.get_position("pos-123")
        assert loaded is not None
        assert loaded.id == "pos-123"
        assert loaded.symbol == "BTCUSDT"
    
    @pytest.mark.asyncio
    async def test_get_open_positions(self, storage):
        """Test getting open positions."""
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        
        mock_conn.fetch = AsyncMock(return_value=[
            {
                'id': 'pos-1',
                'symbol': 'BTCUSDT',
                'side': 'LONG',
                'entry_price': '50000',
                'size': '0.001',
                'stop_loss': '49000',
                'take_profit': '52000',
                'status': 'OPEN'
            },
            {
                'id': 'pos-2',
                'symbol': 'ETHUSDT',
                'side': 'SHORT',
                'entry_price': '3000',
                'size': '0.1',
                'stop_loss': '3100',
                'take_profit': '2900',
                'status': 'OPEN'
            }
        ])
        
        # Create async context manager mock
        mock_acm = AsyncMock()
        mock_acm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acm)
        storage._pool = mock_pool
        
        positions = await storage.get_open_positions()
        assert len(positions) == 2
    
    @pytest.mark.asyncio
    async def test_get_position_returns_none_when_not_found(self, storage):
        """Test get_position returns None for missing position."""
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        
        # Create async context manager mock
        mock_acm = AsyncMock()
        mock_acm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acm)
        storage._pool = mock_pool
        
        loaded = await storage.get_position("nonexistent")
        assert loaded is None