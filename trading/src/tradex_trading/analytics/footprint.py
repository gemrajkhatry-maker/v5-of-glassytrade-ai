"""Footprint — per-price buy/sell volume tracking and bar-level analysis."""

from __future__ import annotations

from collections import defaultdict

from tradex_domain.market import Quote

from tradex_trading.analytics.orderflow import classify_aggressor
from tradex_trading.analytics.orderflow_types import FootprintLevel, OrderflowCandle


class Footprint:
    """Accumulates per-price buy/sell volume from Quote events.

    ponytail: dict-based, no persistence. Sufficient for session-scoped
    footprint analysis. Add persistence when multi-day analysis is needed.
    """

    def __init__(self) -> None:
        self._buy_vol: dict[float, float] = defaultdict(float)
        self._sell_vol: dict[float, float] = defaultdict(float)

    def add(self, quote: Quote) -> None:
        """Process one Quote: classify aggressor, accumulate volume."""
        if quote.volume is None:
            return  # no volume to attribute — nothing to accumulate
        ltp = float(quote.ltp.value)
        bid = float(quote.bid.value) if quote.bid is not None else ltp
        ask = float(quote.ask.value) if quote.ask is not None else ltp
        vol = float(quote.volume.value)
        direction = classify_aggressor(ltp=ltp, bid=bid, ask=ask)
        # A mid-trade (direction == 0) has no clear aggressor — drop it rather
        # than double-count the volume on both sides.
        if direction > 0:
            self._buy_vol[ltp] += vol
        elif direction < 0:
            self._sell_vol[ltp] += vol

    def levels(self) -> dict[float, tuple[float, float]]:
        """Return {price: (buy_volume, sell_volume)} for all traded prices."""
        all_prices = set(self._buy_vol) | set(self._sell_vol)
        return {
            p: (self._buy_vol.get(p, 0.0), self._sell_vol.get(p, 0.0))
            for p in sorted(all_prices)
        }

    def delta(self) -> dict[float, float]:
        """Return {price: buy_vol - sell_vol} for all traded prices."""
        return {
            p: buy - sell
            for p, (buy, sell) in self.levels().items()
        }

    def reset(self) -> None:
        """Clear all accumulated data."""
        self._buy_vol.clear()
        self._sell_vol.clear()


# ---------------------------------------------------------------------------
# Bar-level footprint analysis (pure functions over OrderflowCandle)
# ---------------------------------------------------------------------------


def bar_poc(candle: OrderflowCandle) -> FootprintLevel | None:
    """Price level with the highest total volume within a bar's footprint."""
    if not candle.footprint:
        return None
    return max(candle.footprint.values(), key=lambda fp: fp.total_volume)


def imbalance_levels(
    candle: OrderflowCandle, threshold: float = 3.0
) -> list[tuple[float, str]]:
    """Price levels with a strong one-sided print.

    Returns ``(price, 'buy'|'sell')`` for levels where one side dominates
    (ratio >= threshold, or a purely one-sided print). Key for initiative
    auction detection.
    """
    results: list[tuple[float, str]] = []
    for price in sorted(candle.footprint):
        fp = candle.footprint[price]
        bid, ask = fp.bid_volume, fp.ask_volume
        if bid > 0 and ask / bid >= threshold:
            results.append((price, "buy"))
        elif ask > 0 and bid / ask >= threshold:
            results.append((price, "sell"))
        elif bid == 0 and ask > 0:
            results.append((price, "buy"))
        elif ask == 0 and bid > 0:
            results.append((price, "sell"))
    return results


def absorption_at_level(
    candle: OrderflowCandle, price: float, tolerance: float = 0.0
) -> FootprintLevel | None:
    """Footprint level at (or within *tolerance* of) a price."""
    if price in candle.footprint:
        return candle.footprint[price]
    for p, fp in candle.footprint.items():
        if abs(p - price) <= tolerance:
            return fp
    return None


def aggressive_volume_at_level(
    candles: list[OrderflowCandle],
    price: float,
    *,
    tolerance: float = 0.0,
    lookback: int = 5,
) -> tuple[float, float]:
    """Total aggressive (buy, sell) volume at a price across recent bars."""
    buy = sell = 0.0
    for candle in candles[-lookback:]:
        fp = absorption_at_level(candle, price, tolerance)
        if fp is not None:
            buy += fp.ask_volume
            sell += fp.bid_volume
    return buy, sell


def count_consecutive_imbalances(
    candles: list[OrderflowCandle],
    direction: str,
    *,
    threshold: float = 3.0,
    lookback: int = 5,
) -> int:
    """Consecutive recent bars with a one-sided imbalance in a direction."""
    count = 0
    for candle in reversed(candles[-lookback:]):
        if any(d == direction for _, d in imbalance_levels(candle, threshold)):
            count += 1
        else:
            break
    return count


__all__ = [
    "Footprint",
    "absorption_at_level",
    "aggressive_volume_at_level",
    "bar_poc",
    "count_consecutive_imbalances",
    "imbalance_levels",
]
