"""
Token Refresh Scheduler - Background token refresh mechanism.

Automatically refreshes Dhan API tokens before expiry to ensure
uninterrupted trading operations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RefreshError(Exception):
    """Raised when token refresh fails."""
    pass


class TokenRefreshScheduler:
    """
    Background scheduler for automatic token refresh.
    
    Monitors token expiry and proactively refreshes tokens before they expire.
    Runs as an async background task that checks every 5 minutes.
    
    Example:
        >>> scheduler = TokenRefreshScheduler(auth_provider, http_client)
        >>> await scheduler.start()
        >>> # ... do trading ...
        >>> await scheduler.stop()
    """
    
    def __init__(
        self,
        auth_provider,
        http_client,
        check_interval: int = 300,  # 5 minutes
    ):
        """
        Initialize token refresh scheduler.
        
        Args:
            auth_provider: DhanAuthProvider instance for token management
            http_client: DhanHttpClient instance to update with new tokens
            check_interval: Seconds between expiry checks (default: 300)
        """
        self._auth_provider = auth_provider
        self._http_client = http_client
        self._check_interval = check_interval
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the background refresh scheduler."""
        if self._running:
            logger.debug("Token refresh scheduler already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())
        
        logger.info(
            f"Token refresh scheduler started (check interval: {self._check_interval}s)"
        )
    
    async def stop(self) -> None:
        """Stop the background refresh scheduler."""
        if not self._running:
            return
        
        self._running = False
        
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Token refresh scheduler stopped")
    
    async def _refresh_loop(self) -> None:
        """Main refresh loop - runs until stopped."""
        logger.debug("Token refresh loop started")
        
        while self._running:
            try:
                await self._refresh_if_needed()
            except Exception as e:
                logger.error(f"Error in token refresh loop: {e}")
            
            # Wait for next check
            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
        
        logger.debug("Token refresh loop exited")
    
    async def _refresh_if_needed(self) -> None:
        """
        Check if token needs refresh and refresh if necessary.
        
        Updates the HTTP client headers with the new token.
        Logs errors but doesn't raise them (scheduler should continue).
        """
        try:
            # Check if token is near expiry
            if not self._auth_provider.is_token_near_expiry():
                return
            
            logger.info("Token near expiry, refreshing...")
            
            # Get new token
            new_token = await self._auth_provider.ensure_valid_token()
            
            # Update HTTP client headers
            self._http_client._headers["access-token"] = new_token
            
            # Also update Authorization header if present
            if "Authorization" in self._http_client._headers:
                self._http_client._headers["Authorization"] = f"Bearer {new_token}"
            
            logger.info("Token refreshed successfully")
            
        except Exception as e:
            logger.error(f"Failed to refresh token: {e}")
            # Don't raise - scheduler should continue running
            raise RefreshError(f"Token refresh failed: {e}") from e
