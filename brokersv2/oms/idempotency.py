"""Idempotency Protection - Prevent duplicate order submissions."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional


class IdempotencyError(Exception):
    """Raised when idempotency check fails."""
    pass


class DuplicateOrderError(IdempotencyError):
    """Raised when duplicate order is detected."""
    
    def __init__(self, key: str):
        super().__init__(f"Duplicate order detected with key: {key}")
        self.key = key


class IdempotencyKey:
    """Generate deterministic idempotency keys from order parameters."""
    
    @staticmethod
    def generate(
        symbol: str,
        side: str,
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "MARKET",
    ) -> str:
        """
        Generate deterministic idempotency key from order params.
        
        Uses minute granularity for timestamp to allow retries within same minute.
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Order quantity
            price: Limit price (None for market orders)
            order_type: MARKET, LIMIT, STOP, etc.
            
        Returns:
            Deterministic hash string
        """
        # Use minute granularity (same minute = same key)
        now = datetime.now(timezone.utc)
        timestamp_minute = now.replace(second=0, microsecond=0)
        
        # Create canonical string
        key_parts = [
            symbol.upper(),
            side.upper(),
            str(quantity),
            str(price) if price is not None else "None",
            order_type.upper(),
            timestamp_minute.isoformat(),
        ]
        
        key_string = "|".join(key_parts)
        
        # Generate hash
        return hashlib.sha256(key_string.encode()).hexdigest()[:16]


class IdempotencyManager:
    """
    Manages idempotency checking for order submissions.
    
    Features:
    - Duplicate detection within TTL window
    - Thread-safe with async lock
    - Automatic cleanup of expired keys
    - Comprehensive tracking
    
    Usage:
        idempotency = IdempotencyManager(ttl=timedelta(minutes=5))
        
        key = IdempotencyKey.generate("NIFTY", "BUY", 100, price=24000)
        
        if await idempotency.check_and_record(key):
            # Safe to submit order
            await place_order()
        else:
            # Duplicate detected!
            raise DuplicateOrderError(key)
    """
    
    def __init__(self, ttl: timedelta = timedelta(minutes=5)):
        """
        Initialize idempotency manager.
        
        Args:
            ttl: Time-to-live for idempotency keys
        """
        self._pending: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl
    
    async def check_and_record(self, key: str) -> bool:
        """
        Check if order is duplicate and record if new.
        
        Args:
            key: Idempotency key
            
        Returns:
            True if new (safe to proceed), False if duplicate
        """
        async with self._lock:
            self._cleanup_expired()
            
            if key in self._pending:
                return False  # Duplicate!
            
            # Record new key
            self._pending[key] = datetime.now(timezone.utc)
            return True
    
    async def is_duplicate(self, key: str) -> bool:
        """
        Check if key is duplicate without recording.
        
        Args:
            key: Idempotency key
            
        Returns:
            True if duplicate, False if new
        """
        async with self._lock:
            self._cleanup_expired()
            return key in self._pending
    
    def _cleanup_expired(self) -> int:
        """Remove expired keys (must be called with lock held).
        
        Returns:
            Number of expired keys removed
        """
        now = datetime.now(timezone.utc)
        cutoff = now - self._ttl
        
        # Remove expired keys
        expired_keys = [
            key for key, timestamp in self._pending.items()
            if timestamp < cutoff
        ]
        
        for key in expired_keys:
            del self._pending[key]
        
        return len(expired_keys)
    
    async def cleanup_expired(self) -> int:
        """Public cleanup method (thread-safe).
        
        Returns:
            Number of expired keys removed
        """
        async with self._lock:
            return self._cleanup_expired()
    
    @property
    async def pending_count(self) -> int:
        """Get count of pending idempotency keys (thread-safe)."""
        async with self._lock:
            self._cleanup_expired()
            return len(self._pending)
    
    async def clear(self) -> None:
        """Clear all pending keys."""
        async with self._lock:
            self._pending.clear()
