"""
Dhan Auth Provider - Implementation of IAuthProvider protocol.

This module provides the authentication provider implementation for
managing authentication with the Dhan API.

Features:
    - TOTP-based authentication with auto-generation
    - Smart token policy: reuse → renew → generate
    - JWT exp claim parsing for offline validity check
    - Rate limit cooldown (2-min Dhan constraint)
    - TOTP time window retry for clock drift tolerance
    - Token persistence to .env for reuse across restarts

Example:
    >>> from brokers.broker.dhan.infrastructure import DhanAuthProvider
    >>> 
    >>> auth = DhanAuthProvider(http_client)
    >>> 
    >>> # Option 1: Authenticate with TOTP code directly
    >>> token = await auth.authenticate("CLIENT123", totp="123456")
    >>> 
    >>> # Option 2: Auto-generate token using TOTP secret
    >>> auth.set_totp_secret("JBSWY3DPEHPK3PXP")
    >>> token = await auth.generate_token("CLIENT123")
    >>> 
    >>> # Check authentication status
    >>> if auth.is_authenticated:
    ...     print(f"Token: {auth.access_token}")
    >>> 
    >>> # Auto-refresh if near expiry, auto-generate if expired
    >>> token = await auth.ensure_valid_token()
"""

import asyncio
import base64
import json
import os
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional, Callable, Awaitable

import requests as _requests  # sync HTTP for auth endpoints (rare, once/day)

try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False

from brokers.broker.dhan.ports import (
    IHttpClient,
    IAuthProvider,
)
from brokers.broker.dhan.domain import (
    DhanAuthError,
    DhanTokenExpiredError,
    DhanTokenInvalidError,
    AUTH_GENERATE_TOKEN_URL,
    RENEW_TOKEN_URL,
    TOTP_TIME_WINDOW_SECONDS,
)
from brokers.broker.logging import get_logger


# =============================================================================
# Constants
# =============================================================================

# Near-expiry window: if token expires within this many seconds, try to renew
NEAR_EXPIRY_SECONDS = 3600  # 1 hour

# Cooldown between token generation attempts (Dhan rate limits to once per 2 min)
TOKEN_GENERATION_COOLDOWN_SECONDS = 130  # 2min + 10s buffer


# =============================================================================
# Logger
# =============================================================================

logger = get_logger("dhan.auth")


# =============================================================================
# Dhan Auth Provider Implementation
# =============================================================================

