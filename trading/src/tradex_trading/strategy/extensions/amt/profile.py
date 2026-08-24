"""Small AMT-specific profile policy over the canonical Candle contract."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal


def profile(
    candles,
    value_area_pct: Decimal = Decimal("0.68"),
) -> tuple[
    Decimal | None,
    Decimal | None,
    Decimal | None,
    tuple[Decimal, ...],
    tuple[Decimal, ...],
    str,
]:
    volumes: dict[Decimal, Decimal] = defaultdict(Decimal)
    for candle in candles:
        price = (
            candle.ohlc.high.value
            + candle.ohlc.low.value
            + candle.ohlc.close.value
        ) / Decimal("3")
        volumes[price] += candle.volume.value
    if not volumes:
        return None, None, None, (), (), "unknown"
    prices = sorted(volumes)
    poc = max(prices, key=lambda price: volumes[price])
    target = sum(volumes.values()) * value_area_pct
    lo = hi = prices.index(poc)
    total = volumes[poc]
    while total < target and (lo > 0 or hi < len(prices) - 1):
        down = volumes[prices[lo - 1]] if lo > 0 else Decimal("-1")
        up = volumes[prices[hi + 1]] if hi < len(prices) - 1 else Decimal("-1")
        if up >= down:
            hi += 1
            total += up
        else:
            lo -= 1
            total += down
    lvn = tuple(
        prices[i] for i in range(1, len(prices) - 1)
        if (
            volumes[prices[i]] < volumes[prices[i - 1]]
            and volumes[prices[i]] < volumes[prices[i + 1]]
        )
    )
    mean_volume = sum(volumes.values(), Decimal("0")) / Decimal(len(prices))
    hvn = tuple(
        price for price in prices if volumes[price] >= Decimal("2") * mean_volume
    )
    position = prices.index(poc) / max(1, len(prices) - 1)
    shape = "p_shape" if position > 0.65 else "b_shape" if position < 0.35 else "d_shape"
    return poc, prices[lo], prices[hi], lvn, hvn, shape
