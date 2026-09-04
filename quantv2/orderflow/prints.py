"""Bubble print tracker — AMT §7.1.

A trade print is a volume bubble when its size reaches ``min_bubble_qty`` lots
(contractual: 30). A bubble is institutional when its size reaches
``institutional_qty`` lots (contractual: 100) or the feed's institutional flag
is set. Bubbles are kept as re-test levels for cluster queries.

Translated from ``quant/amt/orderflow/aggressive_prints.py`` (registry +
proximity-query semantics); threshold thresholds pinned to AMT §7.1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_EPS = 1e-9


@dataclass(frozen=True)
class Bubble:
    """A single aggressive print that qualifies as a volume bubble (§7.1)."""

    symbol: str
    ts: float
    price: float
    qty: float
    side: str
    institutional: bool


class PrintTracker:
    """Tracks volume bubbles and answers cluster (re-test) queries.

    Threshold semantics (AMT §7.1, contractual):
      - ``qty >= min_bubble_qty``   → bubble (30)
      - ``qty >= institutional_qty`` or feed flag → institutional (100)
    """

    def __init__(
        self,
        symbol: str = "",
        min_bubble_qty: float = 30.0,
        institutional_qty: float = 100.0,
    ) -> None:
        self.symbol = symbol
        self.min_bubble_qty = min_bubble_qty
        self.institutional_qty = institutional_qty
        self._bubbles: list[Bubble] = []

    @property
    def bubbles(self) -> list[Bubble]:
        return list(self._bubbles)

    def on_print(
        self,
        ts: float,
        price: float,
        qty: float,
        side: str,
        flag: bool | None = None,
    ) -> Bubble | None:
        """Register a trade print; return a Bubble if it qualifies, else None."""
        if qty < self.min_bubble_qty:
            return None
        institutional = qty >= self.institutional_qty or bool(flag)
        bubble = Bubble(
            symbol=self.symbol,
            ts=ts,
            price=float(price),
            qty=float(qty),
            side=side,
            institutional=institutional,
        )
        self._bubbles.append(bubble)
        return bubble

    def bubbles_near(self, price: float, ticks: int, tick: float) -> list[Bubble]:
        """Bubbles clustered at/near ``price`` for re-test analysis.

        A bubble matches when it lies within ``±ticks * tick`` of ``price``
        or shares the same whole-price level — bubbles cluster on the level,
        not just the tight tick window.
        """
        lo = price - ticks * tick - _EPS
        hi = price + ticks * tick + _EPS
        level = math.floor(price)
        return [
            b
            for b in self._bubbles
            if lo <= b.price <= hi or math.floor(b.price) == level
        ]

    def clear(self) -> None:
        self._bubbles.clear()
