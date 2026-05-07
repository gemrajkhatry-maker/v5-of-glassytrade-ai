"""
Rate limiter implementation for DhanHQ v2 API limits.

DhanHQ v2 Rate Limits:
- Orders: 10/sec, 250/min, 1000/hr, 7000/day
- Quotes: 1/sec
- Historical: 5/sec (second-level data)
- Non-trading: 20/sec
- Option Chain: 1/3 sec
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional
from threading import Lock


@dataclass
class RateLimit:
    """Rate limit configuration."""
    requests_per_second: int = 10
    requests_per_minute: int = 600
    requests_per_hour: int = 3600
    requests_per_day: int = 10000


class TokenBucket:
    """
    Token bucket rate limiter.
    
    Supports both per-second and per-minute limits.
    """
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize token bucket.
        
        Args:
            capacity: Maximum tokens (burst size)
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate
        self.last_refill = time.monotonic()
        self._lock = Lock()
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
    
    def try_consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens.
        
        Returns True if successful, False if not enough tokens.
        """
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class RateLimiter:
    """
    Multi-bucket rate limiter for different API endpoints.
    """
    
    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = Lock()
        
        # Initialize DhanHQ v2 limits
        self._setup_dhan_limits()
    
    def _setup_dhan_limits(self) -> None:
        """Set up DhanHQ v2 rate limits."""
        # Orders: 10/sec, 250/min
        self._buckets["orders"] = TokenBucket(capacity=250, refill_rate=10.0)
        
        # Quotes: 1/sec
        self._buckets["quotes"] = TokenBucket(capacity=1, refill_rate=1.0)
        
        # Historical: 5/sec
        self._buckets["historical"] = TokenBucket(capacity=5, refill_rate=5.0)
        
        # Non-trading: 20/sec
        self._buckets["non_trading"] = TokenBucket(capacity=20, refill_rate=20.0)
        
        # Option chain: 1/3 sec ≈ 0.33/sec
        self._buckets["option_chain"] = TokenBucket(capacity=1, refill_rate=0.33)
        
        # Default: 10/sec
        self._buckets["default"] = TokenBucket(capacity=10, refill_rate=10.0)
    
    def register_bucket(self, name: str, bucket: TokenBucket) -> None:
        """Register a custom bucket."""
        with self._lock:
            self._buckets[name] = bucket
    
    def try_request(self, bucket: str = "default") -> bool:
        """
        Check if request is allowed for the given bucket.
        
        Returns True if request can proceed, False if rate limited.
        """
        bucket_obj = self._buckets.get(bucket, self._buckets["default"])
        return bucket_obj.try_consume()
    
    def wait_for_token(self, bucket: str = "default", timeout: float = 5.0) -> bool:
        """
        Wait for a token to become available.
        
        Returns True if token acquired, False if timeout.
        """
        start = time.monotonic()
        bucket_obj = self._buckets.get(bucket, self._buckets["default"])
        
        while time.monotonic() - start < timeout:
            if bucket_obj.try_consume():
                return True
            time.sleep(0.01)
        
        return False
    
    def get_wait_time(self, bucket: str = "default") -> float:
        """Get estimated wait time in seconds."""
        bucket_obj = self._buckets.get(bucket, self._buckets["default"])
        with bucket_obj._lock:
            bucket_obj._refill()
            if bucket_obj.tokens >= 1:
                return 0.0
            return (1 - bucket_obj.tokens) / bucket_obj.refill_rate


class RequestScheduler:
    """
    Priority-aware request scheduler with rate limiting.
    """
    
    def __init__(self, rate_limiter: RateLimiter):
        self._rate_limiter = rate_limiter
        self._pending: list = []
        self._lock = Lock()
    
    def submit(
        self,
        request_id: str,
        bucket: str,
        priority: int = 0,
        callback=None,
    ) -> bool:
        """
        Submit request for scheduling.
        
        Returns True if request can proceed immediately.
        """
        if self._rate_limiter.try_request(bucket):
            if callback:
                callback()
            return True
        
        with self._lock:
            self._pending.append({
                "id": request_id,
                "bucket": bucket,
                "priority": priority,
                "callback": callback,
            })
        
        return False
    
    def process_pending(self) -> int:
        """Process pending requests. Returns count processed."""
        count = 0
        with self._lock:
            pending = sorted(self._pending, key=lambda x: -x["priority"])
            self._pending.clear()
        
        for req in pending:
            if self._rate_limiter.try_request(req["bucket"]):
                if req["callback"]:
                    req["callback"]()
                count += 1
        
        return count