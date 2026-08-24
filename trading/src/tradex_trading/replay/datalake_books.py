"""Datalake-derived order books — Depth snapshots rebuilt from OHLCV bars.

The datalake stores OHLCV only, but tick-level L2 backtests need books. This
generator rebuilds a deterministic ``Depth`` snapshot for every bar from the
bar's own OHLCV: the book is anchored on the bar's close, the spread comes
from the configured tick size, and level quantities scale with the bar's
volume — big bars trade through deeper books. The snapshot for a given bar is
identical every run (per-bar seed derived from instrument + timestamp), so a
full-universe ``BookFillSource`` backtest over ``ParquetStorage.read`` output
is deterministic without any live depth source.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from tradex_domain import Candle, Depth
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.replay.depth_tape import interleave_tape


@dataclass(frozen=True, slots=True)
class DatalakeBookGenerator:
    """Deterministic book-snapshot generator anchored on OHLCV bars.

    Parameters
    ----------
    depth_levels:
        Number of price levels per side (default 5).
    tick_size:
        Price step between levels (NSE equity default 0.05).
    seed:
        Optional RNG seed mixed with each bar's identity — snapshots for the
        same bar are stable across runs and across generator instances.
    """

    depth_levels: int = 5
    tick_size: Decimal | float | str = Decimal("0.05")
    seed: int | None = None

    def snapshot(self, candle: Candle) -> Depth:
        """Build the book snapshot for *candle* (anchored at its close).

        Level quantity scales with the bar's volume (``volume / divisor``), so
        high-volume bars present deeper books — a marketable order sweeping
        them pays the same VWAP every run for the same tape.
        """
        if self.depth_levels < 1:
            raise ValueError("depth_levels must be >= 1")
        tick = Decimal(str(self.tick_size))
        mid = candle.ohlc.close.value
        # Per-bar determinism: the same bar always yields the same book,
        # independent of tape order or generator instance.
        identity = f"{candle.instrument.instrument_id}|{candle.timestamp}"
        rng = random.Random(self.seed)
        rng.seed(identity + ("" if self.seed is None else f"|{self.seed}"))
        base = max(Decimal("1"), (candle.volume.value / Decimal("100")).to_integral_value())
        bids: list[tuple[Price, Quantity]] = []
        asks: list[tuple[Price, Quantity]] = []
        for i in range(self.depth_levels):
            offset = tick * (i + 1)
            raw = rng.uniform(float(base) * 0.5, float(base) * 1.5) * (1 + i * 0.4)
            qty = Quantity(value=Decimal(str(max(1, int(raw)))))
            bids.append((Price(value=mid - offset), qty))
            asks.append((Price(value=mid + offset), qty))
        return Depth(
            instrument=candle.instrument,
            bids=tuple(bids),
            asks=tuple(asks),
            # Snapshot at the bar's close, so interleaving puts it after the
            # bar it summarizes (the convention interleave_tape relies on).
            timestamp=candle.timestamp + timedelta(seconds=59),
        )


def book_tape_from_candles(
    candles: list[Candle],
    *,
    depth_levels: int = 5,
    tick_size: Decimal | float | str = Decimal("0.05"),
    seed: int | None = None,
) -> list[Candle | Depth]:
    """Build a full book-backtest tape from OHLCV bars (candles + snapshots).

    Shortcut for running ``BookFillSource`` backtests directly off the
    datalake: ``book_tape_from_candles(store.read(...))`` produces the event
    stream ``BacktestEngine.run`` expects, with a Depth snapshot per bar.
    """
    generator = DatalakeBookGenerator(
        depth_levels=depth_levels, tick_size=tick_size, seed=seed,
    )
    return interleave_tape(candles, [generator.snapshot(c) for c in candles])


__all__ = ["DatalakeBookGenerator", "book_tape_from_candles"]
