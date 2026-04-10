"""LVN/HVN Detector — Low/High Volume Node detection with persistence tracking.

LVN: Volume < 15% of mean → rejection zone, price moves fast through these
HVN: Volume > 200% of mean → acceptance zone, price tends to consolidate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from appv2.config import constants as C


@dataclass(frozen=True)
class LVNLevel:
    price: float
    volume: float
    persistence: int  # Bars since first detected
    is_active: bool


@dataclass(frozen=True)
class HVNLevel:
    price: float
    volume: float
    persistence: int
    is_active: bool


class LVNPersistenceTracker:
    """Tracks LVN/HVN persistence to prevent flickering (appearing/disappearing).

    A level must persist for N consecutive bars before being considered valid.
    Once valid, it remains active even if volume temporarily changes.
    """

    def __init__(
        self,
        min_persistence: int = C.LVN_MIN_PERSISTENCE_BARS,
        lvn_threshold: float = C.LVN_THRESHOLD,
        hvn_threshold: float = C.HVN_THRESHOLD,
    ):
        self._min_persistence = min_persistence
        self._lvn_threshold = lvn_threshold
        self._hvn_threshold = hvn_threshold
        self._lvn_registry: dict[float, int] = {}  # price → persistence count
        self._hvn_registry: dict[float, int] = {}

    def update(self, profile: list) -> tuple[list[LVNLevel], list[HVNLevel]]:
        """Update LVN/HVN levels from volume profile.

        Returns:
            (list of active LVN levels, list of active HVN levels)
        """
        if not profile:
            return [], []

        total_vol = sum(p.volume for p in profile)
        mean_vol = total_vol / len(profile) if profile else 0
        if mean_vol <= 0:
            return [], []

        # Identify current LVN/HVN prices
        current_lvns = set()
        current_hvns = set()

        for p in profile:
            vol_ratio = p.volume / mean_vol
            if vol_ratio < self._lvn_threshold:
                current_lvns.add(p.price)
            elif vol_ratio > self._hvn_threshold:
                current_hvns.add(p.price)

        # Update persistence counters
        for price in current_lvns:
            self._lvn_registry[price] = self._lvn_registry.get(price, 0) + 1
        for price in list(self._lvn_registry.keys()):
            if price not in current_lvns:
                self._lvn_registry[price] = 0  # Reset on disappearance

        for price in current_hvns:
            self._hvn_registry[price] = self._hvn_registry.get(price, 0) + 1
        for price in list(self._hvn_registry.keys()):
            if price not in current_hvns:
                self._hvn_registry[price] = 0

        # Build active levels
        lvn_levels = []
        for price, persistence in self._lvn_registry.items():
            is_active = persistence >= self._min_persistence
            vol = next((p.volume for p in profile if p.price == price), 0)
            lvn_levels.append(LVNLevel(
                price=price, volume=vol, persistence=persistence, is_active=is_active,
            ))

        hvn_levels = []
        for price, persistence in self._hvn_registry.items():
            is_active = persistence >= self._min_persistence
            vol = next((p.volume for p in profile if p.price == price), 0)
            hvn_levels.append(HVNLevel(
                price=price, volume=vol, persistence=persistence, is_active=is_active,
            ))

        return sorted(lvn_levels, key=lambda x: x.price), sorted(hvn_levels, key=lambda x: x.price)

    def reset(self) -> None:
        self._lvn_registry.clear()
        self._hvn_registry.clear()
