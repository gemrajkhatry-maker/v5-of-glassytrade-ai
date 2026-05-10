"""
Tests for RingBuffer and ObjectPool.
"""

import pytest
from brokersv2.core.ring_buffer import RingBuffer
from brokersv2.core.object_pool import ObjectPool


# ===========================================================================
# RingBuffer Tests
# ===========================================================================

class TestRingBufferBasic:
    """Test basic ring buffer operations."""
    
    def test_put_and_get(self):
        """Should store and retrieve items."""
        buffer = RingBuffer(capacity=10)
        
        buffer.put("item1")
        buffer.put("item2")
        
        assert buffer.get() == "item1"
        assert buffer.get() == "item2"
    
    def test_get_empty_returns_none(self):
        """Should return None when buffer is empty."""
        buffer = RingBuffer(capacity=10)
        
        assert buffer.get() is None
    
    def test_fifo_order(self):
        """Should maintain FIFO order."""
        buffer = RingBuffer(capacity=10)
        
        for i in range(5):
            buffer.put(i)
        
        for i in range(5):
            assert buffer.get() == i
    
    def test_len(self):
        """Should track size correctly."""
        buffer = RingBuffer(capacity=10)
        
        assert len(buffer) == 0
        
        buffer.put("item")
        assert len(buffer) == 1
        
        buffer.get()
        assert len(buffer) == 0


class TestRingBufferCapacity:
    """Test ring buffer capacity management."""
    
    def test_capacity_limit(self):
        """Should respect capacity limit."""
        buffer = RingBuffer(capacity=3)
        
        assert buffer.put("item1") is True
        assert buffer.put("item2") is True
        assert buffer.put("item3") is True
        assert buffer.put("item4") is False  # Should drop
    
    def test_drop_tracking(self):
        """Should track dropped items."""
        buffer = RingBuffer(capacity=2)
        
        buffer.put("item1")
        buffer.put("item2")
        buffer.put("item3")  # Drop
        buffer.put("item4")  # Drop
        
        assert buffer.dropped_count == 2
    
    def test_drop_rate(self):
        """Should calculate drop rate."""
        buffer = RingBuffer(capacity=2)
        
        buffer.put("item1")
        buffer.put("item2")
        buffer.put("item3")  # Drop
        
        # 1 dropped out of 3 total attempted (2 in buffer + 1 dropped)
        assert buffer.drop_rate == pytest.approx(0.333, rel=0.01)
    
    def test_is_full(self):
        """Should detect full buffer."""
        buffer = RingBuffer(capacity=2)
        
        assert buffer.is_full is False
        
        buffer.put("item1")
        buffer.put("item2")
        
        assert buffer.is_full is True
    
    def test_is_empty(self):
        """Should detect empty buffer."""
        buffer = RingBuffer(capacity=10)
        
        assert buffer.is_empty is True
        
        buffer.put("item")
        assert buffer.is_empty is False


class TestRingBufferCircular:
    """Test circular behavior."""
    
    def test_circular_overwrite(self):
        """Should wrap around after reaching capacity."""
        buffer = RingBuffer(capacity=3)
        
        buffer.put("a")
        buffer.put("b")
        buffer.put("c")
        
        # Get one item
        assert buffer.get() == "a"
        
        # Put new item - should go to position 0
        buffer.put("d")
        
        assert buffer.get() == "b"
        assert buffer.get() == "c"
        assert buffer.get() == "d"
    
    def test_clear(self):
        """Should clear all items."""
        buffer = RingBuffer(capacity=10)
        
        buffer.put("item1")
        buffer.put("item2")
        buffer.clear()
        
        assert buffer.size == 0
        assert buffer.get() is None
    
    def test_peek(self):
        """Should peek without removing."""
        buffer = RingBuffer(capacity=10)
        
        buffer.put("item")
        
        assert buffer.peek() == "item"
        assert buffer.size == 1  # Not removed
    
    def test_peek_empty(self):
        """Should return None when peeking empty buffer."""
        buffer = RingBuffer(capacity=10)
        
        assert buffer.peek() is None


