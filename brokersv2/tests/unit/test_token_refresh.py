"""
Token Refresh Scheduler tests - Phase 2, Step 5 (TDD)

Tests for background token refresh mechanism.
Ensures tokens are automatically refreshed before expiry.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from brokersv2.infrastructure.dhan_adapter.token_refresh_scheduler import (
    TokenRefreshScheduler,
    RefreshError,
)


class TestSchedulerInitialization:
    """Test TokenRefreshScheduler initialization."""
    
    def test_create_scheduler(self):
        """Should create scheduler with auth provider and client."""
        auth_provider = MagicMock()
        http_client = MagicMock()
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client)
        
        assert scheduler._auth_provider == auth_provider
        assert scheduler._http_client == http_client
        assert scheduler._running is False
        assert scheduler._task is None
    
    def test_default_check_interval(self):
        """Should have default 5-minute check interval."""
        auth_provider = MagicMock()
        http_client = MagicMock()
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client)
        
        assert scheduler._check_interval == 300  # 5 minutes in seconds
    
    def test_custom_check_interval(self):
        """Should accept custom check interval."""
        auth_provider = MagicMock()
        http_client = MagicMock()
        
        scheduler = TokenRefreshScheduler(
            auth_provider, http_client, check_interval=60
        )
        
        assert scheduler._check_interval == 60


class TestSchedulerLifecycle:
    """Test scheduler start/stop lifecycle."""
    
    @pytest.mark.asyncio
    async def test_start_scheduler(self):
        """Should start background task."""
        auth_provider = MagicMock()
        http_client = MagicMock()
        scheduler = TokenRefreshScheduler(auth_provider, http_client, check_interval=0.1)
        
        await scheduler.start()
        
        assert scheduler._running is True
        assert scheduler._task is not None
        assert not scheduler._task.done()
        
        # Cleanup
        await scheduler.stop()
    
    @pytest.mark.asyncio
    async def test_stop_scheduler(self):
        """Should stop background task."""
        auth_provider = MagicMock()
        http_client = MagicMock()
        scheduler = TokenRefreshScheduler(auth_provider, http_client, check_interval=0.1)
        
        await scheduler.start()
        await scheduler.stop()
        
        assert scheduler._running is False
        assert scheduler._task.done()
    
    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        """Should handle multiple stop calls gracefully."""
        auth_provider = MagicMock()
        http_client = MagicMock()
        scheduler = TokenRefreshScheduler(auth_provider, http_client, check_interval=0.1)
        
        await scheduler.start()
        await scheduler.stop()
        await scheduler.stop()  # Should not raise
        
        assert scheduler._running is False
    
    @pytest.mark.asyncio
    async def test_start_already_running(self):
        """Should not start multiple tasks."""
        auth_provider = MagicMock()
        http_client = MagicMock()
        scheduler = TokenRefreshScheduler(auth_provider, http_client, check_interval=0.1)
        
        await scheduler.start()
        task1 = scheduler._task
        
        await scheduler.start()  # Should not create new task
        task2 = scheduler._task
        
        assert task1 is task2
        
        # Cleanup
        await scheduler.stop()


class TestRefreshLogic:
    """Test token refresh logic."""
    
    @pytest.mark.asyncio
    async def test_refresh_when_near_expiry(self):
        """Should refresh token when near expiry."""
        auth_provider = MagicMock()
        auth_provider.is_token_near_expiry.return_value = True
        auth_provider.ensure_valid_token = AsyncMock(return_value="new_token")
        
        http_client = MagicMock()
        http_client._headers = {"access-token": "old_token"}
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client)
        
        await scheduler._refresh_if_needed()
        
        auth_provider.ensure_valid_token.assert_called_once()
        assert http_client._headers["access-token"] == "new_token"
    
    @pytest.mark.asyncio
    async def test_skip_refresh_when_valid(self):
        """Should skip refresh when token is valid."""
        auth_provider = MagicMock()
        auth_provider.is_token_near_expiry.return_value = False
        auth_provider.ensure_valid_token = AsyncMock()
        
        http_client = MagicMock()
        http_client._headers = {"access-token": "valid_token"}
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client)
        
        await scheduler._refresh_if_needed()
        
        auth_provider.ensure_valid_token.assert_not_called()
        assert http_client._headers["access-token"] == "valid_token"
    
    @pytest.mark.asyncio
    async def test_refresh_failure_logged(self):
        """Should log error when refresh fails."""
        auth_provider = MagicMock()
        auth_provider.is_token_near_expiry.return_value = True
        auth_provider.ensure_valid_token = AsyncMock(side_effect=Exception("Network error"))
        
        http_client = MagicMock()
        http_client._headers = {"access-token": "old_token"}
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client)
        
        # Should raise RefreshError (logged internally)
        from brokersv2.infrastructure.dhan_adapter.token_refresh_scheduler import RefreshError
        with pytest.raises(RefreshError, match="Network error"):
            await scheduler._refresh_if_needed()
        
        # Token should remain unchanged
        assert http_client._headers["access-token"] == "old_token"
    
    @pytest.mark.asyncio
    async def test_refresh_updates_all_headers(self):
        """Should update all auth-related headers."""
        auth_provider = MagicMock()
        auth_provider.is_token_near_expiry.return_value = True
        auth_provider.ensure_valid_token = AsyncMock(return_value="new_token")
        
        http_client = MagicMock()
        http_client._headers = {
            "access-token": "old_token",
            "Authorization": "Bearer old_token",
            "other-header": "value",
        }
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client)
        
        await scheduler._refresh_if_needed()
        
        assert http_client._headers["access-token"] == "new_token"
        assert http_client._headers["Authorization"] == "Bearer new_token"
        assert http_client._headers["other-header"] == "value"  # Unchanged


class TestRefreshLoop:
    """Test background refresh loop."""
    
    @pytest.mark.asyncio
    async def test_loop_checks_periodically(self):
        """Should check for refresh at regular intervals."""
        auth_provider = MagicMock()
        auth_provider.is_token_near_expiry.return_value = False
        auth_provider.ensure_valid_token = AsyncMock()
        
        http_client = MagicMock()
        http_client._headers = {"access-token": "token"}
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client, check_interval=0.1)
        
        # Start scheduler
        await scheduler.start()
        await asyncio.sleep(0.35)  # Should check ~3 times
        
        await scheduler.stop()
        
        # Should have checked multiple times
        assert auth_provider.is_token_near_expiry.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_loop_stops_when_flag_cleared(self):
        """Should exit loop when _running is False."""
        auth_provider = MagicMock()
        auth_provider.is_token_near_expiry.return_value = False
        
        http_client = MagicMock()
        http_client._headers = {"access-token": "token"}
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client, check_interval=0.1)
        
        # Start and immediately stop
        scheduler._running = True
        loop_task = asyncio.create_task(scheduler._refresh_loop())
        
        await asyncio.sleep(0.05)
        scheduler._running = False
        
        await asyncio.sleep(0.15)
        
        # Loop should have exited
        assert loop_task.done()


class TestErrorHandling:
    """Test error handling in scheduler."""
    
    def test_refresh_error_message(self):
        """RefreshError should have descriptive message."""
        error = RefreshError("Token renewal failed")
        
        assert str(error) == "Token renewal failed"
    
    @pytest.mark.asyncio
    async def test_loop_continues_after_error(self):
        """Should continue loop even if one refresh fails."""
        auth_provider = MagicMock()
        # First check triggers refresh (which fails), then continues
        auth_provider.is_token_near_expiry.side_effect = [True, False, False]
        auth_provider.ensure_valid_token = AsyncMock(side_effect=Exception("Fail"))
        
        http_client = MagicMock()
        http_client._headers = {"access-token": "token"}
        
        scheduler = TokenRefreshScheduler(auth_provider, http_client, check_interval=0.1)
        
        # Start scheduler
        await scheduler.start()
        await asyncio.sleep(0.35)
        
        await scheduler.stop()
        
        # Should have continued checking after error
        assert auth_provider.is_token_near_expiry.call_count >= 2
