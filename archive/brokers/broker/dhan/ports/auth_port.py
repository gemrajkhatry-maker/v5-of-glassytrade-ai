"""
Auth Port - Protocol for authentication.

This module defines the interface for authentication with the Dhan API.
Implementations handle access token management and TOTP-based authentication.

Example:
    >>> from brokers.broker.dhan.ports import IAuthProvider
    >>> 
    >>> # Authenticate with client ID
    >>> access_token = await auth.authenticate("CLIENT_ID", totp="123456")
    >>> 
    >>> # Check authentication status
    >>> if auth.is_authenticated:
    ...     print(f"Token: {auth.access_token}")
"""

from typing import Protocol, runtime_checkable, Optional


# =============================================================================
# Auth Provider Protocol
# =============================================================================

@runtime_checkable
class IAuthProvider(Protocol):
    """Protocol for authentication.
    
    This protocol defines the interface for managing authentication with
    the Dhan API. Implementations should handle:
        - Access token storage and retrieval
        - TOTP-based authentication
        - Token refresh logic
        - Session management
    
    All methods are async to support API calls for authentication.
    
    Example:
        >>> class DhanAuthProvider:
        ...     async def authenticate(self, client_id: str, totp: Optional[str] = None) -> str:
        ...         # Authenticate with Dhan API
        ...         pass
        ...     
        ...     @property
        ...     def access_token(self) -> Optional[str]:
        ...         return self._access_token
    """
    
    async def authenticate(
        self, 
        client_id: str, 
        totp: Optional[str] = None
    ) -> str:
        """Authenticate with the Dhan API.
        
        Performs authentication and returns the access token.
        For accounts with TOTP enabled, provide the TOTP code.
        
        Args:
            client_id: Dhan client ID
            totp: Optional TOTP code for 2FA
        
        Returns:
            Access token string
        
        Raises:
            DhanAuthError: If authentication fails
            DhanTokenInvalidError: If credentials are invalid
        
        Example:
            >>> token = await auth.authenticate("CLIENT123", totp="123456")
            >>> print(f"Authenticated with token: {token}")
        """
        ...
    
    async def refresh_token(self) -> str:
        """Refresh the access token.
        
        Obtains a new access token using the current session.
        
        Returns:
            New access token string
        
        Raises:
            DhanAuthError: If refresh fails
            DhanTokenExpiredError: If session has expired
        
        Example:
            >>> new_token = await auth.refresh_token()
        """
        ...
    
    @property
    def access_token(self) -> Optional[str]:
        """Get the current access token.
        
        Returns:
            Access token if authenticated, None otherwise
        """
        ...
    
    @property
    def is_authenticated(self) -> bool:
        """Check if currently authenticated.
        
        Returns:
            True if valid access token exists, False otherwise
        """
        ...
