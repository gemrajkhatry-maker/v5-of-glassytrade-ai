"""Volume Profile value object.

Encapsulates Point of Control (POC), Value Area High/Low, and related
volume profile data. Extracted from the flat AMTResult dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VolumeProfile:
    """Volume profile for a trading session.

    Attributes:
        poc: Point of Control — price level with highest volume.
        vah: Value Area High — upper bound of 70% value area.
        val: Value Area Low — lower bound of 70% value area.
        lvns: Low Volume Nodes — price gaps with low volume.
        hvns: High Volume Nodes — price levels with high volume.
    """

    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    lvns: tuple[float, ...] = ()
    hvns: tuple[float, ...] = ()

    @property
    def value_area_width(self) -> float:
        """Width of the value area."""
        return self.vah - self.val if self.vah and self.val else 0.0

    @property
    def has_profile(self) -> bool:
        """Whether this profile has meaningful data."""
        return self.poc > 0.0 and self.vah > 0.0 and self.val > 0.0


@dataclass(frozen=True)
class DevelopingVolumeProfile:
    """Short lookback volume profile that adapts fast to large moves."""

    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0


@dataclass(frozen=True)
class LegVolumeProfile:
    """Volume profile for a displacement leg."""

    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    lvns: tuple[float, ...] = ()
