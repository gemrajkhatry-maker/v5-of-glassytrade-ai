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
    synth_time: int = 0


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

        # Triple-A state machine — persistent across detect_triple_a() calls
        self._triple_a_phase: str = ""  # "", "ABSORPTION", "ACCUMULATION", "AGGRESSION"
        self._triple_a_absorption_idx: int = -1
        self._triple_a_direction: str = ""
        self._leg_start_idx: int = 0
        self._absorption_bar_index: int | None = None
        self._accumulation_count: int = 0
        self._aggression_bar_index: int = -1
        self._last_processed_idx: int = -1
        self._poc_at_detection: float = 0.0
        self._vah_at_detection: float = 0.0
        self._val_at_detection: float = 0.0
        import time
        self._next_ts: int = int(time.time()) - (self._max_bars * 60)

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
        self._leg_start_idx = 0
        self._absorption_bar_index = None
        self._accumulation_count = 0
        self._aggression_bar_index = -1
        self._last_processed_idx = -1
        self._poc_at_detection = 0.0
        self._vah_at_detection = 0.0
        self._val_at_detection = 0.0
        import time
        self._next_ts = int(time.time()) - (self._max_bars * 60)

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
        bar.synth_time = self._next_ts
        self._next_ts += 60
        self._bars.append(bar)

        # Trim old bars (in-place to avoid list copy)
        if len(self._bars) > self._max_bars:
            del self._bars[:-self._max_bars]

        # Update volume profile — distribute volume across the bar's range
        step = self._tick_size
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

    def _compute_vp_from_dicts(self, vp_levels: dict, vp_buy: dict, vp_sell: dict) -> RangeBarVP:
        if not vp_levels:
            return RangeBarVP()

        sorted_levels = sorted(vp_levels.items())
        total_vol = sum(v for _, v in sorted_levels)

        if total_vol <= 0:
            return RangeBarVP()

        poc_price = max(sorted_levels, key=lambda x: x[1])[0]
        target = total_vol * 0.70
        poc_vol = vp_levels.get(poc_price, 0.0)

        poc_idx = next(i for i, (p, _) in enumerate(sorted_levels) if p == poc_price)
        accumulated = poc_vol
        lo_idx = poc_idx
        hi_idx = poc_idx

        while accumulated < target:
            lo_vol = (
                vp_levels.get(sorted_levels[lo_idx - 1][0], 0.0)
                if lo_idx > 0
                else -1
            )
            hi_vol = (
                vp_levels.get(sorted_levels[hi_idx + 1][0], 0.0)
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
                buy_volume=vp_buy.get(p, 0.0),
                sell_volume=vp_sell.get(p, 0.0),
            )
            for p, v in sorted_levels
        ]

        return RangeBarVP(poc=poc_price, vah=vah, val=val, levels=levels)

    def get_volume_profile(self) -> RangeBarVP:
        """Compute session volume profile from all range bars."""
        return self._compute_vp_from_dicts(self._vp_levels, self._vp_buy, self._vp_sell)

    def get_leg_volume_profile(self) -> RangeBarVP:
        """Compute leg volume profile from range bars (since last TripleA aggression)."""
        if not self._bars:
            return RangeBarVP()
            
        ta = self.detect_triple_a()
        if ta.detected and ta.phase == "AGGRESSION":
            self._leg_start_idx = max(0, ta.aggression_bar_index)
            
        vp_levels = {}
        vp_buy = {}
        vp_sell = {}
        step = self._tick_size
        
        bars = self._bars[self._leg_start_idx:] if hasattr(self, '_leg_start_idx') else self._bars
        for bar in bars:
            mid_price = (bar.high + bar.low) / 2.0
            bucket = round(mid_price / step) * step
            vp_levels[bucket] = vp_levels.get(bucket, 0.0) + bar.volume
            vp_buy[bucket] = vp_buy.get(bucket, 0.0) + bar.buy_volume
            vp_sell[bucket] = vp_sell.get(bucket, 0.0) + bar.sell_volume
            
            price = bar.low
            v_per_tick = bar.volume / max(1, (bar.high - bar.low) / step + 1)
            bv_per_tick = bar.buy_volume / max(1, (bar.high - bar.low) / step + 1)
            sv_per_tick = bar.sell_volume / max(1, (bar.high - bar.low) / step + 1)
            
            while price <= bar.high:
                bkt = round(price / step) * step
                vp_levels[bkt] = vp_levels.get(bkt, 0.0) + v_per_tick
                vp_buy[bkt] = vp_buy.get(bkt, 0.0) + bv_per_tick
                vp_sell[bkt] = vp_sell.get(bkt, 0.0) + sv_per_tick
                price += step
                
        return self._compute_vp_from_dicts(vp_levels, vp_buy, vp_sell)

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

        STATEFUL: instead of recomputing the pattern from the last ~10 bars on
        every call, this advances a persistent state machine over each newly
        finalized bar only once:

            WAITING("") -> ABSORPTION -> ACCUMULATION -> AGGRESSION -> reset to ""

        Phase 1 — ABSORPTION: High-volume bar with tight range
            (volume > 1.5x average AND range < 0.5x average range)

        Phase 2 — ACCUMULATION: 2+ tight-range bars after absorption that keep
            trading within/near the POC (range < 0.7x average range AND the bar
            trades within 2 tick-steps of POC)

        Phase 3 — AGGRESSION: Breakout bar with expanding volume that closes
            beyond the VWAP band (volume > 1.2x average AND range > 1.0x
            average range AND close > VWAP + 1sigma for LONG / < VWAP - 1sigma
            for SHORT)

        A bar is only evaluated once; the phase persists between calls until
        a fresh bar after AGGRESSION resets the machine to WAITING.
        """
        if len(self._bars) < 5:
            return self._triple_a_snapshot()

        recent = self._bars[-10:]

        # Compute averages
        avg_vol = sum(b.volume for b in recent) / len(recent)
        avg_range = sum(b.high - b.low for b in recent) / len(recent)

        if avg_vol <= 0 or avg_range <= 0:
            return self._triple_a_snapshot()

        # Guard against the bar list being trimmed: drop stale references and
        # restart the walk from the current end of the list.
        if self._absorption_bar_index is not None and self._absorption_bar_index >= len(self._bars):
            self._triple_a_phase = ""
            self._absorption_bar_index = None
            self._accumulation_count = 0
            self._triple_a_direction = ""
        self._last_processed_idx = min(self._last_processed_idx, len(self._bars) - 1)

        # Advance the state machine over every bar finalized since the last call.
        while self._last_processed_idx < len(self._bars) - 1:
            idx = self._last_processed_idx + 1
            self._last_processed_idx = idx
            self._advance_triple_a(idx, self._bars[idx], avg_vol, avg_range)

        return self._triple_a_snapshot()

    def _advance_triple_a(
        self, idx: int, bar: RangeBar, avg_vol: float, avg_range: float
    ) -> None:
        """Feed one freshly finalized bar through the state machine."""
        # A new bar arriving after a signal starts a fresh cycle.
        if self._triple_a_phase == "AGGRESSION":
            self._triple_a_phase = ""
            self._absorption_bar_index = None
            self._accumulation_count = 0
            self._triple_a_direction = ""
            self._aggression_bar_index = -1

        bar_range = bar.high - bar.low

        if self._triple_a_phase == "":  # WAITING
            if bar.volume > avg_vol * 1.5 and bar_range < avg_range * 0.5:
                self._triple_a_phase = "ABSORPTION"
                self._absorption_bar_index = idx
                self._triple_a_absorption_idx = idx
                self._accumulation_count = 0
                self._triple_a_direction = ""

        elif self._triple_a_phase == "ABSORPTION":
            if self._is_accumulation_bar(bar, bar_range, avg_range):
                self._accumulation_count += 1
                if self._accumulation_count >= 2:
                    self._triple_a_phase = "ACCUMULATION"
            else:
                self._accumulation_count = 0

        elif self._triple_a_phase == "ACCUMULATION":
            direction = self._check_aggression(idx, bar, bar_range, avg_vol, avg_range)
            if direction:
                self._triple_a_phase = "AGGRESSION"
                self._triple_a_direction = direction
                self._aggression_bar_index = idx
                vp = self.get_volume_profile()
                self._poc_at_detection = vp.poc
                self._vah_at_detection = vp.vah
                self._val_at_detection = vp.val

    def _is_accumulation_bar(self, bar: RangeBar, bar_range: float, avg_range: float) -> bool:
        """True when a bar consolidates near the POC region (tight range, trades
        within 2 tick-steps of the session POC)."""
        if bar_range >= avg_range * 0.7:
            return False
        poc = self.get_volume_profile().poc
        if poc <= 0:
            return True
        tol = 2 * self._tick_size
        return bar.low <= poc + tol and bar.high >= poc - tol

    def _check_aggression(
        self, idx: int, bar: RangeBar, bar_range: float, avg_vol: float, avg_range: float
    ) -> str:
        """Return the direction ("LONG"/"SHORT") for a VWAP-band breakout bar,
        else "" when the bar does not qualify as aggression."""
        if bar.volume <= avg_vol * 1.2 or bar_range <= avg_range * 1.0:
            return ""
        vwap = self.get_vwap()
        if vwap <= 0:
            return ""

        closes = [b.close for b in self._bars[-10:]]
        mean = sum(closes) / len(closes)
        variance = sum((c - mean) ** 2 for c in closes) / len(closes)
        std = variance ** 0.5

        if bar.close > vwap + std:
            return "LONG"
        if bar.close < vwap - std:
            return "SHORT"
        return ""

    def _triple_a_snapshot(self) -> TripleAPattern:
        """Current state machine snapshot in the caller-facing TripleAPattern shape."""
        if self._triple_a_phase == "AGGRESSION":
            return TripleAPattern(
                detected=True,
                phase="AGGRESSION",
                direction=self._triple_a_direction,
                absorption_bar_index=(
                    self._absorption_bar_index
                    if self._absorption_bar_index is not None
                    else -1
                ),
                aggression_bar_index=self._aggression_bar_index,
                poc_at_detection=self._poc_at_detection,
                vah_at_detection=self._vah_at_detection,
                val_at_detection=self._val_at_detection,
            )
        if self._triple_a_phase in ("ABSORPTION", "ACCUMULATION"):
            return TripleAPattern(
                detected=False,
                phase=self._triple_a_phase,
                direction="",
                absorption_bar_index=(
                    self._absorption_bar_index
                    if self._absorption_bar_index is not None
                    else -1
                ),
                aggression_bar_index=-1,
            )
        return TripleAPattern()

    # ── Serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize state for WebSocket streaming."""
        bars = self.get_all_bars()
        session_vp = self.get_volume_profile()
        leg_vp = self.get_leg_volume_profile()
        triple_a = self.detect_triple_a()

        # Convert bars to OHLC-like format with sequential synthetic timestamps.
        # Closed bars always have synth_time > 0 (assigned in _finalize_bar).
        # The forming bar has synth_time == 0 — we use _next_ts + 1 so it is
        # strictly greater than the last closed bar (_next_ts - 60) and strictly
        # less than what the NEXT closed bar will receive (_next_ts), guaranteeing
        # lightweight-charts never sees a non-ascending time value.
        serialized_bars = []
        forming_ts = self._next_ts + 1  # safe placeholder for the live forming bar
        for b in bars:
            t = b.synth_time if getattr(b, "synth_time", 0) > 0 else forming_ts
            serialized_bars.append(
                {
                    "time": t,
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
            "sessionProfile": {
                "poc": session_vp.poc,
                "vah": session_vp.vah,
                "val": session_vp.val,
                "levels": [
                    {
                        "price": l.price,
                        "volume": l.volume,
                        "buyVolume": l.buy_volume,
                        "sellVolume": l.sell_volume,
                    }
                    for l in session_vp.levels[-200:]
                ],
            },
            "legProfile": {
                "poc": leg_vp.poc,
                "vah": leg_vp.vah,
                "val": leg_vp.val,
                "levels": [
                    {
                        "price": l.price,
                        "volume": l.volume,
                        "buyVolume": l.buy_volume,
                        "sellVolume": l.sell_volume,
                    }
                    for l in leg_vp.levels[-200:]
                ],
            },
            "volumeProfile": {
                "poc": session_vp.poc,
                "vah": session_vp.vah,
                "val": session_vp.val,
                "levels": [
                    {
                        "price": l.price,
                        "volume": l.volume,
                        "buyVolume": l.buy_volume,
                        "sellVolume": l.sell_volume,
                    }
                    for l in session_vp.levels[-200:]  # Retain for backward compat
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
