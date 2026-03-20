"""Profile Selector — SESSION/LEG/COMBINED profile selection per plan (FR-02-11/12).

Selects which volume profile to use for entry decisions:
  SESSION: Standard session profile from open (always available)
  LEG: Filtered Relative Volume Profile for current displacement leg
  COMBINED: Shows confluence between leg LVNs and session levels

Selection logic:
  - IMBALANCED + displacement active → LEG profile (tighter entries)
  - BALANCED → SESSION profile (broader context)
  - LVN near session VAH/VAL/POC → COMBINED bonus (+0.5 aggression)
"""

from __future__ import annotations

import logging
from enum import Enum

from app.domain.trading.models.enums import MarketState

logger = logging.getLogger(__name__)


class ProfileType(str, Enum):
    """Which profile to use for entry targeting."""

    SESSION = "SESSION"
    LEG = "LEG"
    COMBINED = "COMBINED"


class ProfileSelector:
    """Selects active profile type based on market context."""

    def select(
        self,
        market_state: MarketState,
        has_displacement: bool,
        leg_lvns: list[float],
        session_lvns: list[float],
    ) -> ProfileType:
        """Select which profile to use.

        Returns:
            ProfileType indicating which profile is active.
        """
        # IMBALANCED with displacement → use leg profile
        if market_state == MarketState.IMBALANCED and has_displacement and leg_lvns:
            # Check for combined confluence
            has_confluence = self._has_confluence(leg_lvns, session_lvns)
            if has_confluence:
                return ProfileType.COMBINED
            return ProfileType.LEG

        # BALANCED or no displacement → session profile
        return ProfileType.SESSION

    def _has_confluence(
        self,
        leg_lvns: list[float],
        session_levels: list[float],
    ) -> bool:
        """Check if any leg LVN is near a session level (confluence)."""
        if not leg_lvns or not session_levels:
            return False
        for lvn in leg_lvns:
            for level in session_levels:
                if level > 0 and abs(lvn - level) < level * 0.02:  # Within 2%
                    return True
        return False