class TestRingBufferEdgeCases:
    """Test edge cases."""
    
    def test_invalid_capacity(self):
        """Should reject invalid capacity."""
        with pytest.raises(ValueError):
            RingBuffer(capacity=0)
        
        with pytest.raises(ValueError):
            RingBuffer(capacity=-1)
    
    def test_repr(self):
        """Should have informative repr."""
        buffer = RingBuffer(capacity=100)
        
        repr_str = repr(buffer)
        assert "RingBuffer" in repr_str
        assert "capacity=100" in repr_str


# ===========================================================================
# ObjectPool Tests
# ===========================================================================

class TestObjectPoolBasic:
    """Test basic object pool operations."""
    
    def test_acquire_and_release(self):
        """Should acquire and release objects."""
        pool = ObjectPool(factory=lambda: {"value": 0}, pool_size=10)
        
        obj = pool.acquire()
        obj["value"] = 42
        
        pool.release(obj)
        
        assert pool.active_count == 0
        assert pool.pool_size == 10
    
    def test_pre_allocation(self):
        """Should pre-allocate objects."""
        pool = ObjectPool(factory=lambda: object(), pool_size=100)
        
        assert pool.pool_size == 100
        assert pool.active_count == 0
    
    def test_acquire_reduces_pool_size(self):
        """Acquire should reduce available pool size."""
        pool = ObjectPool(factory=lambda: object(), pool_size=5)
        
        obj = pool.acquire()
        
        assert pool.pool_size == 4
        assert pool.active_count == 1
    
    def test_release_increases_pool_size(self):
        """Release should increase available pool size."""
        pool = ObjectPool(factory=lambda: object(), pool_size=5)
        
        obj = pool.acquire()
        pool.release(obj)
        
        assert pool.pool_size == 5
        assert pool.active_count == 0


class TestObjectPoolExhaustion:
    """Test pool exhaustion behavior."""
    
    def test_creates_new_when_exhausted(self):
        """Should create new object when pool is exhausted."""
        pool = ObjectPool(factory=lambda: {"id": 0}, pool_size=2)
        
        obj1 = pool.acquire()
        obj2 = pool.acquire()
        obj3 = pool.acquire()  # Should create new
        
        assert pool.pool_size == 0
        assert pool.active_count == 3
    
    def test_total_created(self):
        """Should track total created objects."""
        pool = ObjectPool(factory=lambda: object(), pool_size=5)
        
        # Acquire 5 objects (from pool)
        for _ in range(5):
            pool.acquire()
        
        # All from pre-allocated pool, so total_created = 5
        assert pool.total_created == 5
        assert pool.active_count == 5


class TestObjectPoolObjectReuse:
    """Test object reuse behavior."""
    
    def test_reuses_released_object(self):
        """Should reuse released objects."""
        objects_seen = []
        
        def factory():
            obj = {"created": True}
            objects_seen.append(id(obj))
            return obj
        
        pool = ObjectPool(factory=factory, pool_size=2)
        
        # Acquire 2 objects
        obj1 = pool.acquire()
        obj2 = pool.acquire()
        
        # Release and reacquire
        pool.release(obj1)
        obj3 = pool.acquire()
        
        # obj3 should be the same object as obj1
        assert id(obj3) == id(obj1)
    
    def test_tracks_active_by_id(self):
        """Should track active objects by id."""
        pool = ObjectPool(factory=lambda: object(), pool_size=5)
        
        obj1 = pool.acquire()
        obj2 = pool.acquire()
        
        assert pool.active_count == 2
        
        pool.release(obj1)
        assert pool.active_count == 1


class TestObjectPoolEdgeCases:
    """Test edge cases."""
    
    def test_invalid_pool_size(self):
        """Should reject invalid pool size."""
        with pytest.raises(ValueError):
            ObjectPool(factory=lambda: object(), pool_size=0)
        
        with pytest.raises(ValueError):
            ObjectPool(factory=lambda: object(), pool_size=-1)
    
    def test_repr(self):
        """Should have informative repr."""
        pool = ObjectPool(factory=lambda: object(), pool_size=100)
        
        repr_str = repr(pool)
        assert "ObjectPool" in repr_str
        assert "available=100" in repr_str
    
    def test_len(self):
        """Should support len()."""
        pool = ObjectPool(factory=lambda: object(), pool_size=10)
        
        assert len(pool) == 10
        
        pool.acquire()
        assert len(pool) == 9
