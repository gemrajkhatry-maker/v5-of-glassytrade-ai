"""
JWT Session Manager with automatic token refresh.

Manages broker authentication sessions:
- Token storage and validation
- Automatic refresh before expiry
- Session lifecycle management
- Multi-session support
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session lifecycle states."""
    CREATED = "created"
    ACTIVE = "active"
    EXPIRED = "expired"
    REFRESHING = "refreshing"
    REVOKED = "revoked"


@dataclass
class SessionConfig:
    """Configuration for session management."""
    
    # Token timing
    token_lifetime: int = 3600  # Token lifetime in seconds (1 hour)
    refresh_threshold: int = 300  # Refresh when 5 minutes remaining
    auto_refresh: bool = True  # Enable automatic refresh
    
    # Refresh limits
    max_refresh_attempts: int = 3
    refresh_backoff: float = 2.0  # Base backoff for refresh retries
    
    # Session limits
    max_concurrent_sessions: int = 5
    session_timeout: int = 86400  # 24 hours


@dataclass
class SessionInfo:
    """Information about a session."""
    
    session_id: str
    user_id: str
    state: SessionState = SessionState.CREATED
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_refreshed: Optional[datetime] = None
    refresh_count: int = 0
    
    @property
    def is_active(self) -> bool:
        """Check if session is active."""
        return self.state == SessionState.ACTIVE
    
    @property
    def needs_refresh(self) -> bool:
        """Check if token needs refresh."""
        if not self.expires_at:
            return False
        
        time_remaining = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return time_remaining < 300  # Less than 5 minutes
    
    @property
    def is_expired(self) -> bool:
        """Check if session is expired."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def time_to_expiry(self) -> float:
        """Seconds until token expires."""
        if not self.expires_at:
            return 0.0
        return max(0, (self.expires_at - datetime.now(timezone.utc)).total_seconds())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "state": self.state.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_refreshed": self.last_refreshed.isoformat() if self.last_refreshed else None,
            "refresh_count": self.refresh_count,
            "time_to_expiry": round(self.time_to_expiry, 0),
        }


class SessionManager:
    """
    Manages JWT sessions with automatic refresh.
    
    Usage:
        manager = SessionManager(
            token_refresher=refresh_token_function,
            config=SessionConfig()
        )
        
        # Create session
        session = await manager.create_session(
            session_id="user_123",
            user_id="user_123",
            access_token="...",
            refresh_token="...",
            expires_at=datetime.now() + timedelta(hours=1)
        )
        
        # Get valid token (auto-refreshes if needed)
        token = await manager.get_valid_token("user_123")
    """
    
    def __init__(
        self,
        token_refresher: Optional[Callable[..., Coroutine[Any, Any, Dict[str, str]]]] = None,
        config: Optional[SessionConfig] = None,
    ):
        self.token_refresher = token_refresher
        self.config = config or SessionConfig()
        self._sessions: Dict[str, SessionInfo] = {}
        self._refresh_locks: Dict[str, asyncio.Lock] = {}
    
    async def create_session(
        self,
        session_id: str,
        user_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> SessionInfo:
        """
        Create a new session.
        
        Args:
            session_id: Unique session identifier
            user_id: User identifier
            access_token: JWT access token
            refresh_token: Optional refresh token
            expires_at: Token expiration time
            
        Returns:
            Created session info
        """
        # Check session limit
        if len(self._sessions) >= self.config.max_concurrent_sessions:
            raise SessionLimitError(
                f"Maximum {self.config.max_concurrent_sessions} concurrent sessions allowed"
            )
        
        # Set default expiry
        if expires_at is None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.config.token_lifetime)
        
        session = SessionInfo(
            session_id=session_id,
            user_id=user_id,
            state=SessionState.ACTIVE,
            access_token=access_token,
            refresh_token=refresh_token,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
        
        self._sessions[user_id] = session
        self._refresh_locks[user_id] = asyncio.Lock()
        
        logger.info(f"Session created: {user_id} expires in {session.time_to_expiry:.0f}s")
        
        return session
    
    async def get_valid_token(self, user_id: str) -> str:
        """
        Get a valid access token, refreshing if necessary.
        
        Args:
            user_id: User identifier
            
        Returns:
            Valid access token
            
        Raises:
            SessionNotFoundError: If session doesn't exist
            SessionExpiredError: If session cannot be refreshed
        """
        session = self._sessions.get(user_id)
        if not session:
            raise SessionNotFoundError(f"No session found for user {user_id}")
        
        # Check if session is active
        if session.state == SessionState.REVOKED:
            raise SessionRevokedError(f"Session revoked for user {user_id}")
        
        # Check if token is still valid
        if not session.needs_refresh and not session.is_expired:
            return session.access_token
        
        # Need to refresh
        if not session.refresh_token:
            raise SessionExpiredError(
                f"No refresh token available for user {user_id}"
            )
        
        # Refresh with lock to prevent concurrent refreshes
        async with self._refresh_locks[user_id]:
            # Double-check after acquiring lock
            if not session.needs_refresh and not session.is_expired:
                return session.access_token
            
            return await self._refresh_session(session)
    
    async def _refresh_session(self, session: SessionInfo) -> str:
        """
        Refresh a session's tokens.
        
        Args:
            session: Session to refresh
            
        Returns:
            New access token
        """
        session.state = SessionState.REFRESHING
        logger.info(f"Refreshing session for user {session.user_id}")
        
        for attempt in range(self.config.max_refresh_attempts):
            try:
                if not self.token_refresher:
                    raise SessionError("No token refresher configured")
                
                # Call token refresher
                tokens = await self.token_refresher(
                    user_id=session.user_id,
                    refresh_token=session.refresh_token,
                )
                
                # Update session
                session.access_token = tokens["access_token"]
                if "refresh_token" in tokens:
                    session.refresh_token = tokens["refresh_token"]
                
                # Update expiry
                session.expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=self.config.token_lifetime
                )
                
                session.last_refreshed = datetime.now(timezone.utc)
                session.refresh_count += 1
                session.state = SessionState.ACTIVE
                
                logger.info(
                    f"Session refreshed for user {session.user_id} "
                    f"(attempt {attempt + 1})"
                )
                
                return session.access_token
                
            except Exception as e:
                logger.warning(
                    f"Refresh attempt {attempt + 1} failed for {session.user_id}: {e}"
                )
                
                if attempt < self.config.max_refresh_attempts - 1:
                    # Wait before retry
                    wait_time = self.config.refresh_backoff * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                else:
                    # All attempts failed
                    session.state = SessionState.EXPIRED
                    raise SessionExpiredError(
                        f"Failed to refresh session after {self.config.max_refresh_attempts} attempts: {e}"
                    )
        
        # Should never reach here
        raise SessionExpiredError("Refresh failed unexpectedly")
    
    async def revoke_session(self, user_id: str) -> None:
        """
        Revoke a session.
        
        Args:
            user_id: User identifier
        """
        session = self._sessions.get(user_id)
        if session:
            session.state = SessionState.REVOKED
            session.access_token = None
            session.refresh_token = None
            logger.info(f"Session revoked for user {user_id}")
    
    async def cleanup_expired_sessions(self) -> int:
        """
        Remove expired sessions.
        
        Returns:
            Number of sessions removed
        """
        expired_users = [
            user_id
            for user_id, session in self._sessions.items()
            if session.is_expired or session.state == SessionState.REVOKED
        ]
        
        for user_id in expired_users:
            del self._sessions[user_id]
            if user_id in self._refresh_locks:
                del self._refresh_locks[user_id]
        
        if expired_users:
            logger.info(f"Cleaned up {len(expired_users)} expired sessions")
        
        return len(expired_users)
    
    def get_session(self, user_id: str) -> Optional[SessionInfo]:
        """Get session info for user."""
        return self._sessions.get(user_id)
    
    def get_active_sessions(self) -> Dict[str, SessionInfo]:
        """Get all active sessions."""
        return {
            user_id: session
            for user_id, session in self._sessions.items()
            if session.is_active
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get session manager status."""
        return {
            "total_sessions": len(self._sessions),
            "active_sessions": len(self.get_active_sessions()),
            "config": {
                "token_lifetime": self.config.token_lifetime,
                "refresh_threshold": self.config.refresh_threshold,
                "auto_refresh": self.config.auto_refresh,
                "max_concurrent_sessions": self.config.max_concurrent_sessions,
            },
        }


class SessionError(Exception):
    """Base session error."""
    pass


class SessionNotFoundError(SessionError):
    """Session not found."""
    pass


class SessionExpiredError(SessionError):
    """Session expired and cannot be refreshed."""
    pass


class SessionRevokedError(SessionError):
    """Session has been revoked."""
    pass


class SessionLimitError(SessionError):
    """Maximum session limit reached."""
    pass
