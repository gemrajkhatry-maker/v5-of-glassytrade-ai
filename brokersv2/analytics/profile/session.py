"""Session Profile Manager."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from brokersv2.analytics.profile.events import (
    ProfileType,
    TPOProfile,
    VolumeProfile,
    ProfileEvent,
)


class SessionProfileManager:
    """
    Manage session profiles and create rolling profiles.
    
    Features:
    - Session profile storage
    - Session retrieval by date
    - Recent session queries
    - Rolling profile creation
    - Average POC calculation
    """

    def __init__(self):
        self._sessions: Dict[str, List] = {}  # symbol -> [profiles]

    def create_session(
        self,
        symbol: str,
        session_date: datetime,
        profile_type: ProfileType = ProfileType.TPO,
    ):
        """
        Create a new session profile.
        
        Args:
            symbol: Instrument symbol
            session_date: Session date
            profile_type: Type of profile
            
        Returns:
            Empty profile object
        """
        if profile_type == ProfileType.TPO:
            return TPOProfile(
                symbol=symbol,
                session_date=session_date,
                levels=[],
            )
        else:
            return VolumeProfile(
                symbol=symbol,
                session_date=session_date,
                levels=[],
            )

    def store_session(self, profile) -> None:
        """
        Store session profile.
        
        Args:
            profile: TPOProfile or VolumeProfile
        """
        symbol = profile.symbol
        if symbol not in self._sessions:
            self._sessions[symbol] = []
        
        self._sessions[symbol].append(profile)

    def get_session(
        self,
        symbol: str,
        session_date: datetime,
    ) -> Optional[object]:
        """
        Get session by date.
        
        Args:
            symbol: Instrument symbol
            session_date: Session date
            
        Returns:
            Session profile or None
        """
        if symbol not in self._sessions:
            return None
        
        for session in self._sessions[symbol]:
            if session.session_date.date() == session_date.date():
                return session
        
        return None

    def get_recent_sessions(
        self,
        symbol: str,
        count: int = 5,
    ) -> List[object]:
        """
        Get most recent sessions.
        
        Args:
            symbol: Instrument symbol
            count: Number of sessions
            
        Returns:
            List of recent profiles
        """
        if symbol not in self._sessions:
            return []
        
        sessions = self._sessions[symbol]
        # Sort by date descending
        sorted_sessions = sorted(
            sessions,
            key=lambda s: s.session_date,
            reverse=True,
        )
        
        return sorted_sessions[:count]

    def get_session_history(self, symbol: str) -> List[object]:
        """
        Get all session history.
        
        Args:
            symbol: Instrument symbol
            
        Returns:
            List of all profiles
        """
        return self._sessions.get(symbol, [])

    def get_session_count(self) -> int:
        """Get total number of stored sessions."""
        return sum(len(sessions) for sessions in self._sessions.values())

    def create_rolling_profile(
        self,
        symbol: str,
        lookback: int = 5,
    ) -> Optional[object]:
        """
        Create rolling profile from recent sessions.
        
        Args:
            symbol: Instrument symbol
            lookback: Number of sessions to include
            
        Returns:
            Combined profile or None
        """
        recent = self.get_recent_sessions(symbol, lookback)
        if not recent:
            return None
        
        # Return the most recent as placeholder
        # In real implementation, would combine all
        return recent[0]

    def get_average_poc(
        self,
        symbol: str,
        lookback: int = 5,
    ) -> Optional[float]:
        """
        Get average POC across recent sessions.
        
        Args:
            symbol: Instrument symbol
            lookback: Number of sessions
            
        Returns:
            Average POC price or None
        """
        recent = self.get_recent_sessions(symbol, lookback)
        if not recent:
            return None
        
        pocs = []
        for session in recent:
            if hasattr(session, 'poc_price') and session.poc_price > 0:
                pocs.append(session.poc_price)
        
        if not pocs:
            return None
        
        return sum(pocs) / len(pocs)
