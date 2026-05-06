"""Infrastructure adapters for backendv2 - zero parity with existing backend."""
from dataclasses import dataclass
from typing import Optional, Protocol
import asyncio
import sqlite3
from contextlib import contextmanager
import os

# Import domain models from backendv2
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus


_LEGACY_BINANCE_ENABLED = os.getenv("ENABLE_LEGACY_BINANCE_ADAPTERS", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _ensure_legacy_binance_enabled() -> None:
    if _LEGACY_BINANCE_ENABLED:
        return
    raise NotImplementedError(
        "Legacy Binance adapters are disabled by default. "
        "Set ENABLE_LEGACY_BINANCE_ADAPTERS=true to opt into this shim."
    )


class IBroker(Protocol):
    """Protocol for broker adapter (Binance/Dhan integration)."""
    
    async def place_order(self, symbol: str, side: str, qty: float, price: float) -> dict:
        """Place a new order."""
        ...
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        ...
    
    async def get_position(self, symbol: str) -> Optional[dict]:
        """Get current position for symbol."""
        ...


class IMarketData(Protocol):
    """Protocol for market data adapter."""
    
    async def get_ticker(self, symbol: str) -> dict:
        """Get current ticker data."""
        ...
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        """Get order book depth."""
        ...
    
    async def stream_ticks(self, symbol: str):
        """Async generator for tick stream."""
        ...


@dataclass
class SQLiteConfig:
    """SQLite database configuration."""
    db_path: str = "trading.db"


class SQLiteStorage:
    """SQLite storage adapter implementing IStorage."""
    
    def __init__(self, config: SQLiteConfig):
        self._config = config
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    size REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    status TEXT NOT NULL,
                    exit_price REAL,
                    pnl REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    payload TEXT NOT NULL
                )
            """)
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(self._config.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def save_position(self, position: Position) -> None:
        """Persist position to database."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO positions 
                (id, symbol, side, entry_price, size, stop_loss, take_profit, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.id,
                position.symbol,
                position.side.value,
                float(position.entry_price),
                float(position.size),
                float(position.stop_loss),
                float(position.take_profit),
                position.status.value
            ))
            conn.commit()
    
    def get_position(self, position_id: str) -> Optional[Position]:
        """Load position from database."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE id = ?", (position_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return Position(
                id=row['id'],
                symbol=row['symbol'],
                side=Side(row['side']),
                entry_price=row['entry_price'],
                size=row['size'],
                stop_loss=row['stop_loss'],
                take_profit=row['take_profit'],
                status=PositionStatus(row['status'])
            )
    
    def save_event(self, event) -> None:
        """Persist domain event."""
        import json
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO events (event_id, event_type, payload)
                VALUES (?, ?, ?)
            """, (event.event_id, event.__class__.__name__, json.dumps(event.__dict__)))
            conn.commit()


class BinanceAdapter:
    """Binance broker adapter."""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        _ensure_legacy_binance_enabled()
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._base_url = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
    
    async def place_order(self, symbol: str, side: str, qty: float, price: float) -> dict:
        """Place order via Binance API."""
        _ensure_legacy_binance_enabled()
        # Placeholder - would use aiohttp for async HTTP
        return {
            "order_id": f"{symbol}_{asyncio.get_event_loop().time()}",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "status": "NEW"
        }
    
    async def get_position(self, symbol: str) -> Optional[dict]:
        """Get position from Binance."""
        _ensure_legacy_binance_enabled()
        return None  # Placeholder


class BinanceMarketDataAdapter:
    """Binance market data adapter."""
    
    def __init__(self, testnet: bool = True):
        _ensure_legacy_binance_enabled()
        self._testnet = testnet
    
    async def get_ticker(self, symbol: str) -> dict:
        """Get ticker from Binance."""
        _ensure_legacy_binance_enabled()
        return {
            "symbol": symbol,
            "price": 50000.0,
            "bid": 49999.0,
            "ask": 50001.0
        }
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        """Get orderbook from Binance."""
        _ensure_legacy_binance_enabled()
        return {
            "bids": [{"price": 49999.0 - i*0.5, "quantity": 1.0} for i in range(depth)],
            "asks": [{"price": 50001.0 + i*0.5, "quantity": 1.0} for i in range(depth)]
        }
    
    async def stream_ticks(self, symbol: str):
        """Stream ticks via WebSocket."""
        _ensure_legacy_binance_enabled()
        # Placeholder - would use websockets library
        while True:
            yield {"symbol": symbol, "price": 50000.0, "volume": 1.0}
            await asyncio.sleep(1)