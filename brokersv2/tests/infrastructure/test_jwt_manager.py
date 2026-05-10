"""Tests for JWT Token Manager."""

import asyncio
import pytest
from datetime import timedelta
from brokersv2.infrastructure.dhan_adapter.jwt_manager import (
    JWTManager,
    TokenRefreshError,
)


class MockDhanClient:
    """Mock DhanHttpClient for testing."""
    
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.refresh_count = 0
    
    async def refresh_token(self):
        self.refresh_count += 1
        if self.should_fail:
            raise ConnectionError("Token refresh failed")
        return {
            "access_token": f"token_{self.refresh_count}",
            "expires_in": 3600,
        }


@pytest.mark.asyncio
async def test_token_refresh_before_expiry():
    """Token refreshes automatically 60s before expiry."""
    client = MockDhanClient()
    jwt_mgr = JWTManager(client, refresh_buffer=60)
    
    # Set token expiring in 30 seconds (should trigger refresh)
    jwt_mgr.set_token("initial_token", expires_in=30)
    
    # Get token should trigger refresh
    token = await jwt_mgr.get_token()
    
    assert token == "token_1"
    assert client.refresh_count == 1
    assert jwt_mgr.has_valid_token


@pytest.mark.asyncio
async def test_concurrent_token_access():
    """Multiple concurrent requests use same token (no double refresh)."""
    client = MockDhanClient()
    jwt_mgr = JWTManager(client, refresh_buffer=60)
    
    # Set expired token
    jwt_mgr.set_token("expired_token", expires_in=0)
    
    # Concurrent token requests
    tokens = await asyncio.gather(
        jwt_mgr.get_token(),
        jwt_mgr.get_token(),
        jwt_mgr.get_token(),
    )
    
    # All should get same token
    assert tokens[0] == tokens[1] == tokens[2]
    # Only one refresh should occur
    assert client.refresh_count == 1


@pytest.mark.asyncio
async def test_refresh_retry_on_failure():
    """Token refresh retries on failure (max 3 attempts)."""
    client = MockDhanClient(should_fail=True)
    jwt_mgr = JWTManager(client, max_retries=3)
    
    # Set expired token
    jwt_mgr.set_token("expired_token", expires_in=0)
    
    # Should fail after 3 retries
    with pytest.raises(TokenRefreshError) as exc_info:
        await jwt_mgr.get_token()
    
    assert "3 attempts" in str(exc_info.value)
    assert client.refresh_count == 3
