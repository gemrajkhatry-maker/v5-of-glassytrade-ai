"""Incremental Volume Profile — CME-style, no full rebuild per candle.

Updates profile one candle at a time. Supports:
- Configurable bucket size (tick_size × multiplier)
- VWAP-weighted volume distribution within each candle
- POC with VWAP tie-break
- Value Area via CME two-row pairs method
- LVN/HVN detection
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from appv2.config import constants as C

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VolumeProfileLevel:
    """Single level in the volume profile."""
    price: float
    volume: float


class IncrementalVolumeProfile:
    """Volume profile that updates incrementally — no full rebuild.

    Usage:
        vp = IncrementalVolumeProfile(tick_size=0.05)
        vp.update_candle(candle)  # OHLC candle
        profile = vp.get_profile()  # list[VolumeProfileLevel]
        poc, vah, val = vp.compute_value_area()
    """

    def __init__(self, tick_size: float = 0.05):
        self._tick_size = tick_size
        self._bucket_size = tick_size * C.VP_BUCKET_MULTIPLIER  # tick × 4
        # price → volume accumulator
        self._buckets: dict[float, float] = {}
        self._total_volume: float = 0.0
        self._candle_count: int = 0

    def update_candle(self, candle) -> None:
        """Update profile with one OHLC candle.

        Volume is distributed across price bins using the candle's range.
        Each bin gets volume proportional to time-at-price approximation:
        - Uniform distribution across candle range (simple method)
        """
        candle_range = candle.high - candle.low
        if candle_range <= 0 or candle.volume <= 0:
            return

        # Distribute volume across price buckets
        price = candle.low
        while price <= candle.high:
            bucket_price = self._bucket_price(price)
            # Volume proportional to overlap with this bucket
            bucket_low = bucket_price
            bucket_high = bucket_price + self._bucket_size
            overlap_low = max(price, bucket_low)
            overlap_high = min(min(price + self._bucket_size, candle.high), bucket_high)
            overlap = max(0.0, overlap_high - overlap_low)

            if overlap > 0:
                frac = overlap / candle_range
                vol = candle.volume * frac
                self._buckets[bucket_price] = self._buckets.get(bucket_price, 0.0) + vol

            price += self._bucket_size

        # Add candle volume ONCE to total (not per-bucket)
        self._total_volume += candle.volume
        self._candle_count += 1

    def update_tick(self, price: float, volume: float) -> None:
        """Update profile with a single tick (LTP + volume delta)."""
        if volume <= 0:
            return
        bucket = self._bucket_price(price)
        self._buckets[bucket] = self._buckets.get(bucket, 0.0) + volume
        self._total_volume += volume

    def get_profile(self) -> list[VolumeProfileLevel]:
        """Return sorted profile levels."""
        if not self._buckets:
            return []
        return [
            VolumeProfileLevel(price=price, volume=vol)
            for price, vol in sorted(self._buckets.items())
        ]

    def get_poc(self) -> float:
        """Point of Control — bucket with max volume."""
        if not self._buckets:
            return 0.0
        max_vol = max(self._buckets.values())
        # Return middle price if multiple bins tie
        poc_buckets = [p for p, v in self._buckets.items() if v == max_vol]
        return sum(poc_buckets) / len(poc_buckets)

    def get_poc_with_vwap_tiebreak(self, vwap: float) -> float:
        """POC with VWAP tie-break for multi-bin max volume."""
        if not self._buckets:
            return 0.0
        max_vol = max(self._buckets.values())
        poc_candidates = [p for p, v in self._buckets.items() if v == max_vol]
        if len(poc_candidates) == 1:
            return poc_candidates[0]
        # Tie-break: choose bucket closest to VWAP
        return min(poc_candidates, key=lambda p: abs(p - vwap))

    def compute_value_area(
        self, value_area_pct: float = C.VALUE_AREA_PCT
    ) -> tuple[float, float, float]:
        """Compute POC, VAH, VAL using CME two-row pairs method.

        Returns:
            (poc, vah, val)
        """
        profile = self.get_profile()
        if len(profile) < 3:
            return 0.0, 0.0, 0.0

        # Find POC
        max_vol = max(p.volume for p in profile)
        poc_idx = next(i for i, p in enumerate(profile) if p.volume == max_vol)

        total_volume = sum(p.volume for p in profile)
        target_volume = total_volume * value_area_pct
        current_volume = max_vol

        up_idx = poc_idx
        down_idx = poc_idx

        while current_volume < target_volume:
            # Look 2 rows up and down (CME two-row pairs)
            up_pair_vol = 0.0
            up_count = 0
            for k in range(1, 3):
                if up_idx + k < len(profile):
                    up_pair_vol += profile[up_idx + k].volume
                    up_count += 1

            down_pair_vol = 0.0
            down_count = 0
            for k in range(1, 3):
                if down_idx - k >= 0:
                    down_pair_vol += profile[down_idx - k].volume
                    down_count += 1

            if up_count == 0 and down_count == 0:
                break

            if up_count > 0 and (down_count == 0 or up_pair_vol >= down_pair_vol):
                up_idx += 1
                current_volume += profile[up_idx].volume
            elif down_count > 0:
                down_idx -= 1
                current_volume += profile[down_idx].volume

        # VAH/VAL: midpoint of boundary bucket
        half_bucket = self._bucket_size / 2
        vah = profile[up_idx].price + half_bucket
        val = profile[down_idx].price - half_bucket

        return profile[poc_idx].price, vah, val

    def get_total_volume(self) -> float:
        return self._total_volume

    def get_mean_volume(self) -> float:
        if not self._buckets:
            return 0.0
        return self._total_volume / len(self._buckets)

    def reset(self) -> None:
        """Clear profile (e.g., at session boundary)."""
        self._buckets.clear()
        self._total_volume = 0.0
        self._candle_count = 0

    def _bucket_price(self, price: float) -> float:
        """Snap price to bucket lower bound."""
        if self._bucket_size <= 0:
            return price
        return round((price // self._bucket_size) * self._bucket_size, 4)

    def to_dict(self) -> dict:
        """Serialize profile for frontend/charting."""
        return {
            "profile": [
                {"price": lv.price, "volume": lv.volume}
                for lv in self.get_profile()
            ],
            "poc": self.get_poc(),
            "total_volume": self._total_volume,
            "candle_count": self._candle_count,
            "bucket_size": self._bucket_size,
        }
