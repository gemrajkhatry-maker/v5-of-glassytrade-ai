"""
Object Pool - Reduces GC pressure by reusing frequently allocated objects.

For Tick, Candle, and other hot-path objects.
"""

from __future__ import annotations

from typing import Any, Callable, List, Set


class ObjectPool:
    """
    Object pool for frequently allocated types.
    
    Features:
    - Pre-allocated object pool
    - Acquire/release pattern
    - Reduces GC pressure
    - Thread-safe for single-threaded async context
    
    Usage:
        pool = ObjectPool(lambda: Tick(...), pool_size=1000)
        tick = pool.acquire()
        tick.price = 100.0
        pool.release(tick)
    """
    
    def __init__(self, factory: Callable[[], Any], pool_size: int = 1000):
        """
        Initialize object pool.
        
        Args:
            factory: Callable that creates new instances
            pool_size: Number of objects to pre-allocate
        """
        if pool_size <= 0:
            raise ValueError("Pool size must be positive")
        
        self._factory = factory
        self._pool: List[Any] = []
        self._active: Set[int] = set()  # Track by id()
        
        # Pre-allocate
        for _ in range(pool_size):
            self._pool.append(factory())
    
    def acquire(self) -> Any:
        """
        Get object from pool.
        
        Returns:
            Object instance (new or recycled)
        """
        if self._pool:
            obj = self._pool.pop()
        else:
            # Pool exhausted, create new
            obj = self._factory()
        
        self._active.add(id(obj))
        return obj
    
    def release(self, obj: Any):
        """
        Return object to pool.
        
        Args:
            obj: Object to return
        """
        obj_id = id(obj)
        if obj_id in self._active:
            self._active.remove(obj_id)
            self._pool.append(obj)
    
    @property
    def pool_size(self) -> int:
        """Get number of available objects in pool."""
        return len(self._pool)
    
    @property
    def active_count(self) -> int:
        """Get number of active (acquired) objects."""
        return len(self._active)
    
    @property
    def total_created(self) -> int:
        """Get total number of objects created (pool + active)."""
        return self.pool_size + self.active_count
    
    def __len__(self) -> int:
        """Return number of available objects."""
        return len(self._pool)
    
    def __repr__(self) -> str:
        return (
            f"ObjectPool(available={self.pool_size}, "
            f"active={self.active_count}, "
            f"total={self.total_created})"
        )
