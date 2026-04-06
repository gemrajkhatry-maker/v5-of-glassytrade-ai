"""
Profile selector — choose active profile based on market state.

SESSION: Always available
LEG: Active when leg is in progress
COMBINED: Shows confluence between leg LVNs and session levels
"""

from typing import Dict, List, Optional

from src.profile.node_detector import LVN


class ProfileSelector:
    """
    Select which profile is active for trade construction.

    Decision based on market state and leg status.
    """

    @staticmethod
    def select_active(
        market_state: str,
        leg_active: bool,
    ) -> str:
        """
        Select active profile type.

        Args:
            market_state: Current market state (BALANCED, IMBALANCED, etc.)
            leg_active: Whether a leg is currently in progress

        Returns:
            Profile type: "SESSION", "LEG", or "COMBINED"
        """
        # In IMBALANCED state with active leg, prefer leg profile
        if market_state == "IMBALANCED" and leg_active:
            return "LEG"

        # In BALANCED state, use session profile
        if market_state == "BALANCED":
            return "SESSION"

        # Default to session
        return "SESSION"

    @staticmethod
    def get_key_levels(
        session_poc: Optional[float],
        session_vah: Optional[float],
        session_val: Optional[float],
        leg_lvns: List[LVN],
        session_lvns: List[LVN],
    ) -> Dict[str, Optional[float]]:
        """
        Get key levels for trade construction.

        Returns dict with poc, vah, val, and nearest lvn.
        """
        # Find nearest LVN to current price
        all_lvns = leg_lvns + session_lvns
        # Sort by quality score
        all_lvns = sorted(all_lvns, key=lambda x: x.quality_score, reverse=True)

        nearest_lvn = all_lvns[0].price if all_lvns else None

        return {
            "poc": session_poc,
            "vah": session_vah,
            "val": session_val,
            "nearest_lvn": nearest_lvn,
        }

    @staticmethod
    def find_nearest_level(
        price: float,
        levels: Dict[str, Optional[float]],
        tick_size: float,
    ) -> Optional[float]:
        """
        Find the nearest key level to current price.

        Returns the price of the nearest level.
        """
        distances = {}

        for name, level_price in levels.items():
            if level_price is not None:
                distances[name] = abs(price - level_price)

        if not distances:
            return None

        nearest_name = min(distances, key=distances.get)
        return levels[nearest_name]