"""
Lightweight token bucket rate limiter for single-user app.

Designed for OpenChart provider which has no guaranteed rate limits.
NOT a distributed system - optimized for desktop trading platform.
"""

from __future__ import annotations

import asyncio
import time
import random
import logging

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """
    Simple token bucket rate limiter for single-user app.
    
    Features:
    - Token refill based on elapsed time
    - Burst allowance up to configured limit
    - Cooldown period after repeated failures
    - Randomized jitter to prevent thundering herd
    
    Usage:
        limiter = TokenBucketRateLimiter(rate=2.0, burst=5)
        await limiter.acquire()  # Waits for token
        # ... make request ...
        limiter.record_success()
    """
    
    def __init__(
        self,
        rate: float = 2.0,  # requests per second
        burst: int = 5,     # max burst size
        cooldown_after: int = 3,  # failures before cooldown
        cooldown_duration: float = 5.0,  # cooldown in seconds
        jitter_min: float = 0.05,  # min jitter in seconds
        jitter_max: float = 0.15,  # max jitter in seconds
    ):
        """
        Initialize rate limiter.
        
        Args:
            rate: Token refill rate (requests per second)
            burst: Maximum burst size (initial tokens)
            cooldown_after: Number of failures before triggering cooldown
            cooldown_duration: How long to cooldown after failures
            jitter_min: Minimum jitter to add after acquiring token
            jitter_max: Maximum jitter to add after acquiring token
        """
        if rate <= 0:
            raise ValueError("Rate must be positive")
        if burst <= 0:
            raise ValueError("Burst size must be positive")
        if cooldown_after <= 0:
            raise ValueError("Cooldown threshold must be positive")
        
        self._rate = rate
        self._burst = burst
        self._cooldown_after = cooldown_after
        self._cooldown_duration = cooldown_duration
        self._jitter_min = jitter_min
        self._jitter_max = jitter_max
        
        # State
        self._tokens = float(burst)
        self._last_refill = time.time()
        self._failure_count = 0
        self._cooldown_until = 0.0
        
        # Metrics
        self._total_acquires = 0
        self._total_waits = 0
        self._total_cooldowns = 0
    
    async def acquire(self):
        """
        Wait until a token is available.
        
        This method blocks until:
        1. Not in cooldown period
        2. At least one token available
        3. Jitter delay completed
        """
        self._total_acquires += 1
        
        while True:
            # Check if in cooldown
            if self._is_in_cooldown():
                self._total_cooldowns += 1
                wait_time = min(0.5, self._cooldown_until - time.time())
                if wait_time > 0:
                    logger.debug(f"Rate limiter in cooldown, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                continue
            
            # Refill tokens
            self._refill()
            
            # Check if token available
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                
                # Add jitter to prevent request clustering
                jitter = random.uniform(self._jitter_min, self._jitter_max)
                if jitter > 0:
                    self._total_waits += 1
                    await asyncio.sleep(jitter)
                
                return
    
    def record_success(self):
        """Record successful request (resets failure count)."""
        self._failure_count = 0
        logger.debug("Rate limiter: success recorded, failure count reset")
    
    def record_failure(self):
        """
        Record failed request.
        
        Triggers cooldown if failure count exceeds threshold.
        """
        self._failure_count += 1
        logger.warning(
            f"Rate limiter: failure recorded (count={self._failure_count})"
        )
        
        if self._failure_count >= self._cooldown_after:
            self._cooldown_until = time.time() + self._cooldown_duration
            logger.warning(
                f"Rate limiter: entering cooldown for {self._cooldown_duration}s "
                f"after {self._failure_count} failures"
            )
    
    @property
    def available_tokens(self) -> float:
        """Get current number of available tokens."""
        self._refill()
        return self._tokens
    
    @property
    def is_in_cooldown(self) -> bool:
        """Check if currently in cooldown period."""
        return self._is_in_cooldown()
    
    @property
    def metrics(self) -> dict:
        """Get rate limiter metrics."""
        return {
            "total_acquires": self._total_acquires,
            "total_waits": self._total_waits,
            "total_cooldowns": self._total_cooldowns,
            "current_tokens": self.available_tokens,
            "failure_count": self._failure_count,
            "in_cooldown": self.is_in_cooldown,
        }
    
    def reset(self):
        """Reset rate limiter state."""
        self._tokens = float(self._burst)
        self._last_refill = time.time()
        self._failure_count = 0
        self._cooldown_until = 0.0
        logger.info("Rate limiter reset")
    
    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_refill
        
        if elapsed > 0:
            new_tokens = elapsed * self._rate
            old_tokens = self._tokens
            self._tokens = min(self._burst, self._tokens + new_tokens)
            self._last_refill = now
            
            if new_tokens > 0.1:  # Log only meaningful refills
                logger.debug(
                    f"Rate limiter: refilled {new_tokens:.2f} tokens "
                    f"({old_tokens:.2f} → {self._tokens:.2f})"
                )
    
    def _is_in_cooldown(self) -> bool:
        """Check if in cooldown period."""
        return time.time() < self._cooldown_until
    
    def __repr__(self) -> str:
        return (
            f"<TokenBucketRateLimiter rate={self._rate}/s "
            f"burst={self._burst} tokens={self.available_tokens:.1f}>"
        )
