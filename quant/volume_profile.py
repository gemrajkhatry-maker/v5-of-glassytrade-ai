"""Volume profile — uniform distribution across [low, high], POC, average-weighted
CME two-row value area (70%)."""

from __future__ import annotations

from dataclasses import dataclass

from quant.bars import Bar


@dataclass(frozen=True)
class VolumeProfileLevel:
    price: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0


@dataclass(frozen=True)
class VolumeProfile:
    levels: tuple[VolumeProfileLevel, ...]
    poc: float
    vah: float
    val: float
    step: float
    total_volume: float


class VolumeProfileBuilder:
    """Accumulates bars; ``snapshot()`` rebuilds the profile from all stored bars."""

    def __init__(self, buckets: int = 0, tick_size: float = 0.0) -> None:
        self._buckets = buckets
        self._tick_size = tick_size
        self._candles: list[Bar] = []

    def update(self, bar: Bar) -> None:
        self._candles.append(bar)

    def snapshot(self) -> VolumeProfile:
        candles = self._candles
        if not candles:
            return VolumeProfile(levels=(), poc=0.0, vah=0.0, val=0.0,
                                 step=0.0, total_volume=0.0)

        min_price = float(min(c.low for c in candles))
        max_price = float(max(c.high for c in candles))
        price_range = max_price - min_price

        if price_range <= 0:
            total = float(sum(c.volume for c in candles))
            level = VolumeProfileLevel(price=float(candles[0].close), volume=total)
            return VolumeProfile(levels=(level,), poc=level.price,
                                 vah=level.price, val=level.price,
                                 step=1.0, total_volume=total)

        buckets = self._buckets
        if buckets <= 0:
            tick = self._tick_size
            if tick <= 0:
                prices = sorted(set(float(c.close) for c in candles[-50:]))
                diffs = [b - a for a, b in zip(prices, prices[1:]) if b > a]
                tick = min(diffs) if diffs else 0.05
            buckets = max(100, min(int(price_range / tick), 1000))

        step = price_range / buckets
        volumes = [0.0] * buckets
        buy_vols = [0.0] * buckets
        sell_vols = [0.0] * buckets

        for c in candles:
            vol = float(c.volume)
            if vol <= 0:
                continue
            start = int((float(c.low) - min_price) / step)
            end = int((float(c.high) - min_price) / step)
            start = max(0, min(buckets - 1, start))
            end = max(0, min(buckets - 1, end))
            n = end - start + 1
            per = vol / n
            buy_per = float(c.buy_volume) / n
            sell_per = float(c.sell_volume) / n
            for i in range(start, end + 1):
                volumes[i] += per
                buy_vols[i] += buy_per
                sell_vols[i] += sell_per

        levels = tuple(
            VolumeProfileLevel(
                price=min_price + i * step + step / 2,
                volume=volumes[i],
                buy_volume=buy_vols[i],
                sell_volume=sell_vols[i],
            )
            for i in range(buckets)
        )

        total_volume = float(sum(volumes))
        poc_idx = max(range(buckets), key=lambda i: volumes[i])
        poc = levels[poc_idx].price

        vah, val = self._value_area(levels, volumes, poc_idx, step, total_volume)

        return VolumeProfile(levels=levels, poc=poc, vah=vah, val=val,
                             step=step, total_volume=total_volume)

    @staticmethod
    def _value_area(levels, volumes, poc_idx, step, total_volume):
        target = total_volume * 0.70
        current = volumes[poc_idx]
        up_idx = down_idx = poc_idx
        n_buckets = len(volumes)

        while current < target:
            up_sum = 0.0
            up_count = 0
            for k in (1, 2):
                if up_idx + k < n_buckets:
                    up_sum += volumes[up_idx + k]
                    up_count += 1
            down_sum = 0.0
            down_count = 0
            for k in (1, 2):
                if down_idx - k >= 0:
                    down_sum += volumes[down_idx - k]
                    down_count += 1

            if up_count == 0 and down_count == 0:
                break

            up_avg = up_sum / up_count if up_count else 0.0
            down_avg = down_sum / down_count if down_count else 0.0

            if up_count and (down_count == 0 or up_avg >= down_avg):
                for _ in range(up_count):
                    up_idx += 1
                    current += volumes[up_idx]
            elif down_count:
                for _ in range(down_count):
                    down_idx -= 1
                    current += volumes[down_idx]

        half = step / 2
        return levels[up_idx].price + half, levels[down_idx].price - half
