"""
Dhan Application Configuration - Configuration dataclass for DhanBroker.

This module provides the configuration class for the Dhan broker implementation.
All configuration values are immutable and can be loaded from environment variables.

Example:
    >>> from brokers.broker.dhan.application import DhanConfig
    >>> 
    >>> # Create from explicit values
    >>> config = DhanConfig(
    ...     client_id="your_client_id",
    ...     access_token="your_access_token",
    ... )
    >>> 
    >>> # Create from environment variables
    >>> config = DhanConfig.from_env()
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from brokers.broker.dhan.domain import (
    API_BASE_URL,
    DHAN_API_V2_BASE_URL,
    WS_URL,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_MAX_RETRIES,
    RATE_LIMIT_DEFAULT,
)


# =============================================================================
# Dhan Configuration
# =============================================================================

@dataclass(frozen=True)
class DhanConfig:
    """
    Immutable configuration for DhanBroker.
    
    This configuration class holds all settings needed to connect to the Dhan API.
    It supports creation from environment variables for secure credential management.
    
    Attributes:
        client_id: Dhan client ID (account identifier).
        access_token: Access token for API authentication.
        base_url: Base URL for the Dhan REST API.
        ws_url: WebSocket URL for real-time data streaming.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts for failed requests.
        retry_delay: Initial delay between retries in seconds.
        rate_limit_per_second: Maximum API calls per second.
        circuit_breaker_threshold: Number of failures before circuit opens.
        circuit_breaker_timeout: Time in seconds before circuit attempts to close.
    
    Example:
        >>> # Create with explicit credentials
        >>> config = DhanConfig(
        ...     client_id="CLIENT123",
        ...     access_token="token_abc123",
        ...     timeout=30.0,
        ... )
        >>> 
        >>> # Create from environment
        >>> # Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN env vars
        >>> config = DhanConfig.from_env()
    """
    
    # Required credentials
    client_id: str
    access_token: str
    
    # API endpoints (default base_url is v2 so all endpoints resolve correctly)
    base_url: str = DHAN_API_V2_BASE_URL
    ws_url: str = WS_URL
    
    # Timeouts and retries
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = 1.0
    
    # Rate limiting
    rate_limit_per_second: float = RATE_LIMIT_DEFAULT
    
    # Circuit breaker
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0

    # Auth
    totp_secret: str = ""
    pin: str = ""
    
    @classmethod
    def from_env(cls, prefix: str = "DHAN_") -> "DhanConfig":
        """
        Create configuration from environment variables.

        Automatically loads .env file from the project root if present.

        Reads the following environment variables:
            - {prefix}CLIENT_ID: Dhan client ID (required)
            - {prefix}ACCESS_TOKEN: Access token (required)
            - {prefix}BASE_URL: API base URL (optional)
            - {prefix}WS_URL: WebSocket URL (optional)
            - {prefix}TIMEOUT: Request timeout in seconds (optional)
            - {prefix}MAX_RETRIES: Maximum retry attempts (optional)
            - {prefix}RATE_LIMIT: Rate limit per second (optional)

        Args:
            prefix: Environment variable prefix (default: "DHAN_").

        Returns:
            DhanConfig instance populated from environment.

        Raises:
            ValueError: If required environment variables are missing.
        """
        # Auto-load .env file (walk up from this file to find project root)
        cls._load_dotenv()

        # Required variables
        client_id = os.environ.get(f"{prefix}CLIENT_ID")
        access_token = os.environ.get(f"{prefix}ACCESS_TOKEN")
        
        if not client_id:
            raise ValueError(
                f"Missing required environment variable: {prefix}CLIENT_ID"
            )
        if not access_token:
            raise ValueError(
                f"Missing required environment variable: {prefix}ACCESS_TOKEN"
            )
        
        # Optional variables with defaults (v2 base URL)
        base_url = os.environ.get(f"{prefix}BASE_URL", DHAN_API_V2_BASE_URL)
        ws_url = os.environ.get(f"{prefix}WS_URL", WS_URL)
        timeout = float(os.environ.get(f"{prefix}TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
        max_retries = int(os.environ.get(f"{prefix}MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))
        retry_delay = float(os.environ.get(f"{prefix}RETRY_DELAY", "1.0"))
        rate_limit = float(os.environ.get(f"{prefix}RATE_LIMIT", str(RATE_LIMIT_DEFAULT)))
        cb_threshold = int(os.environ.get(f"{prefix}CIRCUIT_BREAKER_THRESHOLD", "5"))
        cb_timeout = float(os.environ.get(f"{prefix}CIRCUIT_BREAKER_TIMEOUT", "60.0"))
        totp_secret = os.environ.get(f"{prefix}TOTP_SECRET", "") or os.environ.get("TOTP_SECRET", "")
        pin = os.environ.get(f"{prefix}PIN", "") or os.environ.get("PIN", "")

        return cls(
            client_id=client_id,
            access_token=access_token,
            base_url=base_url,
            ws_url=ws_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
            rate_limit_per_second=rate_limit,
            circuit_breaker_threshold=cb_threshold,
            circuit_breaker_timeout=cb_timeout,
            totp_secret=totp_secret,
            pin=pin,
        )
    
    def with_access_token(self, access_token: str) -> "DhanConfig":
        """
        Create a new config with a different access token.
        
        Useful for token refresh scenarios.
        
        Args:
            access_token: New access token.
        
        Returns:
            New DhanConfig instance with updated token.
        
        Example:
            >>> new_config = config.with_access_token("new_token")
        """
        return DhanConfig(
            client_id=self.client_id,
            access_token=access_token,
            base_url=self.base_url,
            ws_url=self.ws_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            rate_limit_per_second=self.rate_limit_per_second,
            circuit_breaker_threshold=self.circuit_breaker_threshold,
            circuit_breaker_timeout=self.circuit_breaker_timeout,
            totp_secret=self.totp_secret,
            pin=self.pin,
        )
    
    @classmethod
    def _load_dotenv(cls) -> None:
        """Load .env file from project root if python-dotenv is available."""
        try:
            from dotenv import load_dotenv

            # Walk up from this file to find .env
            current = Path(__file__).resolve()
            for parent in current.parents:
                env_file = parent / ".env"
                if env_file.exists():
                    load_dotenv(env_file, override=False)
                    return
                # Stop at git root
                if (parent / ".git").exists():
                    return
        except ImportError:
            pass

    def __repr__(self) -> str:
        """Return string representation with masked credentials."""
        masked_token = (
            self.access_token[:4] + "..." + self.access_token[-4:]
            if len(self.access_token) > 8
            else "****"
        )
        return (
            f"DhanConfig(client_id={self.client_id!r}, "
            f"access_token={masked_token!r}, "
            f"base_url={self.base_url!r}, "
            f"timeout={self.timeout}s)"
        )
