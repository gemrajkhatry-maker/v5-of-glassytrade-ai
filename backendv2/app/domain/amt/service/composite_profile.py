"""Composite/Multi-Session Profile — Weekly bias calculation per Fabio AMT spec.

Merges last N session profiles to calculate weekly POC/VAH/VAL for bias filtering.
Weekly bias: Only take trades aligned with weekly bias for highest conviction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.domain.constants import HVN_THRESHOLD, LVN_THRESHOLD, VALUE_AREA_PCT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompositeProfileResult:
    """Result of composite profile calculation."""
    profile: dict  # price -> merged volume
    weekly_poc: float
    weekly_vah: float
    weekly_val: float
    weekly_lvns: tuple
    weekly_hvns: tuple
    bias: str  # "LONG" | "SHORT" | "NEUTRAL"
    bias_strength: float  # 0.0 to 1.0


class CompositeProfile:
    """Merges last N session profiles for weekly bias calculation.

    Usage:
        composite = CompositeProfile(window=5)
        result = composite.build(session_profiles)
        bias_result = composite.apply_weekly_bias(direction, current_price, result)
    """

    def __init__(self, window: int = 5):
        self._window = window

    def build(self, session_profiles: list[dict]) -> CompositeProfileResult:
        """Merge sessions into composite profile.

        Args:
            session_profiles: List of session profile dicts from storage.
                Each dict should have 'profile' key with {price: volume} mapping,
                or 'poc', 'vah', 'val' keys for basic merging.

        Returns:
            CompositeProfileResult with merged profile and weekly levels.
        """
        if not session_profiles:
            return self._empty_result()

        # Merge volume profiles from last N sessions
        composite: dict[float, float] = {}
        for session in session_profiles[-self._window:]:
            # Handle both full profile dicts and simple poc/vah/val
            profile_data = session.get("profile", {})
            if profile_data:
                for price_str, vol in profile_data.items():
                    try:
                        price = float(price_str)
                        composite[price] = composite.get(price, 0) + float(vol)
                    except (ValueError, TypeError):
                        continue
            else:
                # Fallback: use poc/vah/val as key levels with synthetic volume
                for key in ("poc", "vah", "val"):
                    level = session.get(key, 0)
                    if level and level > 0:
                        composite[float(level)] = composite.get(float(level), 0) + 100

        if not composite:
            return self._empty_result()

        # Calculate weekly levels
        weekly_poc = self._calc_poc(composite)
        weekly_vah, weekly_val = self._calc_value_area(composite, weekly_poc)
        weekly_lvns = self._find_lvns(composite)
        weekly_hvns = self._find_hvns(composite)

        # Determine bias based on POC position relative to value area center
        va_center = (weekly_vah + weekly_val) / 2 if weekly_vah and weekly_val else weekly_poc
        if weekly_poc > va_center:
            bias = "LONG"
            bias_strength = min(1.0, (weekly_poc - va_center) / (weekly_vah - weekly_val) if weekly_vah != weekly_val else 0.5)
        elif weekly_poc < va_center:
            bias = "SHORT"
            bias_strength = min(1.0, (va_center - weekly_poc) / (weekly_vah - weekly_val) if weekly_vah != weekly_val else 0.5)
        else:
            bias = "NEUTRAL"
            bias_strength = 0.0

        result = CompositeProfileResult(
            profile=composite,
            weekly_poc=weekly_poc,
            weekly_vah=weekly_vah,
            weekly_val=weekly_val,
            weekly_lvns=weekly_lvns,
            weekly_hvns=weekly_hvns,
            bias=bias,
            bias_strength=round(bias_strength, 3),
        )

        logger.info(
            "Composite profile: POC=%.1f VAH=%.1f VAL=%.1f bias=%s (%.2f)",
            weekly_poc, weekly_vah, weekly_val, bias, bias_strength,
        )
        return result

    def apply_weekly_bias(
        self,
        direction: str,
        current_price: float,
        composite: CompositeProfileResult,
    ) -> dict:
        """Filter trade against weekly bias.

        Args:
            direction: "LONG" or "SHORT" — intended trade direction.
            current_price: Current market price.
            composite: Composite profile result.

        Returns:
            Dict with 'aligned' bool and confidence adjustment.
        """
        if composite.weekly_poc <= 0:
            return {"aligned": True, "confidence_adjustment": 0.0}

        # Weekly bias: price above POC = bullish, below = bearish
        weekly_bias = composite.bias

        if direction == weekly_bias:
            return {
                "aligned": True,
                "confidence_adjustment": 0.1 * composite.bias_strength,
                "weekly_bias": weekly_bias,
                "weekly_poc": composite.weekly_poc,
            }
        elif weekly_bias == "NEUTRAL":
            return {
                "aligned": True,
                "confidence_adjustment": 0.0,
                "weekly_bias": weekly_bias,
                "weekly_poc": composite.weekly_poc,
            }
        else:
            return {
                "aligned": False,
                "confidence_adjustment": -0.2 * composite.bias_strength,
                "weekly_bias": weekly_bias,
                "weekly_poc": composite.weekly_poc,
            }

    def _calc_poc(self, profile: dict[float, float]) -> float:
        """Calculate Point of Control (highest volume price)."""
        if not profile:
            return 0.0
        return max(profile.keys(), key=lambda p: profile[p])

    def _calc_value_area(
        self, profile: dict[float, float], poc: float
    ) -> tuple[float, float]:
        """Calculate Value Area High and Low (70% of volume around POC)."""
        if not profile or poc <= 0:
            return 0.0, 0.0

        sorted_prices = sorted(profile.keys())
        total_volume = sum(profile.values())
        target_volume = total_volume * VALUE_AREA_PCT

        # Find POC index
        try:
            poc_idx = sorted_prices.index(poc)
        except ValueError:
            poc_idx = len(sorted_prices) // 2

        # Expand from POC outward until we capture 70% of volume
        accumulated = profile[poc]
        low_idx = poc_idx
        high_idx = poc_idx

        while accumulated < target_volume:
            low_vol = profile.get(sorted_prices[low_idx - 1], 0) if low_idx > 0 else 0
            high_vol = profile.get(sorted_prices[high_idx + 1], 0) if high_idx < len(sorted_prices) - 1 else 0

            if low_vol >= high_vol and low_idx > 0:
                low_idx -= 1
                accumulated += low_vol
            elif high_idx < len(sorted_prices) - 1:
                high_idx += 1
                accumulated += high_vol
            else:
                break

        return sorted_prices[high_idx], sorted_prices[low_idx]

    def _find_lvns(self, profile: dict[float, float]) -> tuple[float, ...]:
        """Find Low Volume Nodes (LVNs) — prices with < 15% of mean volume."""
        if len(profile) < 3:
            return ()

        volumes = list(profile.values())
        mean_vol = sum(volumes) / len(volumes)
        threshold = mean_vol * LVN_THRESHOLD

        lvns = [price for price, vol in profile.items() if vol < threshold]
        return tuple(sorted(lvns))

    def _find_hvns(self, profile: dict[float, float]) -> tuple[float, ...]:
        """Find High Volume Nodes (HVN) — prices with > 200% of mean volume."""
        if len(profile) < 3:
            return ()

        volumes = list(profile.values())
        mean_vol = sum(volumes) / len(volumes)
        threshold = mean_vol * HVN_THRESHOLD

        hvns = [price for price, vol in profile.items() if vol > threshold]
        return tuple(sorted(hvns))

    def _empty_result(self) -> CompositeProfileResult:
        return CompositeProfileResult(
            profile={},
            weekly_poc=0.0,
            weekly_vah=0.0,
            weekly_val=0.0,
            weekly_lvns=(),
            weekly_hvns=(),
            bias="NEUTRAL",
            bias_strength=0.0,
        )
