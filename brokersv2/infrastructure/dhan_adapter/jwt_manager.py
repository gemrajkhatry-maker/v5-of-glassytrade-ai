"""JWT Token Manager - Automatic token refresh with storm prevention."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class TokenRefreshError(Exception):
    """Raised when token refresh fails after retries."""
    pass


class JWTManager:
    """
    Manages JWT token lifecycle with automatic refresh.
    
    Features:
    - Auto-refresh before expiry (configurable buffer)
    - Storm prevention (concurrent requests share refresh)
    - Retry logic with configurable attempts
    - Token validity checking
    """
    
    def __init__(
        self,
        client,
        refresh_buffer: int = 60,
        max_retries: int = 3,
    ):
        """
        Initialize JWT manager.
        
        Args:
            client: HTTP client with refresh_token() method
            refresh_buffer: Seconds before expiry to trigger refresh
            max_retries: Maximum retry attempts on failure
        """
        self._client = client
        self._refresh_buffer = refresh_buffer
        self._max_retries = max_retries
        
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._refresh_lock = asyncio.Lock()
    
    @property
    def has_valid_token(self) -> bool:
        """Check if token is valid and not expiring soon."""
        if self._token is None or self._expires_at is None:
            return False
        
        # Check if expiring within buffer
        expiry_threshold = datetime.now(timezone.utc) + timedelta(
            seconds=self._refresh_buffer
        )
        return self._expires_at > expiry_threshold
    
    def set_token(self, token: str, expires_in: int) -> None:
        """
        Set token manually.
        
        Args:
            token: Access token string
            expires_in: Seconds until expiry
        """
        self._token = token
        self._expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=expires_in
        )
        logger.info(f"Token set, expires in {expires_in}s")
    
    async def get_token(self) -> str:
        """
        Get valid token, refreshing if necessary.
        
        Returns:
            Valid access token string
            
        Raises:
            TokenRefreshError: If refresh fails after max retries
        """
        # If token is valid, return it
        if self.has_valid_token:
            return self._token
        
        # Need to refresh - use lock to prevent storms
        async with self._refresh_lock:
            # Double-check after acquiring lock
            if self.has_valid_token:
                return self._token
            
            # Attempt refresh with retries
            for attempt in range(1, self._max_retries + 1):
                try:
                    logger.info(f"Refreshing token (attempt {attempt}/{self._max_retries})")
                    response = await self._client.refresh_token()
                    
                    self._token = response["access_token"]
                    expires_in = response.get("expires_in", 3600)
                    self._expires_at = datetime.now(timezone.utc) + timedelta(
                        seconds=expires_in
                    )
                    
                    logger.info(f"Token refreshed successfully, expires in {expires_in}s")
                    return self._token
                    
                except Exception as e:
                    logger.warning(f"Token refresh attempt {attempt} failed: {e}")
                    if attempt == self._max_retries:
                        raise TokenRefreshError(
                            f"Token refresh failed after {self._max_retries} attempts: {e}"
                        )
                    # Wait before retry (exponential backoff)
                    await asyncio.sleep(min(2 ** attempt, 10))
            
            # Should never reach here due to raise above
            raise TokenRefreshError("Token refresh failed unexpectedly")
