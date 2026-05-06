"""DeltaProfileAdapter — infrastructure adapter for delta profile computation."""

from __future__ import annotations

import logging
import statistics

from app.domain.shared.port.delta_profile import IDeltaProfile, DeltaBucket
from app.domain.constants import DELTA_ZONE_SIGMA_MULT, DELTA_BUCKET_SIZE_DEFAULT

logger = logging.getLogger(__name__)


def _detect_high_delta_zones(
    buckets: dict[float, list[int]],
    direction: str,
    sigma_mult: float = DELTA_ZONE_SIGMA_MULT,
) -> list[float]:
    """Detect high delta levels from raw bucket statistics."""
    if not buckets:
        return []

    deltas = [data[2] for data in buckets.values()]
    if len(deltas) < 2:
        return []

    mean_delta = statistics.fmean(deltas)
    stdev = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
    if stdev == 0.0:
        stdev = 1.0

    threshold = abs(sigma_mult * stdev)
    target = "SELL" if direction.upper() == "LONG" else "BUY"

    level_sign = -1 if target == "SELL" else 1
    return [
        price
        for price, data in buckets.items()
        if (data[2] * level_sign) <= -threshold
    ]


class DeltaProfileAdapter(IDeltaProfile):
    """Tracks delta by price bucket and returns high-delta zones."""

    def __init__(self, bucket_size: float = DELTA_BUCKET_SIZE_DEFAULT) -> None:
        self._bucket_size = bucket_size
        self._buckets: dict[float, list[int]] = {}

    def update(self, price: float, ask_vol: int, bid_vol: int) -> None:
        if price <= 0:
            return

        bucket = round(price / self._bucket_size) * self._bucket_size
        bucket_data = self._buckets.setdefault(bucket, [0, 0, 0, 0])
        delta = int(ask_vol - bid_vol)
        bucket_data[0] += int(ask_vol)
        bucket_data[1] += int(bid_vol)
        bucket_data[2] += delta
        bucket_data[3] += int(ask_vol + bid_vol)

    def get_profile(self) -> list[DeltaBucket]:
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
        if not self._buckets:
            return []
        return _detect_high_delta_zones(self._buckets, direction=direction, sigma_mult=sigma_mult)

    def get_delta_at_price(self, price: float) -> tuple[int, int, int]:
        bucket = round(price / self._bucket_size) * self._bucket_size
        data = self._buckets.get(bucket, [0, 0, 0, 0])
        return data[0], data[1], data[2]

    def reset(self) -> None:
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
        return sum(data[3] for data in self._buckets.values())
