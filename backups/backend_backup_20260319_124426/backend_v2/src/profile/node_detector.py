"""
Node detector — LVN/HVN detection and quality scoring.

LVN: volume < 15% of mean (rejection/weakness)
HVN: volume > 200% of mean (acceptance/strength)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from src.config.engine_config import CFG


@dataclass
class LVN:
    """Low Volume Node."""

    price: float
    volume: int
    thinness_score: float  # 0-1, lower volume = higher score
    proximity_score: float  # 0-1, closer to midpoint = higher score
    quality_score: float  # Combined: thinness 60% + proximity 40%


@dataclass
class HVN:
    """High Volume Node."""

    price: float
    volume: int
    strength_score: float  # 0-1, higher volume = higher score


class NodeDetector:
    """
    Detect Low Volume Nodes and High Volume Nodes in a profile.

    Uses static methods for pure function behavior.
    """

    @staticmethod
    def detect_lvns(
        profile: Dict[float, int],
        threshold: float = CFG.lvn_threshold_pct,
    ) -> List[LVN]:
        """
        Detect LVNs where volume < threshold% of mean.

        Args:
            profile: Volume profile {price: volume}
            threshold: LVN threshold (default 0.15 = 15%)

        Returns:
            List of LVN objects sorted by quality score (descending).
        """
        if not profile:
            return []

        volumes = list(profile.values())
        mean_vol = sum(volumes) / len(volumes) if volumes else 0

        if mean_vol <= 0:
            return []

        lvn_threshold = mean_vol * threshold
        lvns = []

        for price, vol in profile.items():
            if vol < lvn_threshold:
                # Thinness score: lower volume = higher score
                thinness = 1.0 - (vol / lvn_threshold) if lvn_threshold > 0 else 1.0
                thinness = max(0.0, min(1.0, thinness))

                # Proximity score will be calculated later when we have midpoint
                lvns.append(LVN(
                    price=price,
                    volume=vol,
                    thinness_score=thinness,
                    proximity_score=0.5,  # Default, updated later
                    quality_score=thinness * 0.6 + 0.5 * 0.4,  # Default
                ))

        return sorted(lvns, key=lambda x: x.quality_score, reverse=True)

    @staticmethod
    def detect_hvns(
        profile: Dict[float, int],
        threshold: float = CFG.hvn_threshold_pct,
    ) -> List[HVN]:
        """
        Detect HVNs where volume > threshold * mean.

        Args:
            profile: Volume profile {price: volume}
            threshold: HVN threshold (default 2.0 = 200%)

        Returns:
            List of HVN objects sorted by strength score (descending).
        """
        if not profile:
            return []

        volumes = list(profile.values())
        mean_vol = sum(volumes) / len(volumes) if volumes else 0

        if mean_vol <= 0:
            return []

        hvn_threshold = mean_vol * threshold
        hvns = []

        for price, vol in profile.items():
            if vol > hvn_threshold:
                # Strength score: higher volume = higher score
                strength = min(1.0, vol / (hvn_threshold * 2))
                hvns.append(HVN(
                    price=price,
                    volume=vol,
                    strength_score=strength,
                ))

        return sorted(hvns, key=lambda x: x.strength_score, reverse=True)

    @staticmethod
    def score_lvn_quality(
        lvn: LVN,
        profile: Dict[float, int],
        midpoint: float,
    ) -> float:
        """
        Score LVN quality: thinness (60%) + proximity to midpoint (40%).

        Args:
            lvn: LVN to score
            profile: Volume profile
            midpoint: Midpoint price for proximity calculation

        Returns:
            Quality score (0-1).
        """
        if not profile:
            return lvn.quality_score

        # Calculate proximity score
        prices = list(profile.keys())
        price_range = max(prices) - min(prices) if prices else 1.0

        if price_range > 0:
            distance = abs(lvn.price - midpoint)
            proximity = 1.0 - (distance / price_range)
            proximity = max(0.0, min(1.0, proximity))
        else:
            proximity = 0.5

        # Combined quality score
        quality = lvn.thinness_score * 0.6 + proximity * 0.4

        # Update the LVN object
        lvn.proximity_score = proximity
        lvn.quality_score = quality

        return quality

    @staticmethod
    def find_confluence_levels(
        lvns: List[LVN],
        session_levels: Dict[str, Optional[float]],
        proximity_ticks: int = 3,
        tick_size: float = 0.10,
    ) -> List[float]:
        """
        Find confluence levels where LVN coincides with session levels.

        Args:
            lvns: List of LVNs
            session_levels: Dict with 'poc', 'vah', 'val' keys
            proximity_ticks: Maximum ticks for confluence
            tick_size: Tick size for the instrument

        Returns:
            List of confluence price levels.
        """
        confluence = []
        max_distance = proximity_ticks * tick_size

        for lvn in lvns:
            for level_name, level_price in session_levels.items():
                if level_price is not None:
                    if abs(lvn.price - level_price) <= max_distance:
                        confluence.append(lvn.price)
                        break  # Only count once per LVN

        return confluence