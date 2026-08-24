"""Volume profile: POC, VAH, VAL, LVN, value area, session profiles, shape."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from tradex_domain.market import Quote

from tradex_trading.analytics.orderflow import round_price
from tradex_trading.analytics.orderflow_types import OrderflowCandle, VolumeProfile

#: Default value-area width — the 68% rule from the OrderFlow methodology.
#: Shared by the pure functions and the engine so both layers default
#: identically (users can override per profile via ``pct`` / ``value_area_pct``).
DEFAULT_VALUE_AREA_PCT = 0.68

#: Methodology constants (Fabio convention, from the OrderFlow reference).
_P_SHAPE_POC_PCT = 0.65  # POC in the upper 35% of the profile → buyers
_B_SHAPE_POC_PCT = 0.35  # POC in the lower 35% of the profile → sellers
_DOUBLE_DIST_PEAK_FACTOR = 1.5  # both halves' peaks must exceed mean * this
_DOUBLE_DIST_VALLEY_RATIO = 0.5  # valley must dip below the smaller peak * this
_DOUBLE_DIST_MIN_LEVELS = 10
_DOUBLE_DIST_MIN_SEPARATION = 2  # peak gap must exceed 2 levels
_LVN_MIN_LEVELS = 5
_LVN_FLOOR_FACTOR = 0.2  # LVN threshold floored at mean * this


def poc(price_volume: dict[float, float]) -> float | None:
    """Price level with the highest volume; None when empty."""
    if not price_volume:
        return None
    return max(price_volume, key=price_volume.__getitem__)


def value_area(
    price_volume: dict[float, float],
    pct: float = DEFAULT_VALUE_AREA_PCT,
) -> tuple[float | None, float | None]:
    """Return (VAL, VAH) bounding the *pct* fraction of total volume around POC.

    Walks outward from POC one level at a time, adding the side with more
    volume (ties expand upward), until accumulated volume >= pct * total.
    Matches the OrderFlow reference's expansion exactly.
    """
    if not price_volume:
        return (None, None)
    p = poc(price_volume)
    if p is None:
        return (None, None)
    total = sum(price_volume.values())
    target = total * pct
    sorted_prices = sorted(price_volume.keys())
    poc_idx = sorted_prices.index(p)
    accumulated = price_volume[p]
    lo_idx = poc_idx
    hi_idx = poc_idx
    while accumulated < target:
        can_up = hi_idx < len(sorted_prices) - 1
        can_down = lo_idx > 0
        if not can_up and not can_down:
            break
        vol_up = price_volume[sorted_prices[hi_idx + 1]] if can_up else -1
        vol_down = price_volume[sorted_prices[lo_idx - 1]] if can_down else -1
        if vol_up >= vol_down:
            hi_idx += 1
            accumulated += vol_up
        else:
            lo_idx -= 1
            accumulated += vol_down
    return (sorted_prices[lo_idx], sorted_prices[hi_idx])


def vah(price_volume: dict[float, float], pct: float = DEFAULT_VALUE_AREA_PCT) -> float | None:
    """Value Area High — upper bound of the value area."""
    return value_area(price_volume, pct)[1]


def val(price_volume: dict[float, float], pct: float = DEFAULT_VALUE_AREA_PCT) -> float | None:
    """Value Area Low — lower bound of the value area."""
    return value_area(price_volume, pct)[0]


def lvn(price_volume: dict[float, float]) -> list[float]:
    """Low-Volume Nodes — price levels where volume is lower than both neighbors.

    Returns sorted list of prices. Empty profile or flat profile returns [].
    """
    if len(price_volume) < 3:
        return []
    sorted_prices = sorted(price_volume.keys())
    nodes: list[float] = []
    for i in range(1, len(sorted_prices) - 1):
        vol = price_volume[sorted_prices[i]]
        prev_vol = price_volume[sorted_prices[i - 1]]
        next_vol = price_volume[sorted_prices[i + 1]]
        if vol < prev_vol and vol < next_vol:
            nodes.append(sorted_prices[i])
    return nodes


# ---------------------------------------------------------------------------
# Session-scoped profile engine (shape classification + multi-day merge)
# ---------------------------------------------------------------------------

_SHAPES = ("p_shape", "b_shape", "d_shape", "double_dist", "unknown")


class VolumeProfileEngine:
    """Builds session volume profiles with POC/VAH/VAL/LVN and shape.

    Ported from the OrderFlow reference, but pure-Python and consuming
    TradeX's ``Quote`` / ``OrderflowCandle`` inputs. Shape classification
    follows the P-shape (buyers) / b-shape (sellers) / D-shape (balanced) /
    double-distribution (transition) convention.
    """

    def __init__(
        self,
        *,
        tick_size: float = 0.05,
        value_area_pct: float = DEFAULT_VALUE_AREA_PCT,
        lvn_stddev_factor: float = 1.5,
    ) -> None:
        self.tick_size = tick_size
        self.value_area_pct = value_area_pct
        self.lvn_stddev_factor = lvn_stddev_factor

    def compute_from_quotes(
        self, quotes: Sequence[Quote], session_date: str = ""
    ) -> VolumeProfile:
        """Build a profile from raw quote events (footprint at quote volume)."""
        vap: dict[float, float] = defaultdict(float)
        for q in quotes:
            if q.volume is None:
                continue
            rounded = round_price(float(q.ltp.value), self.tick_size)
            vap[rounded] += float(q.volume.value)
        return self._compute_profile(dict(vap), session_date)

    def compute_from_candles(
        self, candles: Sequence[OrderflowCandle], session_date: str = ""
    ) -> VolumeProfile:
        """Build a profile from candles, using footprint when present.

        Candles without footprint (e.g. historical OHLCV) fall back to
        distributing volume evenly across the bar's high-low range.
        """
        vap: dict[float, float] = defaultdict(float)
        for candle in candles:
            if candle.footprint:
                for price, fp in candle.footprint.items():
                    rounded = round_price(price, self.tick_size)
                    vap[rounded] += fp.total_volume
            else:
                low = round_price(float(candle.ohlc.low.value), self.tick_size)
                high = round_price(float(candle.ohlc.high.value), self.tick_size)
                span = high - low
                n_levels = max(1, int(span / self.tick_size) + 1) if span > 0 else 1
                vol_per_level = float(candle.volume.value) / n_levels
                price = low
                for _ in range(n_levels):
                    vap[round(price, 10)] += vol_per_level
                    price += self.tick_size
        return self._compute_profile(dict(vap), session_date)

    def merge_profiles(self, profiles: Sequence[VolumeProfile]) -> VolumeProfile:
        """Merge multiple session profiles into a composite (multi-day context)."""
        if not profiles:
            return VolumeProfile()
        if len(profiles) == 1:
            return profiles[0]
        merged: dict[float, float] = defaultdict(float)
        dates = [p.session_date for p in profiles if p.session_date]
        for profile in profiles:
            for price, vol in profile.volume_at_price.items():
                merged[price] += vol
        session_date = f"{dates[0]}_to_{dates[-1]}" if len(dates) == len(profiles) else ""
        return self._compute_profile(dict(merged), session_date)

    def _compute_profile(
        self, volume_at_price: dict[float, float], session_date: str
    ) -> VolumeProfile:
        if not volume_at_price:
            return VolumeProfile(session_date=session_date)
        prices = sorted(volume_at_price)
        volumes = [volume_at_price[p] for p in prices]
        total_volume = sum(volumes)
        if total_volume == 0:
            return VolumeProfile(session_date=session_date)

        p = poc(volume_at_price)
        poc_idx = prices.index(p) if p is not None else 0
        lo, hi = value_area(volume_at_price, self.value_area_pct)
        lvn_levels = self._detect_lvn(prices, volumes)
        shape, poc_pct = self._classify_shape(prices, volumes, poc_idx)

        return VolumeProfile(
            session_date=session_date,
            poc=p,
            vah=hi,
            val=lo,
            volume_at_price=volume_at_price,
            total_volume=total_volume,
            lvn_levels=tuple(lvn_levels),
            shape=shape,
            poc_position_pct=poc_pct,
        )

    def _detect_lvn(self, prices: list[float], volumes: list[float]) -> list[float]:
        """Low-volume nodes: local minima below mean - factor*stddev."""
        n = len(volumes)
        if n < _LVN_MIN_LEVELS:
            return []
        mean = sum(volumes) / n
        var = sum((v - mean) ** 2 for v in volumes) / n
        std = var ** 0.5
        threshold = mean - self.lvn_stddev_factor * std
        threshold = max(threshold, mean * _LVN_FLOOR_FACTOR)
        nodes: list[float] = []
        for i in range(1, n - 1):
            if (
                volumes[i] < volumes[i - 1]
                and volumes[i] < volumes[i + 1]
                and volumes[i] < threshold
            ):
                nodes.append(prices[i])
        return nodes

    def _classify_shape(
        self, prices: list[float], volumes: list[float], poc_idx: int
    ) -> tuple[str, float]:
        n = len(prices)
        if n == 0:
            return "unknown", 0.5
        poc_pct = poc_idx / max(n - 1, 1)

        # Double distribution: two significant peaks with a valley between.
        if n >= _DOUBLE_DIST_MIN_LEVELS:
            mid = n // 2
            lower_max = max(range(0, mid), key=volumes.__getitem__)
            upper_max = max(range(mid, n), key=volumes.__getitem__)
            mean = sum(volumes) / n
            if (
                volumes[lower_max] > mean * _DOUBLE_DIST_PEAK_FACTOR
                and volumes[upper_max] > mean * _DOUBLE_DIST_PEAK_FACTOR
            ):
                lo, hi = sorted((lower_max, upper_max))
                if hi - lo > _DOUBLE_DIST_MIN_SEPARATION:
                    valley_min = min(volumes[lo + 1 : hi])
                    valley_threshold = (
                        min(volumes[lower_max], volumes[upper_max]) * _DOUBLE_DIST_VALLEY_RATIO
                    )
                    if valley_min < valley_threshold:
                        return "double_dist", poc_pct

        if poc_pct > _P_SHAPE_POC_PCT:
            return "p_shape", poc_pct
        if poc_pct < _B_SHAPE_POC_PCT:
            return "b_shape", poc_pct
        return "d_shape", poc_pct


__all__ = [
    "DEFAULT_VALUE_AREA_PCT",
    "VolumeProfileEngine",
    "poc",
    "vah",
    "val",
    "lvn",
    "value_area",
]
