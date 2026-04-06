"""VolumeProfileComputer — maintains histogram, computes POC/VAH/VAL.

Single job: maintain volume-at-price histogram from tick/candle data,
compute POC (Point of Control), VAH/VAL (Value Area High/Low) via
CME Two-Row Pairs Method.

Inputs: price, volume per tick/candle; SymbolConfig
Outputs: VolumeProfileSnapshot (POC, VAH, VAL, histogram)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.trading.models.value_objects import OHLC, VolumeProfileLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VolumeProfileSnapshot:
    """Immutable snapshot of volume profile at any point in time."""

    poc: float  # Point of Control price
    vah: float  # Value Area High
    val: float  # Value Area Low
    total_volume: float  # Total volume in profile
    poc_index: int  # Bucket index of POC
    histogram: list[float]  # Volume per bucket


def compute_bucket_index(price: float, price_min: float, bucket_size: float) -> int:
    """Compute bucket index for a given price.

    Formula: bucket_idx = floor((price - price_min) / bucket_size)
    """
    return int((price - price_min) / bucket_size)


def compute_poc(
    profile: list[VolumeProfileLevel],
    vwap_ref: float | None = None,
) -> tuple[float, int]:
    """Compute Point of Control.

    POC = price at bucket with maximum volume.
    If tie (two buckets equal max): select bucket closer to session VWAP.

    Returns:
        (poc_price, poc_index)
    """
    if not profile:
        return 0.0, 0

    max_vol = max(p.volume for p in profile)
    poc_candidates = [i for i, p in enumerate(profile) if p.volume == max_vol]

    if len(poc_candidates) == 1:
        idx = poc_candidates[0]
    elif vwap_ref is not None:
        idx = min(poc_candidates, key=lambda i: abs(profile[i].price - vwap_ref))
    else:
        idx = poc_candidates[0]

    return profile[idx].price, idx


def compute_value_area(
    profile: list[VolumeProfileLevel],
    poc_index: int,
    value_area_pct: float = 0.70,
) -> tuple[float, float]:
    """Compute Value Area High/Low via CME Two-Row Pairs Method.

    START: upper_idx = POC, lower_idx = POC
           va_volume = histogram[POC]
           target = total_volume × value_area_pct

    LOOP while va_volume < target:
      top_add = histogram[upper_idx+1] + histogram[upper_idx+2]
      bot_add = histogram[lower_idx-1] + histogram[lower_idx-2]

      IF top_add >= bot_add:
        upper_idx += 2 (expand up 2 rows)
        va_volume += top_add
      ELSE:
        lower_idx -= 2 (expand down 2 rows)
        va_volume += bot_add

      GUARD: if upper_idx = max OR lower_idx = 0 → break

    Returns:
        (vah, val)
    """
    if not profile:
        return 0.0, 0.0

    total_volume = sum(p.volume for p in profile)
    target_volume = total_volume * value_area_pct

    current_volume = profile[poc_index].volume
    up_idx = poc_index
    down_idx = poc_index

    while current_volume < target_volume:
        # Sum the next TWO rows above (CME standard)
        up_pair = 0.0
        up_count = 0
        for k in range(1, 3):
            if up_idx + k < len(profile):
                up_pair += profile[up_idx + k].volume
                up_count += 1

        # Sum the next TWO rows below
        down_pair = 0.0
        down_count = 0
        for k in range(1, 3):
            if down_idx - k >= 0:
                down_pair += profile[down_idx - k].volume
                down_count += 1

        can_go_up = up_count > 0
        can_go_down = down_count > 0

        if not can_go_up and not can_go_down:
            break

        if can_go_up and (not can_go_down or up_pair >= down_pair):
            # Expand upward by up to 2 rows
            for k in range(1, up_count + 1):
                if up_idx + k < len(profile):
                    up_idx += 1
                    current_volume += profile[up_idx].volume
        elif can_go_down:
            # Expand downward by up to 2 rows
            for k in range(1, down_count + 1):
                if down_idx - k >= 0:
                    down_idx -= 1
                    current_volume += profile[down_idx].volume

    # VAH = upper edge of top VA bin, VAL = lower edge of bottom VA bin
    step = profile[1].price - profile[0].price if len(profile) > 1 else 0
    half_step = step / 2
    vah = profile[up_idx].price + half_step
    val = profile[down_idx].price - half_step

    return vah, val


def build_snapshot(
    profile: list[VolumeProfileLevel],
    vwap_ref: float | None = None,
    value_area_pct: float = 0.70,
) -> VolumeProfileSnapshot:
    """Build a complete VolumeProfileSnapshot from a profile.

    Computes POC, VAH, VAL from the profile histogram.
    """
    if not profile:
        return VolumeProfileSnapshot(
            poc=0.0,
            vah=0.0,
            val=0.0,
            total_volume=0.0,
            poc_index=0,
            histogram=[],
        )

    poc, poc_idx = compute_poc(profile, vwap_ref)
    vah, val = compute_value_area(profile, poc_idx, value_area_pct)
    total_volume = sum(p.volume for p in profile)
    histogram = [p.volume for p in profile]

    return VolumeProfileSnapshot(
        poc=poc,
        vah=vah,
        val=val,
        total_volume=total_volume,
        poc_index=poc_idx,
        histogram=histogram,
    )


def compute_optimal_buckets(price_range: float, tick_size: float = 0.05) -> int:
    """Compute optimal number of buckets based on price range and tick size.

    P1-7: Dynamic bucket calculation for precise LVN/HVN detection.
    """
    if price_range <= 0 or tick_size <= 0:
        return 200
    ticks_in_range = price_range / tick_size
    return max(100, min(int(ticks_in_range), 1000))


def create_profile(
    data: list[OHLC],
    buckets: int = 0,
    tick_size: float = 0.0,
    concentrated: bool = False,
) -> list[VolumeProfileLevel]:
    """Build a volume profile from OHLCV data.

    Args:
        data: OHLC candles
        buckets: Number of price buckets (0 = auto-compute)
        tick_size: Minimum price increment (0 = auto-detect)
        concentrated: If True, place volume at close price only.
    """
    if not data:
        return []

    min_price = float(min(d.low for d in data))
    max_price = float(max(d.high for d in data))

    buffer = (max_price - min_price) * 0.01
    min_price -= buffer
    max_price += buffer
    price_range = max_price - min_price

    # P1-7: Auto-compute optimal bucket count
    if buckets <= 0:
        if tick_size <= 0:
            prices = sorted(set(float(d.close) for d in data[-50:]))
            if len(prices) >= 2:
                diffs = [
                    prices[i + 1] - prices[i]
                    for i in range(len(prices) - 1)
                    if prices[i + 1] > prices[i]
                ]
                tick_size = min(diffs) if diffs else 0.05
            else:
                tick_size = 0.05
        buckets = compute_optimal_buckets(price_range, tick_size)

    if price_range == 0:
        total_vol = sum(d.volume for d in data)
        avg_price = data[0].close
        return [VolumeProfileLevel(price=float(avg_price), volume=float(total_vol))]

    step = price_range / buckets
    profile = [
        VolumeProfileLevel(price=min_price + (i * step) + (step / 2))
        for i in range(buckets)
    ]

    for d in data:
        if d.volume <= 0:
            continue

        c_vol = float(d.volume)

        # Buy ratio inference
        if hasattr(d, "taker_buy_volume") and float(d.taker_buy_volume) > 0:
            buy_ratio = float(d.taker_buy_volume) / c_vol
        elif hasattr(d, "delta") and float(d.delta) != 0:
            buy_ratio = 0.5 + (float(d.delta) / (2.0 * c_vol))
            buy_ratio = max(0.0, min(1.0, buy_ratio))
        else:
            midpoint = (float(d.high) + float(d.low)) / 2
            if float(d.close) > midpoint:
                buy_ratio = 0.6
            elif float(d.close) < midpoint:
                buy_ratio = 0.4
            else:
                buy_ratio = 0.5

        if concentrated:
            # Place volume at close price (more accurate POC)
            close_bucket = int((float(d.close) - min_price) / step)
            close_bucket = max(0, min(buckets - 1, close_bucket))
            profile[close_bucket].volume += c_vol
            profile[close_bucket].buy_volume += c_vol * buy_ratio
            profile[close_bucket].sell_volume += c_vol * (1 - buy_ratio)
        else:
            # Uniform distribution across [low, high] range
            start_bucket = int((float(d.low) - min_price) / step)
            end_bucket = int((float(d.high) - min_price) / step)
            start_bucket = max(0, min(buckets - 1, start_bucket))
            end_bucket = max(0, min(buckets - 1, end_bucket))

            n_buckets = end_bucket - start_bucket + 1
            vol_per_bucket = c_vol / n_buckets if n_buckets > 0 else 0.0

            for i in range(start_bucket, end_bucket + 1):
                profile[i].volume += vol_per_bucket
                profile[i].buy_volume += vol_per_bucket * buy_ratio
                profile[i].sell_volume += vol_per_bucket * (1 - buy_ratio)

    return profile


class IncrementalVolumeProfile:
    """Maintains volume profile bucket state between ticks.

    Instead of rebuilding the full profile from all candles each tick,
    this class incrementally adds new candles and removes expired ones,
    then recomputes POC/VA from the bucket totals in O(buckets) time.

    P1-7: Auto-computes optimal bucket count from price range and tick size.
    """

    def __init__(
        self,
        buckets: int = 0,  # 0 = auto-compute on first candle
        concentrated: bool = False,
        tick_size: float = 0.0,  # 0 = auto-detect
    ) -> None:
        self._requested_buckets = buckets
        self._concentrated = concentrated  # True = volume at close price only
        self._tick_size = tick_size
        self._buckets = buckets if buckets > 0 else 200  # Temporary default
        self._volumes: list[list[float]] = [
            [0.0, 0.0, 0.0] for _ in range(self._buckets)
        ]
        self._min_price: float = 0.0
        self._max_price: float = 0.0
        self._step: float = 0.0
        self._initialized: bool = False
        self._candles: list[OHLC] = []

    def _needs_rebuild(self, new_candle: OHLC) -> bool:
        if not self._initialized:
            return True
        return (
            float(new_candle.low) < self._min_price
            or float(new_candle.high) > self._max_price
        )

    def _full_rebuild(self) -> None:
        if not self._candles:
            self._initialized = False
            return

        min_price = float(min(d.low for d in self._candles))
        max_price = float(max(d.high for d in self._candles))
        buffer = (max_price - min_price) * 0.01
        self._min_price = min_price - buffer
        self._max_price = max_price + buffer
        price_range = self._max_price - self._min_price

        # P1-7: Auto-compute optimal bucket count on rebuild
        if self._requested_buckets <= 0 and price_range > 0:
            tick_size = self._tick_size
            if tick_size <= 0:
                prices = sorted(set(float(d.close) for d in self._candles[-50:]))
                if len(prices) >= 2:
                    diffs = [
                        prices[i + 1] - prices[i]
                        for i in range(len(prices) - 1)
                        if prices[i + 1] > prices[i]
                    ]
                    tick_size = min(diffs) if diffs else 0.05
                else:
                    tick_size = 0.05
            self._buckets = compute_optimal_buckets(price_range, tick_size)

        if price_range == 0:
            total_vol = sum(float(d.volume) for d in self._candles)
            vol_per = total_vol / self._buckets
            self._volumes = [
                [vol_per, vol_per * 0.5, vol_per * 0.5] for _ in range(self._buckets)
            ]
            self._step = 1.0
            self._initialized = True
            return

        self._step = price_range / self._buckets
        self._volumes = [[0.0, 0.0, 0.0] for _ in range(self._buckets)]
        for d in self._candles:
            self._add_candle_to_buckets(d)
        self._initialized = True

    def _add_candle_to_buckets(self, candle: OHLC) -> None:
        c_vol = float(candle.volume)
        if c_vol <= 0:
            return
        buy_ratio = (
            float(candle.taker_buy_volume) / c_vol
            if (c_vol > 0 and hasattr(candle, "taker_buy_volume"))
            else 0.5
        )

        if self._concentrated:
            close_bucket = int((float(candle.close) - self._min_price) / self._step)
            close_bucket = max(0, min(self._buckets - 1, close_bucket))
            self._volumes[close_bucket][0] += c_vol
            self._volumes[close_bucket][1] += c_vol * float(buy_ratio)
            self._volumes[close_bucket][2] += c_vol * (1 - float(buy_ratio))
        else:
            c_low = float(candle.low)
            c_high = float(candle.high)
            start_bucket = int((c_low - self._min_price) / self._step)
            end_bucket = int((c_high - self._min_price) / self._step)
            start_bucket = max(0, min(self._buckets - 1, start_bucket))
            end_bucket = max(0, min(self._buckets - 1, end_bucket))

            n_buckets = end_bucket - start_bucket + 1
            vol_per_bucket = c_vol / n_buckets if n_buckets > 0 else 0.0

            for i in range(start_bucket, end_bucket + 1):
                self._volumes[i][0] += vol_per_bucket
                self._volumes[i][1] += vol_per_bucket * float(buy_ratio)
                self._volumes[i][2] += vol_per_bucket * (1 - float(buy_ratio))

    def _remove_candle_from_buckets(self, candle: OHLC) -> None:
        """Subtract a candle's volume from the profile buckets."""
        c_vol = float(candle.volume)
        if c_vol <= 0:
            return
        buy_ratio = (
            float(candle.taker_buy_volume) / c_vol
            if (c_vol > 0 and hasattr(candle, "taker_buy_volume"))
            else 0.5
        )

        if self._concentrated:
            close_bucket = int((float(candle.close) - self._min_price) / self._step)
            close_bucket = max(0, min(self._buckets - 1, close_bucket))
            self._volumes[close_bucket][0] = max(0.0, self._volumes[close_bucket][0] - c_vol)
            self._volumes[close_bucket][1] = max(
                0.0, self._volumes[close_bucket][1] - c_vol * float(buy_ratio)
            )
            self._volumes[close_bucket][2] = max(
                0.0, self._volumes[close_bucket][2] - c_vol * (1 - float(buy_ratio))
            )
        else:
            c_low = float(candle.low)
            c_high = float(candle.high)
            start_bucket = int((c_low - self._min_price) / self._step)
            end_bucket = int((c_high - self._min_price) / self._step)
            start_bucket = max(0, min(self._buckets - 1, start_bucket))
            end_bucket = max(0, min(self._buckets - 1, end_bucket))

            n_buckets = end_bucket - start_bucket + 1
            vol_per_bucket = c_vol / n_buckets if n_buckets > 0 else 0.0

            for i in range(start_bucket, end_bucket + 1):
                self._volumes[i][0] = max(0.0, self._volumes[i][0] - vol_per_bucket)
                self._volumes[i][1] = max(
                    0.0, self._volumes[i][1] - vol_per_bucket * float(buy_ratio)
                )
                self._volumes[i][2] = max(
                    0.0, self._volumes[i][2] - vol_per_bucket * (1 - float(buy_ratio))
                )

    def update(
        self, new_candle: OHLC, oldest_candle_to_remove: OHLC | None = None
    ) -> None:
        needs_remove = False
        if oldest_candle_to_remove is not None and self._candles:
            if self._candles[0].time == oldest_candle_to_remove.time:
                self._candles.pop(0)
                needs_remove = True

        self._candles.append(new_candle)

        if self._needs_rebuild(new_candle):
            self._full_rebuild()
            return

        if needs_remove:
            range_size = self._max_price - self._min_price
            edge_tolerance = range_size * 0.015
            was_boundary = (
                float(oldest_candle_to_remove.low) <= self._min_price + edge_tolerance
                or float(oldest_candle_to_remove.high)
                >= self._max_price - edge_tolerance
            )
            if was_boundary:
                self._full_rebuild()
                return
            self._remove_candle_from_buckets(oldest_candle_to_remove)

        self._add_candle_to_buckets(new_candle)

    def get_profile(self) -> list[VolumeProfileLevel]:
        if not self._initialized or not self._candles:
            return []

        step = self._step
        return [
            VolumeProfileLevel(
                price=self._min_price + (i * step) + (step / 2),
                volume=self._volumes[i][0],
                buy_volume=self._volumes[i][1],
                sell_volume=self._volumes[i][2],
            )
            for i in range(self._buckets)
        ]
