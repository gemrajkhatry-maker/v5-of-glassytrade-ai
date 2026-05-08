"""
Tests for Phase 1 & 2: Broker Gateway & OMS Advanced Features.

Tests:
- RetryManager with exponential backoff
- RequestDispatcher with circuit breaker
- SessionManager with JWT refresh
- IdempotencyManager for OMS
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from brokersv2.gateway.retry_manager import RetryManager, RetryConfig
from brokersv2.gateway.request_dispatcher import (
    CircuitBreakerOpenError,
    RequestDispatcher,
    RequestContext,
    RequestPriority,
)
from brokersv2.gateway.session_manager import (
    SessionError,
    SessionExpiredError,
    SessionManager,
    SessionNotFoundError,
    SessionRevokedError,
    SessionConfig,
    SessionState,
)
from brokersv2.oms.idempotency_manager import IdempotencyManager, IdempotencyStatus


# =============================================================================
# RetryManager Tests
# =============================================================================

class TestRetryManager:
    """Test retry manager with exponential backoff."""
    
    def test_config_default_values(self):
        """Test default config values."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.jitter_enabled is True
    
    def test_config_calculate_delay_exponential(self):
        """Test exponential backoff calculation."""
        config = RetryConfig(base_delay=1.0, jitter_enabled=False)
        
        delay0 = config.calculate_delay(0)  # 1 * 2^0 = 1
        delay1 = config.calculate_delay(1)  # 1 * 2^1 = 2
        delay2 = config.calculate_delay(2)  # 1 * 2^2 = 4
        
        assert delay0 == 1.0
        assert delay1 == 2.0
        assert delay2 == 4.0
    
    def test_config_calculate_delay_capped(self):
        """Test delay is capped at max_delay."""
        config = RetryConfig(base_delay=10.0, max_delay=30.0, jitter_enabled=False)
        
        delay5 = config.calculate_delay(5)  # 10 * 2^5 = 320, capped at 30
        
        assert delay5 == 30.0
    
    def test_should_retry_true(self):
        """Test retryable exception detection."""
        config = RetryConfig()
        assert config.should_retry(ConnectionError()) is True
        assert config.should_retry(TimeoutError()) is True
    
    def test_should_retry_false(self):
        """Test non-retryable exception detection."""
        config = RetryConfig()
        assert config.should_retry(ValueError()) is False
        assert config.should_retry(TypeError()) is False
    
    @pytest.mark.asyncio
    async def test_execute_success_first_try(self):
        """Test successful execution without retries."""
        manager = RetryManager()
        
        async def success_func():
            return "success"
        
        result = await manager.execute_with_retry(success_func)
        assert result == "success"
        assert manager.retry_count == 0
    
    @pytest.mark.asyncio
    async def test_execute_success_after_retries(self):
        """Test successful execution after retries."""
        manager = RetryManager(
            config=RetryConfig(max_retries=3, base_delay=0.01, jitter_enabled=False)
        )
        
        attempt = 0
        
        async def flaky_func():
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise ConnectionError("Temporary failure")
            return "success"
        
        result = await manager.execute_with_retry(flaky_func)
        assert result == "success"
        assert manager.retry_count == 2  # Succeeded on 3rd attempt
    
    @pytest.mark.asyncio
    async def test_execute_all_retries_exhausted(self):
        """Test failure after all retries exhausted."""
        manager = RetryManager(
            config=RetryConfig(max_retries=2, base_delay=0.01, jitter_enabled=False)
        )
        
        async def failing_func():
            raise ConnectionError("Persistent failure")
        
        with pytest.raises(ConnectionError, match="Persistent failure"):
            await manager.execute_with_retry(failing_func)
        
        assert manager.retry_count == 2  # Attempted 3 times (0, 1, 2)
        assert manager.total_retries == 2
    
    @pytest.mark.asyncio
    async def test_execute_non_retryable_exception(self):
        """Test immediate failure on non-retryable exception."""
        manager = RetryManager()
        
        async def bad_func():
            raise ValueError("Invalid input")
        
        with pytest.raises(ValueError, match="Invalid input"):
            await manager.execute_with_retry(bad_func)
        
        assert manager.retry_count == 0  # No retries attempted
    
    def test_execute_sync_success(self):
        """Test sync execution with retries."""
        manager = RetryManager(
            config=RetryConfig(max_retries=2, base_delay=0.01, jitter_enabled=False)
        )
        
        attempt = 0
        
        def flaky_func():
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise ConnectionError("Temporary")
            return "success"
        
        result = manager.execute_with_retry_sync(flaky_func)
        assert result == "success"
    
    def test_reset_stats(self):
        """Test stats reset."""
        manager = RetryManager()
        manager._retry_count = 5
        manager._total_retries = 10
        
        manager.reset_stats()
        
        assert manager.retry_count == 0
        assert manager.total_retries == 0
        assert manager.last_exception is None


