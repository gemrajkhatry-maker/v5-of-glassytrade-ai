"""Volume profile construction and VWAP calculation."""

from __future__ import annotations

from app.domain.amt.model.amt_models import VolumeProfile, VolumeProfileLevel

Bar = dict


def build_volume_profile(bars: list[Bar], bucket_size: float) -> VolumeProfile:
    """
    Build volume profile from range bars.

    Based on amt_docs section 2.2:
    1. Divide price range into buckets
    2. Allocate volume to buckets
    3. Calculate POC, VAH, VAL
    """
    if not bars:
        return VolumeProfile(levels=(), poc=0.0, vah=0.0, val=0.0, step=bucket_size)

    all_prices = []
    for bar in bars:
        all_prices.extend([bar.get("low", 0), bar.get("high", 0)])

    price_min = min(all_prices)
    price_max = max(all_prices)

    num_buckets = max(1, int((price_max - price_min) / bucket_size) + 1)
    buckets: dict[float, dict[str, float]] = {}

    for bar in bars:
        bar_low = bar.get("low", 0)
        bar_high = bar.get("high", 0)
        bar_range = bar_high - bar_low
        if bar_range == 0:
            continue

        for price in [bar_low, bar_high]:
            bucket_idx = int((price - price_min) / bucket_size)
            bucket_price = price_min + bucket_idx * bucket_size

            if bucket_price not in buckets:
                buckets[bucket_price] = {"volume": 0, "buy": 0, "sell": 0}

            vol = bar.get("volume", 0)
            buckets[bucket_price]["volume"] += vol
            buckets[bucket_price]["buy"] += bar.get("buyVolume", vol / 2)
            buckets[bucket_price]["sell"] += bar.get("sellVolume", vol / 2)

    levels = tuple(
        VolumeProfileLevel(
            price=price,
            volume=data["volume"],
            buy_volume=data["buy"],
            sell_volume=data["sell"],
        )
        for price, data in sorted(buckets.items())
    )

    if not levels:
        return VolumeProfile(levels=(), poc=0.0, vah=0.0, val=0.0, step=bucket_size)

    poc_level = max(levels, key=lambda l: l.volume)
    poc = poc_level.price

    # Value Area: 68% of volume
    total_volume = sum(l.volume for l in levels)
    target_volume = total_volume * 0.68

    sorted_levels = sorted(levels, key=lambda l: abs(l.price - poc))
    va_volume = 0
    va_levels = []

    for level in sorted_levels:
        va_levels.append(level)
        va_volume += level.volume
        if va_volume >= target_volume:
            break

    va_prices = [l.price for l in va_levels]
    vah = max(va_prices)
    val = min(va_prices)

    return VolumeProfile(
        levels=levels, poc=poc, vah=vah, val=val, step=bucket_size,
    )


def calculate_vwap(bars: list[Bar]) -> tuple[float, float, float, float, float]:
    """
    Calculate VWAP with standard deviation bands.

    Based on amt_docs section 2.3.

    Returns:
        Tuple of (vwap, upper_1, lower_1, upper_2, lower_2)
    """
    if not bars:
        return (0.0, 0.0, 0.0, 0.0, 0.0)

    cumulative_tp_volume = 0.0
    cumulative_volume = 0.0

    for bar in bars:
        typical_price = (bar.get("high", 0) + bar.get("low", 0) + bar.get("close", 0)) / 3
        volume = bar.get("volume", 0)
        cumulative_tp_volume += typical_price * volume
        cumulative_volume += volume

    if cumulative_volume == 0:
        return (0.0, 0.0, 0.0, 0.0, 0.0)

    vwap = cumulative_tp_volume / cumulative_volume

    # Standard deviation
    variance_sum = 0.0
    for bar in bars:
        typical_price = (bar.get("high", 0) + bar.get("low", 0) + bar.get("close", 0)) / 3
        variance_sum += bar.get("volume", 0) * (typical_price - vwap) ** 2

    std = (variance_sum / cumulative_volume) ** 0.5

    return (
        vwap,
        vwap + std,    # upper 1σ
        vwap - std,    # lower 1σ
        vwap + 2 * std,  # upper 2σ
        vwap - 2 * std,  # lower 2σ
    )
