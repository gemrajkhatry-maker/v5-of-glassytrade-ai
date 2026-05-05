"""PostgreSQL storage adapter for production deployment."""
from dataclasses import dataclass
from typing import Optional, List
import asyncio
from decimal import Decimal

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus, CushionState


@dataclass
class PostgreSQLConfig:
    """PostgreSQL database configuration."""
    host: str = "localhost"
    port: int = 5432
    database: str = "trading"
    username: str = "trading_user"
    password: str = ""
    min_size: int = 10
    max_size: int = 20


class PostgreSQLStorage:
    """PostgreSQL storage adapter with connection pooling."""
    
    def __init__(self, config: PostgreSQLConfig):
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Create connection pool."""
        if not HAS_ASYNCPG:
            raise ImportError("asyncpg not installed. Run: pip install asyncpg")
        
        self._pool = await asyncpg.create_pool(
            host=self._config.host,
            port=self._config.port,
            database=self._config.database,
            username=self._config.username,
            password=self._config.password,
            min_size=self._config.min_size,
            max_size=self._config.max_size
        )
        await self._init_schema()
    
    async def _init_schema(self):
        """Initialize database schema."""
        if not self._pool:
            return
            
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price NUMERIC NOT NULL,
                    size NUMERIC NOT NULL,
                    stop_loss NUMERIC NOT NULL,
                    take_profit NUMERIC NOT NULL,
                    status TEXT NOT NULL,
                    exit_price NUMERIC,
                    pnl NUMERIC,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)
            """)
    
    async def save_position(self, position: Position) -> None:
        """Persist position to PostgreSQL."""
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")
        
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO positions 
                (id, symbol, side, entry_price, size, stop_loss, take_profit, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    exit_price = EXCLUDED.exit_price,
                    pnl = EXCLUDED.pnl,
                    updated_at = NOW()
            """, 
                position.id,
                position.symbol,
                position.side.value,
                float(position.entry_price),
                float(position.size),
                float(position.stop_loss),
                float(position.take_profit),
                position.status.value
            )
    
    async def get_position(self, position_id: str) -> Optional[Position]:
        """Load position from PostgreSQL."""
        if not self._pool:
            return None
        
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM positions WHERE id = $1", position_id
            )
            
            if not row:
                return None
            
            return Position(
                id=row['id'],
                symbol=row['symbol'],
                side=Side(row['side']),
                entry_price=Decimal(str(row['entry_price'])),
                size=Decimal(str(row['size'])),
                stop_loss=Decimal(str(row['stop_loss'])),
                take_profit=Decimal(str(row['take_profit'])),
                status=PositionStatus(row['status'])
            )
    
    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Get all open positions."""
        if not self._pool:
            return []
        
        async with self._pool.acquire() as conn:
            if symbol:
                rows = await conn.fetch(
                    "SELECT * FROM positions WHERE status = 'OPEN' AND symbol = $1",
                    symbol
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM positions WHERE status = 'OPEN'"
                )
            
            return [
                Position(
                    id=row['id'],
                    symbol=row['symbol'],
                    side=Side(row['side']),
                    entry_price=Decimal(str(row['entry_price'])),
                    size=Decimal(str(row['size'])),
                    stop_loss=Decimal(str(row['stop_loss'])),
                    take_profit=Decimal(str(row['take_profit'])),
                    status=PositionStatus(row['status'])
                )
                for row in rows
            ]
    
    async def close(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()