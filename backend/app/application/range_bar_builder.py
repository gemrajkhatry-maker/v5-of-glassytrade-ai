"""Range Bar Builder — Price-movement-based bars (not time-based).

Range bars are formed when price moves a fixed amount (range_size) from the
open, regardless of time. Each bar closes at its high or low — never in the
middle.

Algorithm:
    1. New bar opens at close of previous bar (or first tick)
    2. As ticks arrive, high/low are updated
    3. When (high - low) >= range_size, the bar closes
    4. Close = high if last tick >= open, else close = low
    5. New bar opens at the close price

This module is visualization/calculation only — no trading logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RangeBar:
    """A single range bar."""

    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta: float = 0.0
    tick_count: int = 0
    time_open: str = ""
    time_close: str = ""


@dataclass
class VolumeProfileLevel:
    """Volume at a price level for range bar profile."""

    price: float
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0


@dataclass
class RangeBarVP:
    """Volume profile computed from range bars."""

    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    levels: list[VolumeProfileLevel] = field(default_factory=list)


@dataclass
class TripleAPattern:
    """Triple-A (Absorption + Accumulation + Aggression) pattern."""

    detected: bool = False
    phase: str = ""  # "ABSORPTION", "ACCUMULATION", "AGGRESSION", ""
    direction: str = ""  # "LONG", "SHORT", ""
    absorption_bar_index: int = -1
    aggression_bar_index: int = -1
    poc_at_detection: float = 0.0
    vah_at_detection: float = 0.0
    val_at_detection: float = 0.0


class RangeBarBuilder:
    """Builds range bars from tick stream.

    Usage:
        builder = RangeBarBuilder(range_size=3.0)
        bar = builder.on_tick(ltp=100.0, timestamp="2026-03-23T10:00:00")
        if bar:  # bar is None until the range is breached
            print(f"Closed bar: {bar.close}")

        # Get all closed bars + current in-progress bar
        closed = builder.get_closed_bars()
        current = builder.get_current_bar()

        # Volume profile from range bars
        vp = builder.get_volume_profile()

        # VWAP across range bars
        vwap = builder.get_vwap()

        # Triple-A pattern detection
        pattern = builder.detect_triple_a()
    """

    def __init__(
        self,
        range_size: float = 3.0,
        max_bars: int = 500,
        tick_size: float = 0.05,
    ) -> None:
        self._range_size = range_size
        self._max_bars = max_bars
        self._tick_size = tick_size

        # Current in-progress bar
        self._current: RangeBar | None = None
        self._last_price: float = 0.0

        # Completed bars
        self._bars: list[RangeBar] = []

        # Volume profile state
        self._vp_levels: dict[float, float] = {}  # price bucket -> volume
        self._vp_buy: dict[float, float] = {}
        self._vp_sell: dict[float, float] = {}

        # VWAP accumulators
        self._vwap_pv: float = 0.0  # sum(price * volume)
        self._vwap_v: float = 0.0  # sum(volume)

        # Triple-A state machine
        self._triple_a_phase: str = ""  # "", "ABSORPTION", "ACCUMULATION"
        self._triple_a_absorption_idx: int = -1
        self._triple_a_direction: str = ""

    def reset(self) -> None:
        """Reset at session boundary."""
        self._current = None
        self._last_price = 0.0
        self._bars.clear()
        self._vp_levels.clear()
        self._vp_buy.clear()
        self._vp_sell.clear()
        self._vwap_pv = 0.0
        self._vwap_v = 0.0
        self._triple_a_phase = ""
        self._triple_a_absorption_idx = -1
        self._triple_a_direction = ""

    def on_tick(
        self,
        ltp: float,
        timestamp: str = "",
        buy_vol: float = 0.0,
        sell_vol: float = 0.0,
    ) -> RangeBar | None:
        """Process a single tick. Returns closed RangeBar if range breached, else None.

        Args:
            ltp: Last traded price
            timestamp: ISO timestamp of the tick
            buy_vol: Incremental buy volume for this tick
            sell_vol: Incremental sell volume for this tick
        """
        self._last_price = ltp

        # Initialize first bar if needed
        if self._current is None:
            self._current = RangeBar(
                open=ltp,
                high=ltp,
                low=ltp,
                close=ltp,
                time_open=timestamp,
                time_close=timestamp,
            )
            return None

        bar = self._current

        # Update high/low
        bar.high = max(bar.high, ltp)
        bar.low = min(bar.low, ltp)
        bar.close = ltp
        bar.time_close = timestamp
        bar.tick_count += 1

        # Accumulate volume
        vol = buy_vol + sell_vol
        bar.volume += vol
        bar.buy_volume += buy_vol
        bar.sell_volume += sell_vol
        bar.delta = bar.buy_volume - bar.sell_volume

        # Check if range is breached
        if (bar.high - bar.low) >= self._range_size:
            # Close at high or low — never in the middle
            if ltp >= bar.open:
                bar.close = bar.high  # Bullish
            else:
                bar.close = bar.low  # Bearish

            # Finalize
            self._finalize_bar(bar)
            closed_bar = bar

            # Open new bar at the close price
            self._current = RangeBar(
                open=bar.close,
                high=bar.close,
                low=bar.close,
                close=bar.close,
                time_open=timestamp,
                time_close=timestamp,
            )

            return closed_bar

        return None

    def _finalize_bar(self, bar: RangeBar) -> None:
        """Add closed bar to history and update indicators."""
        self._bars.append(bar)

        # Trim old bars
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]

        # Update volume profile
        # Use tick-sized price buckets
        step = self._tick_size
        mid_price = (bar.high + bar.low) / 2.0
        bucket = round(mid_price / step) * step
        self._vp_levels[bucket] = self._vp_levels.get(bucket, 0.0) + bar.volume
        self._vp_buy[bucket] = self._vp_buy.get(bucket, 0.0) + bar.buy_volume
        self._vp_sell[bucket] = self._vp_sell.get(bucket, 0.0) + bar.sell_volume

        # Also distribute across the bar's range
        price = bar.low
        while price <= bar.high:
            bkt = round(price / step) * step
            self._vp_levels[bkt] = self._vp_levels.get(bkt, 0.0) + bar.volume / max(
                1, (bar.high - bar.low) / step + 1
            )
            self._vp_buy[bkt] = self._vp_buy.get(bkt, 0.0) + bar.buy_volume / max(
                1, (bar.high - bar.low) / step + 1
            )
            self._vp_sell[bkt] = self._vp_sell.get(bkt, 0.0) + bar.sell_volume / max(
                1, (bar.high - bar.low) / step + 1
            )
            price += step

        # Update VWAP
        self._vwap_pv += bar.close * bar.volume
        self._vwap_v += bar.volume

    def get_closed_bars(self) -> list[RangeBar]:
        """Return all closed range bars."""
        return list(self._bars)

    def get_current_bar(self) -> RangeBar | None:
        """Return the current in-progress bar."""
        return self._current

    def get_all_bars(self) -> list[RangeBar]:
        """Return closed bars + current in-progress bar."""
        bars = list(self._bars)
        if self._current:
            bars.append(self._current)
        return bars

    def get_last_price(self) -> float:
        return self._last_price

    # ── Volume Profile ──────────────────────────────────────────────

    def get_volume_profile(self) -> RangeBarVP:
        """Compute volume profile from range bars."""
        if not self._vp_levels:
            return RangeBarVP()

        sorted_levels = sorted(self._vp_levels.items())
        total_vol = sum(v for _, v in sorted_levels)

        if total_vol <= 0:
            return RangeBarVP()

        # POC = price with highest volume
        poc_price = max(sorted_levels, key=lambda x: x[1])[0]

        # VAH/VAL = 70% value area boundaries
        target = total_vol * 0.70
        poc_vol = self._vp_levels.get(poc_price, 0.0)

        # Expand from POC outward to capture 70% of volume
        poc_idx = next(i for i, (p, _) in enumerate(sorted_levels) if p == poc_price)
        accumulated = poc_vol
        lo_idx = poc_idx
        hi_idx = poc_idx

        while accumulated < target:
            lo_vol = (
                self._vp_levels.get(sorted_levels[lo_idx - 1][0], 0.0)
                if lo_idx > 0
                else -1
            )
            hi_vol = (
                self._vp_levels.get(sorted_levels[hi_idx + 1][0], 0.0)
                if hi_idx < len(sorted_levels) - 1
                else -1
            )

            if lo_vol >= hi_vol and lo_vol > 0:
                lo_idx -= 1
                accumulated += lo_vol
            elif hi_vol > 0:
                hi_idx += 1
                accumulated += hi_vol
            else:
                break

        val = sorted_levels[lo_idx][0]
        vah = sorted_levels[hi_idx][0]

        levels = [
            VolumeProfileLevel(
                price=p,
                volume=v,
                buy_volume=self._vp_buy.get(p, 0.0),
                sell_volume=self._vp_sell.get(p, 0.0),
            )
            for p, v in sorted_levels
        ]

        return RangeBarVP(poc=poc_price, vah=vah, val=val, levels=levels)

    # ── VWAP ────────────────────────────────────────────────────────

    def get_vwap(self) -> float:
        """Volume-weighted average price across all range bars."""
        if self._vwap_v <= 0:
            return 0.0
        return self._vwap_pv / self._vwap_v

    # ── Delta ───────────────────────────────────────────────────────

    def get_cumulative_delta(self) -> float:
        """Cumulative delta across all closed range bars."""
        return sum(b.delta for b in self._bars)

    # ── Triple-A Pattern Detection ──────────────────────────────────

    def detect_triple_a(self) -> TripleAPattern:
        """Detect Triple-A (Absorption + Accumulation + Aggression) pattern.

        Phase 1 — ABSORPTION: High-volume bar with tight range
            (volume > 1.5x average AND range < 0.5x average range)

        Phase 2 — ACCUMULATION: 2-3 tight-range bars after absorption
            (range < 0.7x average range, directionless)

        Phase 3 — AGGRESSION: Breakout bar with expanding volume
            (volume > 1.2x average AND range > 1.0x average range,
             closes beyond absorption bar's high/low)
        """
        if len(self._bars) < 5:
            return TripleAPattern()

        recent = self._bars[-10:]

        # Compute averages
        avg_vol = sum(b.volume for b in recent) / len(recent)
        avg_range = sum(b.high - b.low for b in recent) / len(recent)

        if avg_vol <= 0 or avg_range <= 0:
            return TripleAPattern()

        # Phase 1: Look for absorption in last 5 bars
        absorption_idx = -1
        for i in range(max(0, len(recent) - 5), len(recent)):
            bar = recent[i]
            bar_range = bar.high - bar.low
            if bar.volume > avg_vol * 1.5 and bar_range < avg_range * 0.5:
                absorption_idx = i
                break

        if absorption_idx < 0:
            return TripleAPattern()

        # Phase 2: Check for accumulation (2-3 tight bars after absorption)
        acc_count = 0
        for i in range(absorption_idx + 1, len(recent)):
            bar = recent[i]
            bar_range = bar.high - bar.low
            if bar_range < avg_range * 0.7:
                acc_count += 1
            else:
                break

        if acc_count < 1:
            return TripleAPattern()

        # Phase 3: Check for aggression (breakout bar after accumulation)
        aggression_idx = absorption_idx + acc_count + 1
        if aggression_idx >= len(recent):
            # Still in accumulation phase
            return TripleAPattern(
                detected=False,
                phase="ACCUMULATION",
                direction="",
                absorption_bar_index=absorption_idx,
                aggression_bar_index=-1,
            )

        agg_bar = recent[aggression_idx]
        agg_range = agg_bar.high - agg_bar.low
        absorption_bar = recent[absorption_idx]

        if agg_bar.volume > avg_vol * 1.2 and agg_range > avg_range * 1.0:
            # Breakout detected
            if agg_bar.close > absorption_bar.high:
                direction = "LONG"
            elif agg_bar.close < absorption_bar.low:
                direction = "SHORT"
            else:
                direction = ""

            vp = self.get_volume_profile()
            return TripleAPattern(
                detected=True,
                phase="AGGRESSION",
                direction=direction,
                absorption_bar_index=absorption_idx,
                aggression_bar_index=aggression_idx,
                poc_at_detection=vp.poc,
                vah_at_detection=vp.vah,
                val_at_detection=vp.val,
            )

        return TripleAPattern(
            detected=False,
            phase="ACCUMULATION",
            direction="",
            absorption_bar_index=absorption_idx,
            aggression_bar_index=-1,
        )

    # ── Serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize state for WebSocket streaming."""
        bars = self.get_all_bars()
        vp = self.get_volume_profile()
        triple_a = self.detect_triple_a()

        # Convert bars to OHLC-like format with sequential synthetic timestamps
        # Range bars don't have real time ordering, so we use bar index as time
        # The frontend renders these on the candlestick series
        import time

        base_ts = int(time.time()) - len(bars) * 60  # 1 bar per minute synthetic
        serialized_bars = []
        for i, b in enumerate(bars):
            serialized_bars.append(
                {
                    "time": base_ts + i * 60,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "delta": b.delta,
                    "buyVolume": b.buy_volume,
                    "sellVolume": b.sell_volume,
                    "tickCount": b.tick_count,
                }
            )

        return {
            "bars": serialized_bars,
            "volumeProfile": {
                "poc": vp.poc,
                "vah": vp.vah,
                "val": vp.val,
                "levels": [
                    {
                        "price": l.price,
                        "volume": l.volume,
                        "buyVolume": l.buy_volume,
                        "sellVolume": l.sell_volume,
                    }
                    for l in vp.levels[-200:]  # Cap VP levels to prevent huge payloads
                ],
            },
            "vwap": self.get_vwap(),
            "cumulativeDelta": self.get_cumulative_delta(),
            "tripleA": {
                "detected": triple_a.detected,
                "phase": triple_a.phase,
                "direction": triple_a.direction,
                "absorptionBarIndex": triple_a.absorption_bar_index,
                "aggressionBarIndex": triple_a.aggression_bar_index,
                "pocAtDetection": triple_a.poc_at_detection,
                "vahAtDetection": triple_a.vah_at_detection,
                "valAtDetection": triple_a.val_at_detection,
            },
            "rangeSize": self._range_size,
        }
