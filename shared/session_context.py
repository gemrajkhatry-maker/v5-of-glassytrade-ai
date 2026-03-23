"""Session context service for consistent session info retrieval.

This module centralizes session information retrieval, eliminating
duplication across handlers and services.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

logger = logging.getLogger(__name__)

# IST timezone constant
IST = timezone(timedelta(hours=5, minutes=30))


class SessionContext:
    """Centralized session context provider.
    
    Provides consistent session information across all handlers and services.
    """
    
    def __init__(self, market: str = "NSE"):
        self._market = market
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 60  # Cache for 60 seconds
        self._last_update = 0
    
    def get_session_info(
        self,
        timestamp: str | datetime | None = None,
        open_price: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
    ) -> Dict[str, Any]:
        """Get session information for the given timestamp.
        
        Args:
            timestamp: Current timestamp (ISO string or datetime)
            open_price: Current session open price
            prior_vah: Prior session VAH
            prior_val: Prior session VAL
        
        Returns:
            Dictionary containing session information
        """
        # Normalize timestamp
        if timestamp is None:
            dt = datetime.now(IST)
        elif isinstance(timestamp, str):
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.now(IST)
        else:
            dt = timestamp
        
        # Convert to IST if needed
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_ist = dt.astimezone(IST)
        
        # Determine session phase
        session_phase = self._get_session_phase(dt_ist)
        
        # Get strategy hints
        strategy_hints = self._get_strategy_hints(session_phase)
        
        return {
            "session": session_phase,
            "timestamp": dt_ist.isoformat(),
            "market": self._market,
            "open_price": open_price,
            "prior_vah": prior_vah,
            "prior_val": prior_val,
            "allow_entry": strategy_hints["allow_entry"],
            "allow_trend": strategy_hints["allow_trend"],
            "allow_reversion": strategy_hints["allow_reversion"],
            "favor_strategy": strategy_hints["favor_strategy"],
            "opening_relation": self._get_opening_relation(
                open_price, prior_vah, prior_val
            ),
        }
    
    def _get_session_phase(self, dt: datetime) -> str:
        """Determine session phase based on time.
        
        NSE Session Phases (IST):
        - 09:15-09:30: Opening Auction
        - 09:30-11:30: Primary Setup Window
        - 11:30-14:00: Midday Consolidation
        - 14:00-15:15: Power Hour
        - 15:15-15:30: Closing Auction
        """
        hour = dt.hour
        minute = dt.minute
        
        # Convert to minutes since midnight
        time_minutes = hour * 60 + minute
        
        # NSE timings (in minutes)
        if time_minutes < 555:  # Before 09:15
            return "PRE_MARKET"
        elif time_minutes < 570:  # 09:15-09:30
            return "OPENING_AUCTION"
        elif time_minutes < 690:  # 09:30-11:30
            return "PRIMARY_WINDOW"
        elif time_minutes < 840:  # 11:30-14:00
            return "MIDDAY_CONSOLIDATION"
        elif time_minutes < 915:  # 14:00-15:15
            return "POWER_HOUR"
        elif time_minutes < 930:  # 15:15-15:30
            return "CLOSING_AUCTION"
        else:
            return "POST_MARKET"
    
    def _get_strategy_hints(self, session_phase: str) -> Dict[str, Any]:
        """Get strategy hints based on session phase."""
        hints = {
            "PRE_MARKET": {
                "allow_entry": False,
                "allow_trend": False,
                "allow_reversion": False,
                "favor_strategy": "NONE",
            },
            "OPENING_AUCTION": {
                "allow_entry": False,
                "allow_trend": False,
                "allow_reversion": False,
                "favor_strategy": "NONE",
            },
            "PRIMARY_WINDOW": {
                "allow_entry": True,
                "allow_trend": True,
                "allow_reversion": True,
                "favor_strategy": "TREND_CONTINUATION",
            },
            "MIDDAY_CONSOLIDATION": {
                "allow_entry": True,
                "allow_trend": False,
                "allow_reversion": True,
                "favor_strategy": "MEAN_REVERSION",
            },
            "POWER_HOUR": {
                "allow_entry": True,
                "allow_trend": True,
                "allow_reversion": True,
                "favor_strategy": "TREND_CONTINUATION",
            },
            "CLOSING_AUCTION": {
                "allow_entry": False,
                "allow_trend": False,
                "allow_reversion": False,
                "favor_strategy": "NONE",
            },
            "POST_MARKET": {
                "allow_entry": False,
                "allow_trend": False,
                "allow_reversion": False,
                "favor_strategy": "NONE",
            },
        }
        return hints.get(session_phase, hints["POST_MARKET"])
    
    def _get_opening_relation(
        self,
        open_price: float,
        prior_vah: float,
        prior_val: float,
    ) -> str:
        """Determine opening relation to prior session value area."""
        if open_price <= 0 or prior_vah <= 0 or prior_val <= 0:
            return "UNKNOWN"
        
        if open_price > prior_vah:
            return "ABOVE_VAH"
        elif open_price < prior_val:
            return "BELOW_VAL"
        else:
            return "INSIDE_VA"


# Singleton instance
_session_context = SessionContext()


def get_session_info(
    timestamp: str | datetime | None = None,
    market: str = "NSE",
    open_price: float = 0.0,
    prior_vah: float = 0.0,
    prior_val: float = 0.0,
) -> Dict[str, Any]:
    """Get session information (convenience function).
    
    This is the primary interface for session info retrieval.
    All handlers should use this function instead of implementing
    their own session logic.
    """
    if market != _session_context._market:
        context = SessionContext(market)
    else:
        context = _session_context
    
    return context.get_session_info(
        timestamp=timestamp,
        open_price=open_price,
        prior_vah=prior_vah,
        prior_val=prior_val,
    )