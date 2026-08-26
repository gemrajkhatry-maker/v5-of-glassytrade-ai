"""Rebuild a deterministic tick stream from journaled BarClosed rows.

Each recorded bar becomes 4 ticks [O, H, L, C]; volume/buy/sell split evenly.
The aggregator reproduces the exact OHLCV because all ticks share one
interval bucket. # ponytail: bar.vwap is NOT reproduced exactly (equal-volume
split vs live weighting) — replay x2 determinism is exact, live-vs-replay
parity needs tick-grade journals. Upgrade path: record raw ticks in live mode.
"""

from __future__ import annotations

from quant.brokers.gateway import Tick

_EPOCH_FLOOR = 946684800


def bars_from_journal(rows: list[dict]) -> tuple[int, list[dict]]:
    """Return (inferred_interval_seconds, bar_dicts) from journal rows."""
    bars = [r["bar"] for r in rows
            if r.get("type") == "BarClosed" and isinstance(r.get("bar"), dict)]
    if len(bars) < 2:
        raise ValueError("journal has fewer than 2 BarClosed rows")
    times = [int(float(b["time"])) for b in bars[:5]]
    deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    interval = min(deltas) if deltas else 60
    return int(interval), bars


def ticks_from_bars(bars: list[dict], interval: int) -> list[Tick]:
    ticks: list[Tick] = []
    for b in bars:
        base = int(float(b["time"]))
        if base < _EPOCH_FLOOR:
            raise ValueError(f"non-epoch bar time {b['time']!r}")
        vol = float(b.get("volume") or 0.0)
        delta = float(b.get("delta") or 0.0)
        buy = (vol + delta) / 2.0
        sell = vol - buy
        qv, qb, qs = vol / 4.0, buy / 4.0, sell / 4.0
        for i, price in enumerate(
            (float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]))
        ):
            ticks.append(Tick(time=str(base + i + 1), price=price, volume=qv,
                              buy_volume=qb, sell_volume=qs,
                              oi=float(b.get("oi") or 0.0)))
    return ticks
