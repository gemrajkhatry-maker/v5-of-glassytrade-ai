"""Profile factory and lightweight profile bucket containers."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.trading.model.value_objects import VolumeProfileLevel


@dataclass
class _SimpleIncrementalProfile:
    bucket_size: float = 0.05
    buckets: int = 200
    volume_by_level: dict[float, float] = field(default_factory=dict)

    def update(self, candle) -> None:
        price = float(getattr(candle, "close", 0.0))
        vol = float(getattr(candle, "volume", 0.0))
        bucket = round(price / self.bucket_size) * self.bucket_size
        self.volume_by_level[bucket] = self.volume_by_level.get(bucket, 0.0) + vol

    def get_profile(self) -> tuple[VolumeProfileLevel, ...]:
        levels = []
        max_vol = max(self.volume_by_level.values(), default=1.0)
        for price, vol in self.volume_by_level.items():
            weight = vol / max_vol if max_vol else 0.0
            buy = vol * weight
            sell = vol * (1 - weight) if vol > 0 else 0.0
            levels.append(VolumeProfileLevel(price=price, volume=vol, buy_volume=buy, sell_volume=sell))
        return tuple(levels)


class IncrementalProfileFactory:
    def __init__(self, bucket_size: float = 0.05, buckets: int = 200) -> None:
        self._bucket_size = bucket_size
        self._buckets = buckets
        self._creation_count = 0

    def create(self, underlying: str):
        self._creation_count += 1
        return _SimpleIncrementalProfile(bucket_size=self._bucket_size, buckets=self._buckets)

    @property
    def bucket_size(self) -> float:
        return self._bucket_size

    @property
    def buckets(self) -> int:
        return self._buckets

    @property
    def total_engines_created(self) -> int:
        return self._creation_count
