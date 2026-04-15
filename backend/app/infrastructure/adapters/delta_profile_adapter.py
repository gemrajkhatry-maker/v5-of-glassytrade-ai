"""DeltaProfileAdapter — Infrastructure adapter for delta volume profile.

Implements IDeltaProfile with O(1) per tick incremental updates.
Maintains per-bucket buy/sell delta accumulators and computes high delta zones.

Per Fabio methodology:
- High sell delta zones (net_delta very negative) = trapped sellers = LONG entry
- High buy delta zones (net_delta very positive) = trapped buyers = SHORT entry
"""

from __future__ import annotations

import logging
from app.domain.ports.delta_profile import IDeltaProfile, DeltaBucket, DeltaProfile
from app.domain.constants import DELTA_ZONE_SIGMA_MULT, DELTA_BUCKET_SIZE_DEFAULT

logger = logging.getLogger(__name__)


class DeltaProfileAdapter(IDeltaProfile):
    """Delta-colored volume profile with O(1) per tick updates.

    DI pattern: Port (ABC) → Adapter (this class) → ServiceGraph injection.

    Each bucket maintains:
    - buy_delta: aggressive buyers (trades at ask)
    - sell_delta: aggressive sellers (trades at bid)
    - net_delta: buy_delta - sell_delta
    - total_volume: buy_delta + sell_delta
    """

    def __init__(self, bucket_size: float = DELTA_BUCKET_SIZE_DEFAULT) -> None:
        self._bucket_size = bucket_size
        # Per-bucket accumulators: price -> [buy_delta, sell_delta, net_delta, total_volume]
        self._buckets: dict[float, list[int]] = {}

    def update(self, price: float, ask_vol: int, bid_vol: int) -> None:
        """O(1) per tick — incremental bucket update.

        Args:
            price: Trade price.
            ask_vol: Volume at ask (aggressive buyers).
            bid_vol: Volume at bid (aggressive sellers).
        """
        if price <= 0:
            return

        bucket = round(price / self._bucket_size) * self._bucket_size

        if bucket not in self._buckets:
            self._buckets[bucket] = [0, 0, 0, 0]  # [buy, sell, net, total]

        delta = ask_vol - bid_vol
        self._buckets[bucket][0] += ask_vol
        self._buckets[bucket][1] += bid_vol
        self._buckets[bucket][2] += delta
        self._buckets[bucket][3] += ask_vol + bid_vol

    def get_profile(self) -> list[DeltaBucket]:
        """Return the current delta profile as a list of buckets."""
        if not self._buckets:
            return []

        return [
            DeltaBucket(
                price=price,
                buy_delta=data[0],
                sell_delta=data[1],
                net_delta=data[2],
                total_volume=data[3],
            )
            for price, data in sorted(self._buckets.items())
        ]

    def get_high_delta_zones(self, direction: str, sigma_mult: float = DELTA_ZONE_SIGMA_MULT) -> list[float]:
        """Detect high delta zones for entry signal generation.

        Per Fabio methodology:
        - LONG entry: find levels with very high SELL delta (net_delta very negative)
          = trapped sellers who will need to cover = buyers will appear on retest
        - SHORT entry: find levels with very high BUY delta (net_delta very positive)
          = trapped buyers who will need to sell = sellers will appear on retest

        Args:
            direction: "LONG" (find high sell delta) or "SHORT" (find high buy delta).
            sigma_mult: Threshold multiplier (default 2.5 = 250% of mean).

        Returns:
            List of price levels with high delta concentration, sorted by absolute delta.
        """
        if not self._buckets:
            return []

        # Compute mean absolute net delta across all buckets
        net_deltas = [abs(data[2]) for data in self._buckets.values() if data[3] > 0]
        if not net_deltas:
            return []

        mean_abs = sum(net_deltas) / len(net_deltas)
        threshold = mean_abs * sigma_mult

        zones = []
        for price, data in self._buckets.items():
            net = data[2]
            if direction == "LONG" and net < -threshold:
                # High sell delta = trapped sellers = LONG entry zone
                zones.append(price)
            elif direction == "SHORT" and net > threshold:
                # High buy delta = trapped buyers = SHORT entry zone
                zones.append(price)

        return sorted(zones)

    def get_delta_at_price(self, price: float) -> tuple[int, int, int]:
        """Get buy_delta, sell_delta, net_delta at a specific price level.

        Args:
            price: The price level to query.

        Returns:
            Tuple of (buy_delta, sell_delta, net_delta).
        """
        bucket = round(price / self._bucket_size) * self._bucket_size
        data = self._buckets.get(bucket, [0, 0, 0, 0])
        return data[0], data[1], data[2]

    def reset(self) -> None:
        """Clear all profile state (e.g., at session open)."""
        self._buckets.clear()
        logger.debug("Delta profile reset")

    @property
    def bucket_size(self) -> float:
        return self._bucket_size

    @property
    def bucket_count(self) -> int:
        return len(self._buckets)

    @property
    def total_volume(self) -> int:
        """Total volume across all buckets."""
        return sum(data[3] for data in self._buckets.values())