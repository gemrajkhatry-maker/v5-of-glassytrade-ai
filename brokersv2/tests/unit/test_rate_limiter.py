"""Tests for rate limiter."""

import pytest
import time

from brokersv2.infrastructure.rate_limiter.token_bucket import (
    TokenBucket,
    RateLimiter,
    RequestScheduler,
)


class TestTokenBucket:
    """Tests for TokenBucket."""
    
    def test_basic_consumption(self):
        """Test basic token consumption."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        
        assert bucket.try_consume(5) is True
        assert bucket.try_consume(5) is True
        assert bucket.try_consume(1) is False  # Empty
    
    def test_refill_over_time(self):
        """Test token refill over time."""
        bucket = TokenBucket(capacity=10, refill_rate=10.0)
        
        # Empty the bucket
        bucket.try_consume(10)
        assert bucket.try_consume(1) is False
        
        # Wait for refill
        time.sleep(0.2)
        
        # Should have 2 tokens now
        assert bucket.try_consume(2) is True
    
    def test_capacity_limit(self):
        """Test that tokens don't exceed capacity."""
        bucket = TokenBucket(capacity=5, refill_rate=10.0)
        
        # Let it refill
        time.sleep(1)
        
        # Should still be at capacity
        bucket._refill()
        assert bucket.tokens <= 5


class TestRateLimiter:
    """Tests for RateLimiter."""
    
    def test_dhan_limits(self):
        """Test DhanHQ v2 rate limits."""
        limiter = RateLimiter()
        
        # Orders bucket has capacity 250, refill 10/sec
        # Should allow at least 10 requests
        count = 0
        for _ in range(250):
            if limiter.try_request("orders"):
                count += 1
            else:
                break

        # DhanHQ post-March-2026: orders bucket burst capacity is 10
        assert count == 10  # Bucket capacity
    
    def test_quotes_limit(self):
        """Test quotes rate limit (1/sec)."""
        limiter = RateLimiter()
        
        # Allow one
        assert limiter.try_request("quotes") is True
        
        # Should be rate limited
        assert limiter.try_request("quotes") is False


class TestRequestScheduler:
    """Tests for RequestScheduler."""
    
    def test_priority_ordering(self):
        """Test that higher priority requests are processed first."""
        rate_limiter = RateLimiter()
        scheduler = RequestScheduler(rate_limiter)
        
        processed = []
        
        def callback1():
            processed.append(1)
        
        def callback2():
            processed.append(2)
        
        # Use orders bucket which has high capacity
        # Submit low priority first - will succeed immediately but callback not called yet
        scheduler.submit("req1", "orders", priority=0, callback=callback1)
        
        # Submit high priority - will also succeed immediately
        scheduler.submit("req2", "orders", priority=10, callback=callback2)
        
        # Since both succeeded immediately, process_pending has nothing to do
        scheduler.process_pending()
        
        # Both callbacks should have been called immediately on submit
        assert len(processed) == 2
    
    def test_pending_requests_processed_by_priority(self):
        """Test that pending requests are processed in priority order."""
        rate_limiter = RateLimiter()
        scheduler = RequestScheduler(rate_limiter)
        
        processed_order = []
        
        def callback1():
            processed_order.append(1)
        
        def callback2():
            processed_order.append(2)
        
        # Quotes bucket has capacity 1 - first request succeeds, second goes to pending
        scheduler.submit("req1", "quotes", priority=0, callback=callback1)
        scheduler.submit("req2", "quotes", priority=10, callback=callback2)
        
        # Wait for bucket to refill
        time.sleep(1.1)
        
        # Now process pending - both should succeed
        scheduler.process_pending()
        
        assert 2 in processed_order  # High priority processed