"""
Dhan Auth Provider - Authentication and token lifecycle management.

Uses dhanhq.auth.DhanLogin for TOTP-based authentication and token management.
Handles token generation, renewal, expiry tracking, and persistence.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from brokersv2.infrastructure.dhan_adapter.totp_generator import TOTPGenerator

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when authentication fails."""
    pass


class TokenExpiredError(AuthError):
    """Raised when token has expired."""
    pass


class TokenNearExpiryError(AuthError):
    """Raised when token is near expiry."""
    pass


class DhanAuthProvider:
    """
    Manages Dhan API authentication lifecycle.
    
    Responsibilities:
    - Generate tokens using TOTP + PIN
    - Renew tokens before expiry
    - Track token expiry
    - Persist tokens to .env file
    - Enforce rate limits (2-min cooldown between generations)
    
    Example:
        >>> provider = DhanAuthProvider(client_id="client123")
        >>> token = await provider.generate_token(pin="1234", totp_secret="JBSWY3DPEHPK3PXP")
        >>> await provider.ensure_valid_token()  # Auto-refreshes if needed
    """
    
    # Token expiry buffer (renew if less than this time remaining)
    NEAR_EXPIRY_THRESHOLD = timedelta(hours=1)
    
    # Cooldown between token generations (Dhan API rate limit)
    GENERATION_COOLDOWN = timedelta(minutes=2)
    
    def __init__(
        self,
        client_id: str,
        http_client=None,
        env_file: Optional[str] = None,
    ):
        """
        Initialize auth provider.
        
        Args:
            client_id: Dhan client ID
            http_client: Optional HTTP client (for testing)
            env_file: Path to .env file for token persistence
        """
        self.client_id = client_id
        self._http_client = http_client
        self._env_file = env_file
        
        # Token state
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._totp_secret: Optional[str] = None
        self._pin: Optional[str] = None
        self._last_generation_time: Optional[datetime] = None
    
    def set_totp_secret(self, secret: str) -> None:
        """Set TOTP secret for future token generation."""
        self._totp_secret = secret
    
    def set_pin(self, pin: str) -> None:
        """Set PIN for future token generation."""
        self._pin = pin
    
    def set_current_token(self, token: str, expiry: Optional[datetime] = None) -> None:
        """Set current token manually."""
        self._access_token = token
        if expiry:
            self._token_expiry = expiry
        else:
            # Default 24-hour expiry
            self._token_expiry = datetime.now() + timedelta(hours=24)
    
    async def generate_token(self, pin: str, totp_secret: str) -> str:
        """
        Generate new access token using PIN + TOTP.
        
        Args:
            pin: User PIN
            totp_secret: Base32 TOTP secret
            
        Returns:
            New access token string
            
        Raises:
            AuthError: If generation fails or cooldown not met
        """
        # Check cooldown
        self._check_generation_cooldown()
        
        try:
            # Generate TOTP code
            totp_gen = TOTPGenerator(totp_secret)
            totp_code = totp_gen.generate_code()
            
            # Use dhanhq SDK
            from dhanhq.auth import DhanLogin
            login = DhanLogin(self.client_id)
            
            response = login.generate_token(pin=pin, totp=totp_code)
            
            if not response or "access_token" not in response:
                raise AuthError(f"Invalid response from Dhan: {response}")
            
            token = response["access_token"]
            
            # Store credentials for future auto-generation
            self._totp_secret = totp_secret
            self._pin = pin
            self._last_generation_time = datetime.now()
            
            # Set token with default 24-hour expiry
            self._access_token = token
            self._token_expiry = datetime.now() + timedelta(hours=24)
            
            # Persist to .env
            self._persist_token(token, self._token_expiry)
            
            logger.info(f"Generated new Dhan token for client {self.client_id}")
            return token
            
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Failed to generate token: {e}") from e
    
    async def renew_token(self, access_token: str) -> str:
        """
        Renew access token.
        
        Args:
            access_token: Current (expiring) token
            
        Returns:
            New access token
            
        Raises:
            AuthError: If renewal fails (e.g., token already expired)
        """
        try:
            from dhanhq.auth import DhanLogin
            login = DhanLogin(self.client_id)
            
            response = login.renew_token(access_token)
            
            if not response or "access_token" not in response:
                raise AuthError(f"Invalid renewal response: {response}")
            
            new_token = response["access_token"]
            
            # Update token state
            self._access_token = new_token
            self._token_expiry = datetime.now() + timedelta(hours=24)
            
            # Persist
            self._persist_token(new_token, self._token_expiry)
            
            logger.info(f"Renewed Dhan token for client {self.client_id}")
            return new_token
            
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Failed to renew token: {e}") from e
    
    async def ensure_valid_token(self) -> str:
        """
        Ensure we have a valid token, refreshing if needed.
        
        Logic:
        - If token valid (>1hr remaining): return it
        - If token near expiry (<1hr): renew it
        - If token expired: regenerate using TOTP (if available)
        
        Returns:
            Valid access token
            
        Raises:
            AuthError: If cannot obtain valid token
        """
        # No token at all
        if not self._access_token:
            saved = self._load_saved_token()
            if saved:
                self._access_token = saved
                self._token_expiry = datetime.now() + timedelta(hours=24)
            else:
                raise AuthError("No token available")
        
        # Check expiry
        if self.is_token_expired():
            logger.info("Token expired, attempting regeneration")
            if self._totp_secret and self._pin:
                return await self.generate_token(self._pin, self._totp_secret)
            else:
                raise TokenExpiredError("Token expired and no TOTP credentials available")
        
        # Near expiry - try to renew
        if self.is_token_near_expiry():
            logger.info("Token near expiry, attempting renewal")
            try:
                return await self.renew_token(self._access_token)
            except AuthError:
                # Renewal failed, try regeneration
                if self._totp_secret and self._pin:
                    logger.info("Renewal failed, regenerating token")
                    return await self.generate_token(self._pin, self._totp_secret)
                raise
        
        # Token is valid
        return self._access_token
    
    def is_token_near_expiry(self) -> bool:
        """Check if token is near expiry (<1 hour remaining)."""
        if not self._token_expiry:
            return True
        return datetime.now() >= self._token_expiry - self.NEAR_EXPIRY_THRESHOLD
    
    def is_token_expired(self) -> bool:
        """Check if token has expired."""
        if not self._token_expiry:
            return True
        return datetime.now() >= self._token_expiry
    
    def get_access_token(self) -> Optional[str]:
        """Get current access token without refreshing."""
        return self._access_token
    
    async def validate_token(self, access_token: str) -> dict:
        """
        Validate token using user profile API.
        
        Args:
            access_token: Token to validate
            
        Returns:
            User profile dict
            
        Raises:
            AuthError: If token is invalid/expired
        """
        try:
            from dhanhq.auth import DhanLogin
            login = DhanLogin(self.client_id)
            
            profile = login.user_profile(access_token)
            
            if not profile or profile.get("status") != "success":
                raise AuthError(f"Invalid token: {profile}")
            
            return profile
            
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Token validation failed: {e}") from e
    
    def _check_generation_cooldown(self):
        """Enforce cooldown between token generations."""
        if self._last_generation_time:
            elapsed = datetime.now() - self._last_generation_time
            if elapsed < self.GENERATION_COOLDOWN:
                remaining = self.GENERATION_COOLDOWN - elapsed
                raise AuthError(
                    f"Token generation cooldown: wait {remaining.seconds} seconds"
                )
    
    def _persist_token(self, token: str, expiry: datetime):
        """Persist token to .env file."""
        if not self._env_file:
            logger.debug("No .env file configured, skipping token persistence")
            return
        
        try:
            env_path = self._env_file
            
            # Read existing content
            lines = []
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    lines = f.readlines()
            
            # Update or add DHAN_ACCESS_TOKEN
            token_line = f"DHAN_ACCESS_TOKEN={token}\n"
            found = False
            for i, line in enumerate(lines):
                if line.startswith("DHAN_ACCESS_TOKEN="):
                    lines[i] = token_line
                    found = True
                    break
            
            if not found:
                lines.append(token_line)
            
            # Write back
            with open(env_path, 'w') as f:
                f.writelines(lines)
            
            logger.debug(f"Persisted token to {env_path}")
            
        except Exception as e:
            logger.warning(f"Failed to persist token: {e}")
    
    def _load_saved_token(self) -> Optional[str]:
        """Load saved token from .env file."""
        if not self._env_file or not os.path.exists(self._env_file):
            return None
        
        try:
            with open(self._env_file, 'r') as f:
                for line in f:
                    if line.startswith("DHAN_ACCESS_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        if token:
                            return token
        except Exception as e:
            logger.warning(f"Failed to load token from .env: {e}")
        
        return None
