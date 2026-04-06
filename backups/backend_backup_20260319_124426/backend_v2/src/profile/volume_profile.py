"""
Volume profile engine — session + leg + delta profiles.

O(1) incremental bucket updates per tick.
"""

from typing import Dict, List, Optional, Tuple

from src.config.engine_config import CFG
from src.core.tick_processor import Tick, price_to_bucket


class VolumeProfileEngine:
    """
    Volume profile management with O(1) updates.

    Maintains session profile, leg profile, and delta profile.
    """

    def __init__(self, bucket_size: float):
        self._bucket_size = bucket_size

    def update_bucket(
        self,
        profile: Dict[float, int],
        price: float,
        volume: int,
    ) -> None:
        """O(1) incremental bucket update."""
        bucket = price_to_bucket(price, self._bucket_size)
        profile[bucket] = profile.get(bucket, 0) + volume

    def update_delta_bucket(
        self,
        delta_profile: Dict[float, Dict[str, int]],
        price: float,
        bid_vol: int,
        ask_vol: int,
    ) -> None:
        """Update delta profile with bid/ask volumes."""
        bucket = price_to_bucket(price, self._bucket_size)
        if bucket not in delta_profile:
            delta_profile[bucket] = {"buy_delta": 0, "sell_delta": 0, "net_delta": 0}

        delta_profile[bucket]["buy_delta"] += ask_vol
        delta_profile[bucket]["sell_delta"] += bid_vol
        delta_profile[bucket]["net_delta"] += (ask_vol - bid_vol)

    def get_poc(self, profile: Dict[float, int]) -> Optional[float]:
        """
        Calculate Point of Control.

        POC = price bucket with maximum cumulative volume.
        """
        if not profile:
            return None
        return max(profile, key=profile.get)

    def get_value_area(
        self,
        profile: Dict[float, int],
        poc: float,
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate Value Area (VAH/VAL) via 70% expansion from POC.

        Returns (VAH, VAL).
        """
        if not profile:
            return None, None

        total_vol = sum(profile.values())
        target_vol = total_vol * CFG.value_area_pct

        # Start from POC
        poc_bucket = price_to_bucket(poc, self._bucket_size)
        va_vol = profile.get(poc_bucket, 0)
        vah = poc
        val = poc

        # Expand alternately up and down
        sorted_buckets = sorted(profile.keys())
        poc_idx = sorted_buckets.index(poc_bucket) if poc_bucket in sorted_buckets else 0

        up_idx = poc_idx + 1
        down_idx = poc_idx - 1

        # Track if we've expanded in each direction
        expanded_up = False
        expanded_down = False

        while va_vol < target_vol or not (expanded_up and expanded_down):
            up_vol = profile.get(sorted_buckets[up_idx], 0) if up_idx < len(sorted_buckets) else 0
            down_vol = profile.get(sorted_buckets[down_idx], 0) if down_idx >= 0 else 0

            # Expand in direction of higher volume, but ensure both directions are tried
            if up_vol >= down_vol and up_idx < len(sorted_buckets):
                va_vol += up_vol
                vah = sorted_buckets[up_idx]
                up_idx += 1
                expanded_up = True
            elif down_idx >= 0:
                va_vol += down_vol
                val = sorted_buckets[down_idx]
                down_idx -= 1
                expanded_down = True
            else:
                break

        return vah, val

    def get_delta_profile(
        self,
        delta_profile: Dict[float, Dict[str, int]],
    ) -> Dict[float, Dict[str, int]]:
        """Get the delta profile."""
        return delta_profile

    def calculate_atr(self, candles: list, period: int = 14) -> float:
        """
        Calculate Average True Range.

        ATR = average of True Range over N periods.
        """
        if len(candles) < 2:
            return 0.0

        true_ranges = []
        for i in range(1, min(len(candles), period + 1)):
            candle = candles[i]
            prev_close = candles[i - 1].close

            high_low = candle.high - candle.low
            high_close = abs(candle.high - prev_close)
            low_close = abs(candle.low - prev_close)

            tr = max(high_low, high_close, low_close)
            true_ranges.append(tr)

        if not true_ranges:
            return 0.0

        return sum(true_ranges) / len(true_ranges)

    def calculate_avg_volume(self, candles: list, period: int = 20) -> float:
        """
        Calculate average volume over N periods.
        """
        if not candles:
            return 0.0

        recent = candles[-period:] if len(candles) >= period else candles
        volumes = [c.volume for c in recent]

        return sum(volumes) / len(volumes) if volumes else 0.0

    def calculate_avg_trade_size(self, ticks: list, period: int = 20) -> float:
        """
        Calculate average trade size over N recent ticks.
        """
        if not ticks:
            return 0.0

        recent = ticks[-period:] if len(ticks) >= period else ticks
        sizes = [t.trade_size for t in recent if t.trade_size > 0]

        return sum(sizes) / len(sizes) if sizes else 0.0