class DhanAuthProvider(IAuthProvider):
    """
    Authentication provider implementation for the Dhan API.

    Implements the IAuthProvider protocol for managing authentication
    with the Dhan API. Handles TOTP-based authentication, token refresh,
    and session management.

    Features:
        - Token expiry tracking
        - Proactive refresh when token is near expiry
        - Auto-refresh on 401 errors (when integrated with HTTP client)
        - Thread-safe token operations
        - Auto-generate new token using TOTP when expired
        - Rate limit cooldown (class-level, shared across instances)

    Attributes:
        http_client: HTTP client whose access token is updated on auth/refresh.
        token_expiry_hours: Hours until token expires (fallback for non-JWT tokens).
    
    Example:
        >>> auth = DhanAuthProvider(http_client)
        >>> 
        >>> # Option 1: Authenticate with client ID and TOTP code
        >>> token = await auth.authenticate("CLIENT123", totp="123456")
        >>> print(f"Authenticated with token: {token}")
        >>> 
        >>> # Option 2: Auto-generate token using TOTP secret
        >>> auth.set_totp_secret("JBSWY3DPEHPK3PXP")
        >>> token = await auth.generate_token("CLIENT123")
        >>> 
        >>> # Check authentication status
        >>> if auth.is_authenticated:
        ...     print("Currently authenticated")
        >>> 
        >>> # Ensure valid token (auto-refresh if near expiry, auto-generate if expired)
        >>> token = await auth.ensure_valid_token()
        >>> 
        >>> # Refresh token manually
        >>> new_token = await auth.refresh_token()
    """

    # Class-level cooldown shared across all instances (Dhan rate limits globally)
    _token_generation_cooldown_until: float = 0.0

    def __init__(
        self,
        http_client: Optional[IHttpClient] = None,
        token_expiry_hours: int = 24,
        on_token_refreshed: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        """
        Initialize the auth provider.
        
        Args:
            http_client: HTTP client whose access token is updated after
                successful authentication or refresh (via set_access_token).
            token_expiry_hours: Hours until token expires (fallback for non-JWT tokens).
            on_token_refreshed: Optional async callback called when token
                is refreshed. Useful for notifying HTTP client of new token.
        """
        self._http = http_client
        self._token_expiry_hours = token_expiry_hours
        self._on_token_refreshed = on_token_refreshed
        
        # Token storage
        self._access_token: Optional[str] = None
        self._client_id: Optional[str] = None
        self._authenticated_at: Optional[float] = None  # Unix epoch (time.time())
        
        # TOTP secret for auto-regeneration
        self._totp_secret: Optional[str] = None
        self._totp: Optional[pyotp.TOTP] = None
        self._pin: Optional[str] = None
        
        # Lock for thread-safe operations
        self._lock: asyncio.Lock = asyncio.Lock()
        
        # Track refresh attempts to prevent loops
        self._refresh_attempt_count: int = 0
        self._max_refresh_attempts: int = 3
        
        logger.debug(
            f"DhanAuthProvider initialized with token_expiry={token_expiry_hours}h, "
            f"near_expiry_threshold={NEAR_EXPIRY_SECONDS}s"
        )
    
    @property
    def access_token(self) -> Optional[str]:
        """Get the current access token."""
        return self._access_token
    
    @property
    def client_id(self) -> Optional[str]:
        """Get the current client ID."""
        return self._client_id
    
    @property
    def is_authenticated(self) -> bool:
        """Check if currently authenticated (using JWT exp claim when available)."""
        if not self._access_token:
            return False

        # Prefer JWT-based expiry check
        jwt_expired = self._is_jwt_expired(self._access_token, leeway_seconds=0)
        if jwt_expired is True:
            logger.debug("Token has expired (JWT exp claim)")
            return False
        if jwt_expired is False:
            return True

        # Fallback to time-based tracking
        if self._authenticated_at:
            expiry_epoch = self._authenticated_at + self._token_expiry_hours * 3600
            if time.time() > expiry_epoch:
                logger.debug("Token has expired (time-based)")
                return False

        return True
    
    @property
    def authenticated_at(self) -> Optional[float]:
        """Get the authentication timestamp (Unix epoch)."""
        return self._authenticated_at

    @property
    def token_age(self) -> Optional[timedelta]:
        """Get the age of the current token."""
        if self._authenticated_at:
            return timedelta(seconds=time.time() - self._authenticated_at)
        return None
    
    @staticmethod
    def _jwt_exp_timestamp(access_token: str) -> Optional[int]:
        """
        Extract the exp (expiry) claim from a JWT access token.

        Returns the Unix timestamp of expiry, or None if the token
        is not a valid JWT or has no exp claim.
        """
        try:
            parts = access_token.split(".")
            if len(parts) != 3:
                return None
            payload_b64 = parts[1]
            # Add padding for base64 decoding
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
            exp = payload.get("exp")
            if exp is None:
                return None
            return int(exp)
        except Exception:
            return None

    @classmethod
    def _is_jwt_expired(cls, access_token: str, leeway_seconds: int = 0) -> Optional[bool]:
        """
        Check if a JWT token has expired (with optional leeway).

        Returns True if expired, False if still valid, None if not a valid JWT.
        """
        exp = cls._jwt_exp_timestamp(access_token)
        if exp is None:
            return None
        return int(time.time()) >= (exp - max(0, leeway_seconds))

    @property
    def token_expires_at_epoch(self) -> Optional[float]:
        """
        Get the token expiry as a Unix epoch timestamp.

        Uses JWT exp claim if available, otherwise falls back to
        authenticated_at + token_expiry_hours.
        """
        if self._access_token:
            exp_ts = self._jwt_exp_timestamp(self._access_token)
            if exp_ts is not None:
                return float(exp_ts)

        if self._authenticated_at:
            return self._authenticated_at + self._token_expiry_hours * 3600
        return None

    @property
    def time_until_expiry(self) -> Optional[timedelta]:
        """Get the time remaining until token expires."""
        expires_at = self.token_expires_at_epoch
        if expires_at is not None:
            remaining = expires_at - time.time()
            return timedelta(seconds=max(0, remaining))
        return None

    @property
    def jwt_seconds_remaining(self) -> Optional[int]:
        """
        Get seconds remaining on JWT token.

        Returns None if token is not a JWT or has no exp claim.
        More efficient than time_until_expiry for frequent checks.
        """
        if not self._access_token:
            return None
        exp_ts = self._jwt_exp_timestamp(self._access_token)
        if exp_ts is None:
            return None
        return max(0, int(exp_ts - time.time()))
    
    @property
    def needs_refresh(self) -> bool:
        """Check if token needs refresh (within NEAR_EXPIRY_SECONDS or expired)."""
        if not self._access_token:
            return True

        time_remaining = self.time_until_expiry
        if time_remaining is None:
            return False

        return time_remaining.total_seconds() <= NEAR_EXPIRY_SECONDS
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired (no leeway — matches ensure_valid_token JWT path)."""
        if self._access_token:
            jwt_expired = self._is_jwt_expired(self._access_token, leeway_seconds=0)
            if jwt_expired is not None:
                return jwt_expired
        # Fallback to time-based
        time_remaining = self.time_until_expiry
        return time_remaining is not None and time_remaining.total_seconds() <= 0
    
    def set_token(
        self,
        access_token: str,
        client_id: Optional[str] = None,
        totp_secret: Optional[str] = None,
    ) -> None:
        """
        Set the access token directly.

        Use this method when authentication is done externally
        (e.g., through the Dhan web interface).

        Args:
            access_token: The access token.
            client_id: Optional client ID.
            totp_secret: Optional TOTP secret for auto-regeneration.
        """
        self._access_token = access_token
        self._client_id = client_id
        self._authenticated_at = time.time()
        self._refresh_attempt_count = 0

        if totp_secret:
            self.set_totp_secret(totp_secret)

        logger.info("Access token set directly")
    
    def set_totp_secret(self, totp_secret: str) -> None:
        """
        Set the TOTP secret for auto-regeneration.
        
        Args:
            totp_secret: The TOTP secret key.
        """
        self._totp_secret = totp_secret
        if not PYOTP_AVAILABLE:
            logger.warning("pyotp not installed; TOTP auto-generation disabled")
            self._totp = None
            return
        try:
            if not totp_secret or not totp_secret.strip():
                raise ValueError("TOTP secret cannot be empty")
            self._totp = pyotp.TOTP(totp_secret)
            logger.debug("TOTP secret configured for auto-regeneration")
        except ValueError as e:
            logger.warning(f"Failed to initialize TOTP generator: {e}")
            self._totp = None

    def _generate_totp_code(self, window_offset: int = 0) -> str:
        """Generate TOTP code via pyotp, with window offset for clock drift."""
        if not self._totp:
            raise ValueError("TOTP secret not configured")
        if window_offset == 0:
            return self._totp.now()
        time_window = int(time.time() // TOTP_TIME_WINDOW_SECONDS) + window_offset
        return self._totp.at(time_window)
    
    def set_pin(self, pin: str) -> None:
        """Set the PIN for token generation (required by Dhan API)."""
        self._pin = pin
        logger.debug("PIN configured for token generation")

    async def authenticate(
        self,
        client_id: str,
        totp: Optional[str] = None
    ) -> str:
        """
        Authenticate with the Dhan API.
        
        Performs authentication and returns the access token.
        For accounts with TOTP enabled, provide the TOTP code.
        
        Args:
            client_id: Dhan client ID.
            totp: Optional TOTP code for 2FA.
        
        Returns:
            Access token string.
        
        Raises:
            DhanAuthError: If authentication fails.
            DhanTokenInvalidError: If credentials are invalid.
        """
        async with self._lock:
            return await self._authenticate_unlocked(client_id, totp)
    
    async def _authenticate_unlocked(
        self,
        client_id: str,
        totp: Optional[str] = None
    ) -> str:
        """
        Authenticate via Dhan's real API: POST https://auth.dhan.co/app/generateAccessToken.

        Uses sync requests since auth.dhan.co is a separate host and auth is rare (once/day).
        """
        if not self._pin:
            raise DhanAuthError(
                message="PIN not configured for authentication",
                details={"hint": "Call set_pin() or set DHAN_PIN env var"},
            )

        if not totp:
            raise DhanAuthError(
                message="TOTP code required for authentication",
            )

        logger.info(f"Authenticating client: {client_id} via auth.dhan.co")

        try:
            # Dhan uses query parameters, NOT JSON body
            response = _requests.post(
                AUTH_GENERATE_TOKEN_URL,
                params={
                    "dhanClientId": client_id,
                    "pin": self._pin,
                    "totp": totp,
                },
                timeout=15,
            )

            data = response.json()

            if response.status_code != 200 or data.get("status") == "error":
                error_msg = data.get("message", data.get("data", "Authentication failed"))
                raise DhanAuthError(
                    message=f"Authentication failed: {error_msg}",
                    details={"status": response.status_code},
                )

            # Extract access token
            access_token = data.get("accessToken") or data.get("access_token") or data.get("token")
            if not access_token:
                raise DhanAuthError(
                    message="No access token in response",
                )

            # Store tokens
            self._access_token = access_token
            self._client_id = client_id
            self._authenticated_at = time.time()
            self._refresh_attempt_count = 0

            logger.info(f"Authentication successful for client: {client_id}")

            # Update HTTP client with new token
            if self._http and hasattr(self._http, 'set_access_token'):
                self._http.set_access_token(access_token)

            # Notify callback if registered
            if self._on_token_refreshed:
                try:
                    await self._on_token_refreshed(access_token)
                except Exception as e:
                    logger.warning(f"Token refresh callback failed: {e}")

            return access_token

        except DhanAuthError:
            raise
        except Exception as e:
            logger.exception("Authentication failed")
            raise DhanAuthError(
                message=f"Authentication failed: {e}",
                details={"error": str(e)},
            )
    
    async def generate_token(
        self,
        client_id: str,
        totp_secret: Optional[str] = None,
    ) -> str:
        """
        Generate a new token using TOTP auto-generation.
        
        This method automatically generates a TOTP code from the secret
        and authenticates with the Dhan API.
        
        Args:
            client_id: Dhan client ID.
            totp_secret: Optional TOTP secret. If not provided, uses stored secret.
        
        Returns:
            Access token string.
        
        Raises:
            DhanAuthError: If authentication fails or TOTP secret not available.
            DhanTokenInvalidError: If credentials are invalid.
        
        Example:
            >>> auth = DhanAuthProvider(http_client)
            >>> auth.set_totp_secret("JBSWY3DPEHPK3PXP")
            >>> token = await auth.generate_token("CLIENT123")
        """
        async with self._lock:
            if totp_secret:
                self.set_totp_secret(totp_secret)
            return await self._generate_token_unlocked(client_id)
    
    async def refresh_token(self) -> str:
        """
        Renew the access token via Dhan's RenewToken API.

        Sends the current access token + client ID to get a new token.

        Returns:
            New access token string.

        Raises:
            DhanAuthError: If renewal fails.
            DhanTokenExpiredError: If session has expired and re-auth is needed.
        """
        async with self._lock:
            return await self._refresh_token_unlocked()
    
    async def _refresh_token_unlocked(self) -> str:
        """
        Internal refresh without lock (for use within locked context).
        
        Returns:
            New access token string.
        
        Raises:
            DhanAuthError: If refresh fails.
            DhanTokenExpiredError: If session has expired.
        """
        if not self._access_token:
            raise DhanAuthError(
                message="No access token to refresh",
                details={"hint": "Call authenticate() first"},
            )
        
        if not self._client_id:
            raise DhanAuthError(
                message="No client ID stored",
                details={"hint": "Call authenticate() first"},
            )
        
        # Check for refresh loop
        if self._refresh_attempt_count >= self._max_refresh_attempts:
            logger.error(
                f"Max refresh attempts ({self._max_refresh_attempts}) exceeded"
            )
            raise DhanAuthError(
                message="Max refresh attempts exceeded",
                details={"attempts": self._refresh_attempt_count},
            )
        
        self._refresh_attempt_count += 1
        logger.info(
            f"Refreshing access token (attempt {self._refresh_attempt_count})..."
        )
        
        try:
            response = _requests.get(
                RENEW_TOKEN_URL,
                headers={
                    "access-token": self._access_token,
                    "dhanClientId": self._client_id,
                },
                timeout=15,
            )

            data = response.json()

            if response.status_code == 401:
                raise DhanTokenExpiredError(
                    message="Session has expired, re-authentication required",
                    details={"status": 401},
                )

            if response.status_code != 200:
                error_msg = data.get("message", "Token refresh failed")
                raise DhanAuthError(
                    message=error_msg,
                    details={"status": response.status_code},
                )

            # Extract new access token
            access_token = data.get("accessToken") or data.get("access_token") or data.get("token")

            if not access_token:
                raise DhanAuthError(
                    message="No access token in refresh response",
                )

            # Store new token
            self._access_token = access_token
            self._authenticated_at = time.time()
            self._refresh_attempt_count = 0

            logger.info("Token refresh successful")

            # Persist to .env
            self._save_token_to_env(access_token)

            # Update HTTP client with new token
            if self._http and hasattr(self._http, 'set_access_token'):
                self._http.set_access_token(access_token)

            # Notify callback if registered
            if self._on_token_refreshed:
                try:
                    await self._on_token_refreshed(access_token)
                except Exception as e:
                    logger.warning(f"Token refresh callback failed: {e}")

            return access_token

        except DhanAuthError:
            raise
        except Exception as e:
            logger.exception("Token refresh failed")
            raise DhanAuthError(
                message=f"Token refresh failed: {e}",
                details={"error": str(e)},
            )
    
    async def ensure_valid_token(self) -> str:
        """
        Smart token policy: reuse → renew → generate.

        Flow (matches dhanhq_custom get_token_with_policy):
        1. No token at all → generate via TOTP+PIN
        2. Parse JWT exp claim (no API call)
        3. Expired (exp <= now) → generate new token
        4. Near expiry (exp within 1hr) → try renew, fallback to current token
        5. Valid (exp > 1hr away) → return as-is
        6. On new token → save to .env

        Returns:
            Valid access token string.

        Raises:
            DhanAuthError: If not authenticated and cannot refresh/regenerate.
            DhanTokenExpiredError: If token expired and cannot regenerate.
        """
        async with self._lock:
            access_token = self._access_token

            # 1. No token → generate
            if not access_token:
                if self._totp and self._client_id:
                    logger.info("No token available, generating via TOTP...")
                    return await self._generate_token_unlocked(self._client_id)
                raise DhanAuthError(
                    message="Not authenticated",
                    details={"hint": "Call authenticate(), generate_token(), or set_token() first"},
                )

            # 2. Parse JWT exp
            now = int(time.time())
            exp_ts = self._jwt_exp_timestamp(access_token)

            if exp_ts is None:
                # Not a JWT or can't parse — fall back to time-based check
                if self.is_expired:
                    if self._totp and self._client_id:
                        return await self._generate_token_unlocked(self._client_id)
                    raise DhanTokenExpiredError(message="Token expired and cannot regenerate")
                # Near expiry (time-based) → try renew
                if self.needs_refresh and self._client_id:
                    logger.info("Token near expiry (time-based), attempting renewal...")
                    try:
                        return await self._refresh_token_unlocked()
                    except Exception as e:
                        logger.warning(f"Renewal failed: {e}")
                return access_token

            seconds_to_expiry = exp_ts - now

            # 3. Expired → generate
            if seconds_to_expiry <= 0:
                if self._totp and self._client_id:
                    logger.info(f"Token expired ({-seconds_to_expiry}s ago), generating new token...")
                    return await self._generate_token_unlocked(self._client_id)
                raise DhanTokenExpiredError(
                    message="Token expired and cannot regenerate",
                    details={"expired_seconds_ago": -seconds_to_expiry},
                )

            # 4. Valid and far from expiry → return as-is
            if seconds_to_expiry > NEAR_EXPIRY_SECONDS:
                self._refresh_attempt_count = 0
                logger.debug(f"Token valid for {seconds_to_expiry}s, reusing")
                return access_token

            # 5. Near expiry → try renew, fallback gracefully
            logger.info(f"Token near expiry ({seconds_to_expiry}s remaining), attempting renewal...")
            if self._client_id:
                try:
                    return await self._refresh_token_unlocked()
                except Exception as e:
                    logger.warning(f"Renewal failed: {e}")
                    # Still have time? Return current token
                    if seconds_to_expiry > 60:
                        logger.info(f"Using current token ({seconds_to_expiry}s remaining)")
                        return access_token
                    # Almost expired, try generate
                    if self._totp and self._client_id:
                        return await self._generate_token_unlocked(self._client_id)

            return access_token
    
    async def _generate_token_unlocked(self, client_id: str) -> str:
        """
        Internal token generation with rate limit cooldown and TOTP window retry.

        Matches dhanhq_custom generate_token() behavior:
        - Checks 2-min cooldown before attempting
        - On "Invalid TOTP", retries with window offsets (-1, 1, -2, 2)
        - On rate limit response, sets cooldown timer
        - Saves new token to .env on success
        """
        if not self._totp:
            raise DhanAuthError(
                message="TOTP secret not configured",
                details={"hint": "Call set_totp_secret() first"},
            )

        # Check rate limit cooldown
        now = time.time()
        if now < self.__class__._token_generation_cooldown_until:
            remaining = int(self.__class__._token_generation_cooldown_until - now)
            raise DhanAuthError(
                message=f"Rate limit: wait {remaining}s before generating a new token",
                details={"cooldown_remaining": remaining},
            )

        # Try with current TOTP first, then window offsets on Invalid TOTP
        offsets_to_try = [0, -1, 1, -2, 2]
        last_error = None

        for offset in offsets_to_try:
            try:
                totp_code = self._generate_totp_code(window_offset=offset)
                if offset != 0:
                    logger.debug(f"Retrying TOTP with window_offset={offset}")
                token = await self._authenticate_unlocked(client_id, totp_code)
                # Success — save to .env
                self._save_token_to_env(token)
                return token
            except DhanAuthError as e:
                error_msg = str(e).lower()
                # Rate limit — set cooldown and stop retrying
                if "2 minutes" in error_msg or "rate limit" in error_msg or "too many" in error_msg:
                    self.__class__._token_generation_cooldown_until = time.time() + TOKEN_GENERATION_COOLDOWN_SECONDS
                    raise
                # Invalid TOTP — try next window offset
                if "invalid totp" in error_msg or "invalid otp" in error_msg:
                    last_error = e
                    continue
                # Other auth error — don't retry
                raise
            except Exception as e:
                raise DhanAuthError(
                    message=f"Failed to generate TOTP: {e}",
                    details={"error": str(e)},
                )

        # All TOTP windows exhausted
        raise last_error or DhanAuthError(message="Token generation failed after all TOTP window retries")
    
    def ensure_valid_token_sync(self, client_id: str | None = None) -> str:
        """
        Synchronous token management — called during broker creation.

        Flow:
        1. No token → generate via TOTP+PIN (produces APP token — WS only)
        2. Token expired → try renew first (preserves SELF type), fallback to generate
        3. Token near-expiry (<1h) → renew → save to .env
        4. Token valid → return as-is

        NOTE: generateAccessToken produces tokenConsumerType=APP tokens which
        only work for WebSocket feeds. For REST API (orders, positions), you
        need a SELF token from the Dhan web portal consent flow.
        Renew preserves the original token type (SELF stays SELF).

        This avoids asyncio entirely — uses sync HTTP (requests) which
        the auth endpoints already use internally.
        """
        if client_id:
            self._client_id = client_id

        access_token = self._access_token

        # 1. No token → generate (will be APP type — WS only)
        if not access_token:
            logger.warning(
                "No access token available. Generating via TOTP (APP type — WS feeds only). "
                "For REST API access, generate a SELF token from https://web.dhan.co"
            )
            return self._generate_token_sync()

        # 2. Parse JWT exp
        now = int(time.time())
        exp_ts = self._jwt_exp_timestamp(access_token)

        if exp_ts is None:
            logger.debug("Token is not a JWT, assuming valid")
            return access_token

        seconds_to_expiry = exp_ts - now

        # 3. Expired → try renew first (preserves SELF type), fallback to generate
        if seconds_to_expiry <= 0:
            logger.info(f"Token expired {-seconds_to_expiry}s ago")
            # Try renew first — if it was a SELF token, renew keeps it SELF
            try:
                return self._refresh_token_sync()
            except Exception:
                logger.warning(
                    "Renewal failed. Generating via TOTP (APP type — WS feeds only). "
                    "For REST API, generate a SELF token from https://web.dhan.co"
                )
                return self._generate_token_sync()

        # 4. Near expiry → try renew (preserves token type)
        if seconds_to_expiry <= NEAR_EXPIRY_SECONDS:
            logger.info(f"Token near expiry ({seconds_to_expiry}s remaining), renewing...")
            try:
                return self._refresh_token_sync()
            except Exception as e:
                logger.warning(f"Renewal failed ({e})")
                if seconds_to_expiry > 60:
                    return access_token  # still usable
                return self._generate_token_sync()

        # 5. Valid
        logger.info(f"Token valid for {seconds_to_expiry}s ({seconds_to_expiry // 3600}h), reusing")
        return access_token

    def _generate_token_sync(self) -> str:
        """Synchronous token generation via TOTP+PIN."""
        if not self._totp:
            raise DhanAuthError(
                message="Cannot generate token: TOTP secret not configured",
                details={"hint": "Set TOTP_SECRET in .env"},
            )
        if not self._pin:
            raise DhanAuthError(
                message="Cannot generate token: PIN not configured",
                details={"hint": "Set PIN in .env"},
            )
        if not self._client_id:
            raise DhanAuthError(message="Cannot generate token: client_id not set")

        # Check rate limit cooldown
        now = time.time()
        if now < self.__class__._token_generation_cooldown_until:
            remaining = int(self.__class__._token_generation_cooldown_until - now)
            raise DhanAuthError(
                message=f"Rate limit: wait {remaining}s before generating a new token",
            )

        # Try TOTP with window offsets for clock drift
        offsets = [0, -1, 1, -2, 2]
        last_error = None

        for offset in offsets:
            try:
                totp_code = self._generate_totp_code(window_offset=offset)
                if offset != 0:
                    logger.debug(f"Retrying TOTP with window_offset={offset}")

                # Dhan uses query parameters, NOT JSON body
                response = _requests.post(
                    AUTH_GENERATE_TOKEN_URL,
                    params={
                        "dhanClientId": self._client_id,
                        "pin": self._pin,
                        "totp": totp_code,
                    },
                    timeout=15,
                )
                data = response.json()

                if response.status_code != 200 or data.get("status") == "error":
                    error_msg = data.get("message", data.get("data", "Auth failed"))
                    err = DhanAuthError(message=f"Auth failed: {error_msg}")
                    error_lower = error_msg.lower()
                    if "2 minutes" in error_lower or "rate limit" in error_lower or "too many" in error_lower:
                        self.__class__._token_generation_cooldown_until = (
                            time.time() + TOKEN_GENERATION_COOLDOWN_SECONDS
                        )
                        raise err
                    if "invalid totp" in error_lower or "invalid otp" in error_lower:
                        last_error = err
                        continue
                    raise err

                token = (
                    data.get("accessToken")
                    or data.get("access_token")
                    or data.get("token")
                )
                if not token:
                    raise DhanAuthError(message="No access token in response")

                self._access_token = token
                self._authenticated_at = time.time()
                self._refresh_attempt_count = 0
                self._save_token_to_env(token)
                logger.info("Token generated successfully via TOTP")
                return token

            except DhanAuthError:
                raise
            except Exception as e:
                raise DhanAuthError(message=f"Token generation failed: {e}")

        raise last_error or DhanAuthError(message="Token generation failed after all TOTP retries")

    def _refresh_token_sync(self) -> str:
        """Synchronous token renewal via Dhan RenewToken API."""
        if not self._access_token or not self._client_id:
            raise DhanAuthError(message="No token/client_id to refresh")

        response = _requests.get(
            RENEW_TOKEN_URL,
            headers={
                "access-token": self._access_token,
                "dhanClientId": self._client_id,
            },
            timeout=15,
        )
        data = response.json()

        if response.status_code == 401:
            raise DhanTokenExpiredError(message="Session expired, need re-auth")
        if response.status_code != 200:
            raise DhanAuthError(message=data.get("message", "Renewal failed"))

        token = data.get("accessToken") or data.get("access_token") or data.get("token")
        if not token:
            raise DhanAuthError(message="No token in renewal response")

        self._access_token = token
        self._authenticated_at = time.time()
        self._refresh_attempt_count = 0
        self._save_token_to_env(token)
        logger.info("Token renewed successfully")
        return token

    @classmethod
    def _save_token_to_env(cls, access_token: str) -> None:
        """Save access token to .env file for reuse across restarts."""
        # Never overwrite .env during unit tests or with dummy tokens
        if os.environ.get("PYTEST_CURRENT_TEST") or not access_token or not access_token.startswith("eyJ"):
            logger.debug("Skipping .env token persistence (testing or non-JWT token)")
            return

        try:
            from dotenv import set_key, load_dotenv
        except ImportError:
            logger.debug("python-dotenv not available, skipping token persistence")
            return

        try:
            current = Path(__file__).resolve()
            env_file = None
            for parent in current.parents:
                candidate = parent / ".env"
                if candidate.exists():
                    env_file = str(candidate)
                    break
                if (parent / ".git").exists():
                    break

            if not env_file:
                logger.debug("No .env file found, skipping token persistence")
                return

            set_key(env_file, "DHAN_ACCESS_TOKEN", access_token)
            set_key(env_file, "DHAN_ACCESS_TOKEN_SAVED_AT", str(int(time.time())))
            load_dotenv(env_file, override=True)
            os.environ["DHAN_ACCESS_TOKEN"] = access_token
            logger.info("Token saved to .env")
        except Exception as e:
            logger.warning(f"Failed to save token to .env: {e}")

    async def handle_auth_error(self, error: Exception) -> bool:
        """
        Handle an authentication error from API calls.
        
        Call this method when you receive a 401 or 403 error from the API.
        It will attempt to refresh the token or regenerate using TOTP if possible.
        
        Args:
            error: The authentication error that occurred.
        
        Returns:
            True if token was refreshed/regenerated and request can be retried,
            False if refresh failed and re-authentication is needed.
        
        Example:
            >>> try:
            ...     response = await client.get("/orders")
            ... except DhanTokenExpiredError:
            ...     if await auth.handle_auth_error(e):
            ...         # Retry the request
            ...         response = await client.get("/orders")
            ...     else:
            ...         # Need to re-authenticate
            ...         await auth.authenticate(client_id, totp)
        """
        if isinstance(error, (DhanTokenExpiredError, DhanTokenInvalidError)):
            logger.info(f"Handling auth error: {error}")
            async with self._lock:
                # Invalidate current token inside the lock
                self._access_token = None
                self._authenticated_at = None
                if self._totp and self._client_id:
                    try:
                        await self._generate_token_unlocked(self._client_id)
                        logger.info("Token regenerated after auth error")
                        return True
                    except DhanAuthError as e:
                        logger.warning(f"Token recovery failed: {e}")
                        return False
            return False

        return False
    
    def clear(self) -> None:
        """
        Clear the stored authentication data.
        
        Should be called when logging out or when the token is known to be invalid.
        """
        self._access_token = None
        self._client_id = None
        self._authenticated_at = None
        self._totp_secret = None
        self._totp = None
        self._refresh_attempt_count = 0
        
        logger.info("Authentication data cleared")
    
    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"DhanAuthProvider(authenticated={self.is_authenticated}, "
            f"client_id={self._client_id!r}, "
            f"token_age={self.token_age}, "
            f"needs_refresh={self.needs_refresh}, "
            f"has_totp={self._totp is not None})"
        )