"""Profile selection policy for AMT confluence."""
from __future__ import annotations

from enum import Enum

from app.domain.trading.model.enums import MarketState


class ProfileType(str, Enum):
    SESSION = "SESSION"
    LEG = "LEG"
    COMBINED = "COMBINED"


class ProfileSelector:
    def select(self, market_state: MarketState | str, has_displacement: bool, leg_lvns: list[float], session_lvns: list[float]) -> ProfileType:
        state = str(market_state).upper()
        if state in {"IMBALANCED", "MARKETSTATE.IMBALANCED"} and has_displacement and leg_lvns:
            if self._has_confluence(leg_lvns, session_lvns):
                return ProfileType.COMBINED
            return ProfileType.LEG
        return ProfileType.SESSION

    def _has_confluence(self, leg_lvns: list[float], session_levels: list[float]) -> bool:
        if not leg_lvns or not session_levels:
            return False
        for lvn in leg_lvns:
            for level in session_levels:
                if level > 0 and abs(lvn - level) < level * 0.02:
                    return True
        return False