# =============================================================================
# RequestDispatcher Tests
# =============================================================================

class TestRequestDispatcher:
    """Test request dispatcher."""
    
    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test successful request execution."""
        dispatcher = RequestDispatcher()
        
        async def fetch_data(**kwargs):
            return {"data": "test"}
        
        context = RequestContext(method="GET", endpoint="/test")
        result = await dispatcher.execute(context, fetch_data)
        
        assert result == {"data": "test"}
        assert dispatcher.metrics.successful_requests == 1
    
    @pytest.mark.asyncio
    async def test_execute_with_retry(self):
        """Test request with retry on failure."""
        retry_manager = RetryManager(
            config=RetryConfig(max_retries=2, base_delay=0.01, jitter_enabled=False)
        )
        dispatcher = RequestDispatcher(retry_manager=retry_manager)
        
        attempt = 0
        
        async def flaky_endpoint(**kwargs):
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise ConnectionError("Transient")
            return {"success": True}
        
        context = RequestContext(method="POST", endpoint="/order")
        result = await dispatcher.execute(context, flaky_endpoint)
        
        assert result == {"success": True}
        assert dispatcher.metrics.retried_requests == 1
    
    @pytest.mark.asyncio
    async def test_metrics_tracking(self):
        """Test metrics are tracked correctly."""
        dispatcher = RequestDispatcher(
            retry_manager=RetryManager(
                config=RetryConfig(max_retries=0)
            )
        )
        
        async def success_func(**kwargs):
            return "ok"
        
        async def fail_func(**kwargs):
            raise ValueError("Error")
        
        # Successful request
        ctx1 = RequestContext(method="GET", endpoint="/ok")
        await dispatcher.execute(ctx1, success_func)
        
        # Failed request
        ctx2 = RequestContext(method="POST", endpoint="/fail")
        with pytest.raises(ValueError):
            await dispatcher.execute(ctx2, fail_func)
        
        assert dispatcher.metrics.total_requests == 2
        assert dispatcher.metrics.successful_requests == 1
        assert dispatcher.metrics.failed_requests == 1
        assert dispatcher.metrics.success_rate == 50.0
    
    def test_get_status(self):
        """Test status reporting."""
        dispatcher = RequestDispatcher()
        status = dispatcher.get_status()
        
        assert "metrics" in status
        assert "circuit_breaker" in status
        assert status["circuit_breaker"] == "not_configured"


# =============================================================================
# SessionManager Tests
# =============================================================================

class TestSessionManager:
    """Test JWT session management."""
    
    @pytest.mark.asyncio
    async def test_create_session(self):
        """Test session creation."""
        manager = SessionManager()
        
        session = await manager.create_session(
            session_id="session_1",
            user_id="user_1",
            access_token="token_1",
            refresh_token="refresh_1",
        )
        
        assert session.user_id == "user_1"
        assert session.state == SessionState.ACTIVE
        assert session.access_token == "token_1"
        assert session.is_active is True
    
    @pytest.mark.asyncio
    async def test_get_valid_token(self):
        """Test getting valid token."""
        manager = SessionManager()
        
        await manager.create_session(
            session_id="s1",
            user_id="u1",
            access_token="valid_token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        
        token = await manager.get_valid_token("u1")
        assert token == "valid_token"
    
    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Test error on missing session."""
        manager = SessionManager()
        
        with pytest.raises(SessionNotFoundError):
            await manager.get_valid_token("nonexistent")
    
    @pytest.mark.asyncio
    async def test_session_revoked(self):
        """Test error on revoked session."""
        manager = SessionManager()
        
        await manager.create_session(
            session_id="s1",
            user_id="u1",
            access_token="token",
        )
        
        await manager.revoke_session("u1")
        
        with pytest.raises(SessionRevokedError):
            await manager.get_valid_token("u1")
    
    @pytest.mark.asyncio
    async def test_auto_refresh(self):
        """Test automatic token refresh."""
        refresh_called = False
        
        async def mock_refresher(user_id, refresh_token):
            nonlocal refresh_called
            refresh_called = True
            return {
                "access_token": "new_token",
                "refresh_token": "new_refresh",
            }
        
        manager = SessionManager(token_refresher=mock_refresher)
        
        # Create session that expires in 1 minute (needs refresh)
        await manager.create_session(
            session_id="s1",
            user_id="u1",
            access_token="old_token",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        
        # Get token (should trigger refresh)
        token = await manager.get_valid_token("u1")
        
        assert refresh_called is True
        assert token == "new_token"
    
    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self):
        """Test cleanup of expired sessions."""
        manager = SessionManager()
        
        # Active session
        await manager.create_session(
            session_id="s1",
            user_id="u1",
            access_token="token1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        
        # Expired session
        await manager.create_session(
            session_id="s2",
            user_id="u2",
            access_token="token2",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        
        cleaned = await manager.cleanup_expired_sessions()
        
        assert cleaned == 1
        assert len(manager.get_active_sessions()) == 1
    
    def test_get_status(self):
        """Test status reporting."""
        manager = SessionManager()
        status = manager.get_status()
        
        assert "total_sessions" in status
        assert "active_sessions" in status
        assert "config" in status


# =============================================================================
# IdempotencyManager Tests
# =============================================================================

class TestIdempotencyManager:
    """Test idempotency management."""
    
    def test_generate_idempotency_key(self):
        """Test key generation is deterministic."""
        manager = IdempotencyManager()
        
        key1 = manager.generate_idempotency_key(
            user_id="u1",
            symbol="RELIANCE",
            side="BUY",
            quantity=100,
            timestamp=1234567890.0,
        )
        
        key2 = manager.generate_idempotency_key(
            user_id="u1",
            symbol="RELIANCE",
            side="BUY",
            quantity=100,
            timestamp=1234567890.0,
        )
        
        assert key1 == key2
        assert len(key1) == 16  # First 16 chars of SHA256
    
    def test_detect_duplicate(self):
        """Test duplicate detection."""
        manager = IdempotencyManager()
        
        key = manager.generate_idempotency_key(
            user_id="u1",
            symbol="RELIANCE",
            side="BUY",
            quantity=100,
        )
        
        # First request - not duplicate
        manager.record_pending(key)
        assert manager.is_duplicate(key) is False
        
        # Complete request
        manager.record_completion(key, {"order_id": "123"})
        
        # Second request - duplicate
        assert manager.is_duplicate(key) is True
    
    def test_get_cached_response(self):
        """Test cached response retrieval."""
        manager = IdempotencyManager()
        
        key = "test_key"
        response = {"order_id": "123", "status": "filled"}
        
        manager.record_pending(key)
        manager.record_completion(key, response)
        
        cached = manager.get_cached_response(key)
        assert cached == response
    
    def test_record_failure(self):
        """Test failure recording."""
        manager = IdempotencyManager()
        
        key = "fail_key"
        manager.record_pending(key)
        manager.record_failure(key, "Connection timeout")
        
        record = manager.get_record(key)
        assert record.status == IdempotencyStatus.FAILED
        assert record.error == "Connection timeout"
    
    def test_cleanup_stale(self):
        """Test stale record cleanup."""
        manager = IdempotencyManager()
        
        # Create stale record (manipulate created_at)
        key1 = "stale_key"
        manager.record_pending(key1)
        manager._records[key1].created_at = time.time() - 7200  # 2 hours ago
        
        # Create fresh record
        key2 = "fresh_key"
        manager.record_pending(key2)
        
        cleaned = manager.cleanup_stale()
        
        assert cleaned == 1
        assert key1 not in manager._records
        assert key2 in manager._records
    
    def test_get_status(self):
        """Test status reporting."""
        manager = IdempotencyManager()
        
        manager.record_pending("key1")
        manager.record_completion("key1", {"id": "1"})
        
        manager.record_pending("key2")
        manager.record_failure("key2", "error")
        
        status = manager.get_status()
        
        assert status["total_records"] == 2
        assert status["completed"] == 1
        assert status["failed"] == 1


# =============================================================================
# Integration Tests
# =============================================================================

class TestPhase1Phase2Integration:
    """Integration tests for Phase 1 & 2 components."""
    
    @pytest.mark.asyncio
    async def test_dispatcher_with_retry_and_idempotency(self):
        """Test RequestDispatcher with IdempotencyManager."""
        retry_manager = RetryManager(
            config=RetryConfig(max_retries=2, base_delay=0.01, jitter_enabled=False)
        )
        dispatcher = RequestDispatcher(retry_manager=retry_manager)
        idempotency = IdempotencyManager()
        
        # Generate idempotency key
        key = idempotency.generate_idempotency_key(
            user_id="u1",
            symbol="RELIANCE",
            side="BUY",
            quantity=100,
        )
        
        # Check not duplicate
        assert idempotency.is_duplicate(key) is False
        
        # Record pending
        idempotency.record_pending(key)
        
        # Execute request
        async def submit_order(**kwargs):
            return {"order_id": "ORD-123", "status": "pending"}
        
        context = RequestContext(method="POST", endpoint="/order")
        result = await dispatcher.execute(context, submit_order)
        
        # Record completion
        idempotency.record_completion(key, result)
        
        # Verify
        assert idempotency.is_duplicate(key) is True
        cached = idempotency.get_cached_response(key)
        assert cached["order_id"] == "ORD-123"
