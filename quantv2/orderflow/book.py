"""Depth book — OBI, walls, staleness, one-sided fraction (AMT §7, fabio L96).

5-LEVEL CONSTRAINT (documented, honest): Dhan marketfeed exposes 5-level
depth for NSE F&O. This book is hard-capped at `max_levels=5`; OBI/walls are
computed on what this broker actually provides, never on a full book.

Doc-pinned numbers:
  - OBI = (bid_qty − ask_qty) / (bid_qty + ask_qty), always in [−1, 1]
    (0.0 on an empty/one-sided-empty book).
  - Wall = level qty ≥ ratio (default 3.0) × median level qty of its side
    (median_low so a thin 2-level book 500-vs-100 flags the 500 as a wall).
  - Stale = book not refreshed for > 10 s (never-refreshed is always stale).
  - spread(tick) = (best_ask − best_bid) snapped to the tick grid; None if
    either side is missing.
  - one_sided_fraction(window_s=60) = dominant-side share of aggressive
    prints routed in via add_print() over the trailing window; 0.0 with no
    prints. Consumed by absorption (≥ 0.60 gate).

Translated from quant/amt/orderflow/aggression.py + footprint.py OBI /
one-sided math (v1 frozen, never imported).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BookLevel:
    price: float
    qty: float


def _median_low(values: list[float]) -> float:
    s = sorted(values)
    return s[(len(s) - 1) // 2]


class DepthBook:
    def __init__(self, max_levels: int = 5) -> None:
        self.max_levels = max_levels
        self.bids: list[BookLevel] = []
        self.asks: list[BookLevel] = []
        self._ts: float | None = None
        self._prints: list[tuple[float, int]] = []  # (ts, +1 buy / -1 sell)

    def apply_bid_ask(
        self, bids: list[tuple[float, float]], asks: list[tuple[float, float]], ts: float
    ) -> None:
        self.bids = self._side(bids, descending=True)
        self.asks = self._side(asks, descending=False)
        self._ts = ts

    def _side(self, levels: list[tuple[float, float]], descending: bool) -> list[BookLevel]:
        merged: dict[float, float] = {}
        for price, qty in levels:
            if qty <= 0:
                continue
            merged[price] = merged.get(price, 0.0) + qty
        ordered = sorted(merged.items(), key=lambda kv: kv[0], reverse=descending)
        return [BookLevel(price=p, qty=q) for p, q in ordered[: self.max_levels]]

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    def spread(self, tick: float) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        raw = self.best_ask - self.best_bid
        if raw < 0 or tick <= 0:
            return None
        return round(raw / tick) * tick

    def obi(self) -> float:
        bid_qty = sum(lv.qty for lv in self.bids)
        ask_qty = sum(lv.qty for lv in self.asks)
        total = bid_qty + ask_qty
        if total <= 0:
            return 0.0
        return max(-1.0, min(1.0, (bid_qty - ask_qty) / total))

    def wall_levels(self, threshold_ratio: float = 3.0) -> tuple[list[BookLevel], list[BookLevel]]:
        def walls(levels: list[BookLevel]) -> list[BookLevel]:
            if len(levels) < 2:
                return []
            threshold = threshold_ratio * _median_low([lv.qty for lv in levels])
            return [lv for lv in levels if lv.qty >= threshold]

        return walls(self.bids), walls(self.asks)

    def is_stale(self, now: float, max_age_s: float = 10.0) -> bool:
        if self._ts is None:
            return True
        return (now - self._ts) > max_age_s

    def add_print(self, side: str, ts: float) -> None:
        s = side.upper()
        if s not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        self._prints.append((ts, 1 if s == "BUY" else -1))

    def one_sided_fraction(self, window_s: float = 60) -> float:
        if not self._prints:
            return 0.0
        now = max(ts for ts, _ in self._prints)
        recent = [sign for ts, sign in self._prints if (now - ts) <= window_s]
        if not recent:
            return 0.0
        buys = sum(1 for sign in recent if sign > 0)
        dominant = max(buys, len(recent) - buys)
        return dominant / len(recent)
