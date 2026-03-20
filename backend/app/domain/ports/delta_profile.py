"""Port for Delta Volume Profile — domain-to-infrastructure boundary.

Per Fabio methodology, delta-colored volume profiles show buy_delta vs sell_delta
per price level. High sell delta zones (trapped sellers) = LONG entry zones.
High buy delta zones (trapped buyers) = SHORT entry zones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DeltaBucket:
    """A single price level with delta breakdown."""

    price: float
    buy_delta: int  # Aggressive buyers (trades at ask)
    sell_delta: int  # Aggressive sellers (trades at bid)
    net_delta: int  # buy_delta - sell_delta
    total_volume: int  # buy_delta + sell_delta


@dataclass(frozen=True)
class DeltaProfile:
    """Complete delta volume profile result."""

    buckets: tuple[DeltaBucket, ...]
    poc: float  # Point of Control (highest volume price)
    vah: float  # Value Area High
    val: float  # Value Area Low
    high_sell_delta_zones: tuple[float, ...]  # Trapped sellers = LONG entry zones
    high_buy_delta_zones: tuple[float, ...]  # Trapped buyers = SHORT entry zones


class DeltaProfilePort(ABC):
    """Interface for delta-colored volume profile computation.

    Per Fabio methodology, delta profiles show the net buying/selling pressure
    at each price level. This is fundamentally different from plain volume profiles.

    Key insight: High sell delta zones in the left side of a leg profile indicate
    trapped sellers who will need to cover = LONG entry signal.
    """

    @abstractmethod
    def update(self, price: float, ask_vol: int, bid_vol: int) -> None:
        """Update the profile with a single tick.

        Args:
            price: Trade price.
            ask_vol: Volume at ask (aggressive buyers).
            bid_vol: Volume at bid (aggressive sellers).
        """

    @abstractmethod
    def get_profile(self) -> list[DeltaBucket]:
        """Return the current delta profile as a list of buckets."""

    @abstractmethod
    def get_high_delta_zones(self, direction: str, sigma_mult: float = 2.5) -> list[float]:
        """Detect high delta zones for entry signal generation.

        Args:
            direction: "LONG" (find high sell delta) or "SHORT" (find high buy delta).
            sigma_mult: Threshold multiplier (default 2.5 = 250% of mean).

        Returns:
            List of price levels with high delta concentration.
        """

    @abstractmethod
    def reset(self) -> None:
        """Clear all profile state (e.g., at session open)."""