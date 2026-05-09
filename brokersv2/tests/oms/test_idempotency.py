"""Tests for Idempotency Protection."""

import asyncio
import pytest
from datetime import timedelta
from brokersv2.oms.idempotency import (
    IdempotencyKey,
    IdempotencyManager,
    DuplicateOrderError,
)


@pytest.mark.asyncio
async def test_unique_orders_allowed():
    """Different order params generate unique keys and are allowed."""
    manager = IdempotencyManager(ttl=timedelta(minutes=5))
    
    key1 = IdempotencyKey.generate("NIFTY", "BUY", 100, price=24000)
    key2 = IdempotencyKey.generate("NIFTY", "SELL", 100, price=24000)
    key3 = IdempotencyKey.generate("BANKNIFTY", "BUY", 100, price=24000)
    
    assert await manager.check_and_record(key1) is True
    assert await manager.check_and_record(key2) is True
    assert await manager.check_and_record(key3) is True
    assert await manager.pending_count == 3


@pytest.mark.asyncio
async def test_duplicate_order_blocked():
    """Same order params within TTL are blocked."""
    manager = IdempotencyManager(ttl=timedelta(minutes=5))
    
    key = IdempotencyKey.generate("NIFTY", "BUY", 100, price=24000)
    
    # First submission allowed
    assert await manager.check_and_record(key) is True
    
    # Duplicate blocked
    assert await manager.check_and_record(key) is False
    assert await manager.check_and_record(key) is False
    
    assert await manager.pending_count == 1


@pytest.mark.asyncio
async def test_expired_key_allows_resubmission():
    """After TTL expires, same order params allowed again."""
    # Use very short TTL for testing
    manager = IdempotencyManager(ttl=timedelta(milliseconds=100))
    
    key = IdempotencyKey.generate("NIFTY", "BUY", 100, price=24000)
    
    # First submission
    assert await manager.check_and_record(key) is True
    
    # Wait for expiry
    await asyncio.sleep(0.15)
    
    # Should be allowed again
    assert await manager.check_and_record(key) is True
    assert await manager.pending_count == 1  # Old key cleaned up, new one added


@pytest.mark.asyncio
async def test_concurrent_duplicate_handling():
    """Race condition: concurrent duplicate checks handled safely."""
    manager = IdempotencyManager(ttl=timedelta(minutes=5))
    
    key = IdempotencyKey.generate("NIFTY", "BUY", 100, price=24000)
    
    # Simulate concurrent submissions
    results = await asyncio.gather(
        manager.check_and_record(key),
        manager.check_and_record(key),
        manager.check_and_record(key),
    )
    
    # Only one should succeed
    assert results.count(True) == 1
    assert results.count(False) == 2
    assert await manager.pending_count == 1


@pytest.mark.asyncio
async def test_concurrent_pending_count_access():
    """Concurrent pending_count access is thread-safe."""
    manager = IdempotencyManager(ttl=timedelta(minutes=5))
    
    # Add some keys
    for i in range(10):
        await manager.check_and_record(f"key-{i}")
    
    # Access concurrently
    counts = await asyncio.gather(*[
        manager.pending_count for _ in range(100)
    ])
    
    # All should return 10
    assert all(count == 10 for count in counts)


@pytest.mark.asyncio
async def test_key_collision_probability():
    """Test that different params within same minute generate unique keys."""
    manager = IdempotencyManager(ttl=timedelta(minutes=5))
    
    # Generate keys with different params within same minute
    # Since timestamp is at minute granularity, we test symbol/side/qty/price uniqueness
    keys = set()
    unique_combos = [
        (f"SYM{i}", "BUY" if i % 2 == 0 else "SELL", (i % 100) + 1, 100.0 + (i % 50))
        for i in range(100)
    ]
    
    for symbol, side, qty, price in unique_combos:
        key = IdempotencyKey.generate(symbol, side, qty, price=price)
        is_new = await manager.check_and_record(key)
        if is_new:
            keys.add(key)
    
    # All 100 unique combinations should generate unique keys
    assert len(keys) == 100


@pytest.mark.asyncio
async def test_cleanup_expired_returns_count():
    """Cleanup expired returns count of removed keys."""
    manager = IdempotencyManager(ttl=timedelta(milliseconds=100))
    
    # Add keys
    for i in range(5):
        await manager.check_and_record(f"key-{i}")
    
    assert await manager.pending_count == 5
    
    # Wait for expiry
    await asyncio.sleep(0.15)
    
    # Cleanup should return count
    removed = await manager.cleanup_expired()
    assert removed == 5
    assert await manager.pending_count == 0


@pytest.mark.asyncio
async def test_concurrent_cleanup_and_check():
    """Concurrent cleanup and check operations are safe."""
    manager = IdempotencyManager(ttl=timedelta(milliseconds=200))
    
    # Add keys
    for i in range(20):
        await manager.check_and_record(f"key-{i}")
    
    async def check_operation(key_suffix):
        key = f"new-key-{key_suffix}"
        return await manager.check_and_record(key)
    
    async def cleanup_operation():
        return await manager.cleanup_expired()
    
    # Run concurrent operations
    results = await asyncio.gather(
        *[check_operation(i) for i in range(50)],
        *[cleanup_operation() for _ in range(10)],
    )
    
    # All operations should complete without error
    # Both check_and_record (bool) and cleanup_expired (int) return values
    assert len(results) == 60  # 50 checks + 10 cleanups
    assert all(isinstance(r, (bool, int)) for r in results)
