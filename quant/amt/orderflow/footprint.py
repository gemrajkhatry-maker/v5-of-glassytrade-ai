"""Footprint Analyzer — footprint chart generation domain service.

Uses real OHLC + Volume + Delta data and models the internal distribution
using Gaussian logic centred on the real VWAP, normalising totals to match
the real volume and delta exactly.

Incremental mode: caches previous results and only computes the last candle
when data grows by one.
"""

from __future__ import annotations

from quant.contracts.value_objects import OHLC, FootprintLevel, FootprintCandle
from quant.amt import compute as mc


class FootprintAnalyzer:
    """Pure domain service for footprint chart generation (incremental)."""

    def __init__(self) -> None:
        self._last_data_len: int = 0
        self._cached_result: dict[str, FootprintCandle] = {}

    def _generate_candle(self, candle: OHLC) -> FootprintCandle:
        """Generate a FootprintCandle for a single OHLC candle."""
        price_range = candle.high - candle.low

        # Flat candle
        if price_range <= 1e-9:
            buy_vol = (candle.volume + candle.delta) / 2
            sell_vol = (candle.volume - candle.delta) / 2
            level = FootprintLevel(
                price=candle.open,
                bid=int(sell_vol), ask=int(buy_vol),
                delta=candle.delta, imbalance=False,
            )
            return FootprintCandle(
                time=candle.time, levels=(level,),
                poc_price=candle.open, total_delta=candle.delta,
                step_price=(candle.close * 0.0001) or 0.01,
            )

        # Tick size — cap rows so each level gets >= 1 unit of volume.
        # For low-volume instruments (options), fewer rows = meaningful levels.
        max_rows = 30
        if candle.volume > 0:
            # Ensure at least ~1 unit per level: cap rows at volume / 2
            max_rows = max(5, min(30, int(candle.volume / 2)))

        tick_size = max(0.01, candle.close * 0.0001)
        estimated_steps = price_range / tick_size
        if estimated_steps > max_rows:
            tick_size = price_range / max_rows

        steps = max(3, min(max_rows, int(price_range / tick_size)))
        actual_step = max(price_range / steps, 1e-7)

        # Gaussian parameters (MLX-accelerated)
        mean = candle.vwap
        std_dev = price_range / 3.5
        if std_dev == 0:
            std_dev = 0.0001

        bucket_centers = [candle.low + i * actual_step for i in range(steps + 1)]
        weights = mc.gaussian_weights(bucket_centers, mean, std_dev)

        # Second pass: allocate volume using round() to avoid truncation
        buy_vol_total = max(0.0, (candle.volume + candle.delta) / 2)
        sell_vol_total = max(0.0, (candle.volume - candle.delta) / 2)

        raw_levels: list[tuple[float, int, int]] = []
        max_vol_level = 0
        poc_price = candle.open

        for i in range(steps + 1):
            price = candle.low + i * actual_step
            ratio = float(weights[i])
            ask_ = round(float(buy_vol_total) * ratio)
            bid_ = round(float(sell_vol_total) * ratio)
            if ask_ + bid_ > 0:
                raw_levels.append((price, bid_, ask_))
                level_vol = ask_ + bid_
                if level_vol > max_vol_level:
                    max_vol_level = level_vol
                    poc_price = price

        levels: list[FootprintLevel] = []
        for price, bid_, ask_ in reversed(raw_levels):
            levels.append(FootprintLevel(
                price=price, bid=bid_, ask=ask_,
                delta=ask_ - bid_,
                imbalance=(ask_ > bid_ * 3 or bid_ > ask_ * 3),
            ))

        return FootprintCandle(
            time=candle.time, levels=tuple(levels),
            poc_price=poc_price, total_delta=candle.delta,
            step_price=actual_step,
        )

    def generate(self, data: list[OHLC]) -> dict[str, FootprintCandle]:
        if not data:
            self._last_data_len = 0
            self._cached_result = {}
            return {}

        new_len = len(data)

        # If data grew by exactly 1, only compute the new candle (incremental)
        if new_len == self._last_data_len + 1 and self._cached_result:
            candle = data[-1]
            self._cached_result[candle.time] = self._generate_candle(candle)
            self._last_data_len = new_len
            return self._cached_result

        # Data shrank, reset, or first call — full rebuild
        result: dict[str, FootprintCandle] = {}
        for candle in data:
            result[candle.time] = self._generate_candle(candle)

        self._cached_result = result
        self._last_data_len = new_len
        return result


class TickFootprintAccumulator:
    """Accumulates real tick-level footprint data per candle period.

    Uses the tick rule to classify each trade as buy/sell aggression
    based on trade price vs best bid/ask from order book depth.
    """

    MAX_COMPLETED = 200  # Keep last N completed candles

    def __init__(self) -> None:
        self._current_candle_time: str = ""
        self._levels: dict[float, list[int, int]] = {}  # price -> [bid_vol, ask_vol]
        self._completed: dict[str, FootprintCandle] = {}
        self._prev_ltp: float = 0.0

    def on_tick(self, ltp: float, ltq: int, best_bid: float, best_ask: float, candle_time: str) -> None:
        """Process a single tick. Classify aggressor side using tick rule."""
        if ltq <= 0 or ltp <= 0:
            return

        # New candle period — finalize previous
        if candle_time != self._current_candle_time and self._current_candle_time:
            self._finalize_candle()
        self._current_candle_time = candle_time

        # Tick rule: classify aggressor
        mid = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else ltp
        if best_ask > 0 and ltp >= best_ask:
            side = 1  # ask (buyer lifted offer)
        elif best_bid > 0 and ltp <= best_bid:
            side = 0  # bid (seller hit bid)
        elif ltp > mid:
            side = 1  # above mid = likely buy
        elif ltp < mid:
            side = 0  # below mid = likely sell
        else:
            side = 1 if ltp >= self._prev_ltp else 0  # uptick/downtick rule

        self._prev_ltp = ltp

        # Accumulate at price level
        if ltp not in self._levels:
            self._levels[ltp] = [0, 0]
        self._levels[ltp][side] += ltq

    def _finalize_candle(self) -> None:
        """Convert current accumulated levels into a FootprintCandle."""
        if not self._levels:
            return
        candle = self._build_candle(self._current_candle_time, self._levels)
        self._completed[self._current_candle_time] = candle
        # Trim old candles
        if len(self._completed) > self.MAX_COMPLETED:
            keys = sorted(self._completed.keys())
            for k in keys[:len(keys) - self.MAX_COMPLETED]:
                del self._completed[k]
        self._levels = {}

    def _build_candle(self, time: str, levels: dict[float, list[int, int]]) -> FootprintCandle:
        """Build FootprintCandle with diagonal imbalance + stacked detection."""
        sorted_prices = sorted(levels.keys())
        if not sorted_prices:
            return FootprintCandle(time=time)

        # Step price = median price gap between levels (real tick size)
        if len(sorted_prices) >= 2:
            gaps = [sorted_prices[i+1] - sorted_prices[i] for i in range(len(sorted_prices)-1)]
            gaps.sort()
            step = gaps[len(gaps) // 2]  # median gap
        else:
            step = sorted_prices[0] * 0.0001 or 0.01

        # POC = price with highest total volume
        poc_price = sorted_prices[0]
        max_vol = 0

        # Build raw level data with diagonal imbalance detection
        # Diagonal: ask[N] vs bid[N-1] (buy imbalance), bid[N] vs ask[N+1] (sell imbalance)
        imbalance_dirs: list[int] = []  # 1=buy, -1=sell, 0=none
        raw: list[tuple[float, int, int, int, int]] = []  # (price, bid, ask, delta, imb_dir)

        for i, price in enumerate(sorted_prices):
            bid_vol, ask_vol = levels[price]
            delta = ask_vol - bid_vol
            total = bid_vol + ask_vol
            if total > max_vol:
                max_vol = total
                poc_price = price

            # Diagonal imbalance detection
            imb_dir = 0
            # Buy imbalance: ask[N] vs bid[N-1]
            if i > 0:
                prev_bid = levels[sorted_prices[i-1]][0]
                if prev_bid == 0 and ask_vol >= 5:
                    imb_dir = 1  # auto-imbalance (zero on weak side with real volume)
                elif prev_bid > 0 and ask_vol >= 3 * prev_bid:
                    imb_dir = 1
            # Sell imbalance: bid[N] vs ask[N+1]
            if i < len(sorted_prices) - 1 and imb_dir == 0:
                next_ask = levels[sorted_prices[i+1]][1]
                if next_ask == 0 and bid_vol >= 5:
                    imb_dir = -1
                elif next_ask > 0 and bid_vol >= 3 * next_ask:
                    imb_dir = -1

            imbalance_dirs.append(imb_dir)
            raw.append((price, bid_vol, ask_vol, delta, imb_dir))

        # Stacked imbalance: 3+ consecutive same-direction imbalances with real volume
        stacked_flags = [False] * len(raw)
        for i in range(len(imbalance_dirs) - 2):
            d = imbalance_dirs[i]
            if d != 0 and imbalance_dirs[i+1] == d and imbalance_dirs[i+2] == d:
                v0 = raw[i][2] if d > 0 else raw[i][1]
                v1 = raw[i+1][2] if d > 0 else raw[i+1][1]
                v2 = raw[i+2][2] if d > 0 else raw[i+2][1]
                if v0 + v1 + v2 >= 15:
                    stacked_flags[i] = True
                    stacked_flags[i+1] = True
                    stacked_flags[i+2] = True

        # Build FootprintLevels (descending price order for frontend)
        fp_levels: list[FootprintLevel] = []
        total_delta = 0.0
        for i in range(len(raw) - 1, -1, -1):
            price, bid_vol, ask_vol, delta, imb_dir = raw[i]
            total_delta += delta
            fp_levels.append(FootprintLevel(
                price=price,
                bid=bid_vol,
                ask=ask_vol,
                delta=delta,
                imbalance=imb_dir != 0,
                stacked=stacked_flags[i],
            ))

        return FootprintCandle(
            time=time,
            levels=tuple(fp_levels),
            poc_price=poc_price,
            total_delta=total_delta,
            step_price=step,
        )

    def get_all(self) -> dict[str, FootprintCandle]:
        """Return all completed candles + current in-progress candle."""
        result = dict(self._completed)
        if self._current_candle_time and self._levels:
            result[self._current_candle_time] = self._build_candle(
                self._current_candle_time, self._levels
            )
        return result


def detect_absorption(candle: FootprintCandle, price_change_pct: float) -> dict | None:
    """Detect absorption: high aggressive volume with minimal price movement.

    Absorption = big aggression on one side but price doesn't move = hidden
    institutional activity on the opposite side absorbing the flow.
    """
    if not candle.levels:
        return None

    total_bid = sum(lv.bid for lv in candle.levels)
    total_ask = sum(lv.ask for lv in candle.levels)
    total_vol = total_bid + total_ask
    if total_vol == 0:
        return None

    # Need significant volume (at least 2x the average per-level volume)
    avg_per_level = total_vol / len(candle.levels)
    dominant_side_vol = max(total_bid, total_ask)

    # Absorption criteria:
    # 1. One side has >65% of volume (strong aggression)
    # 2. Price moved <0.15% (absorbed — no impact)
    dominance_ratio = dominant_side_vol / total_vol
    if dominance_ratio < 0.65:
        return None
    if abs(price_change_pct) > 0.15:
        return None

    side = "SELL" if total_bid > total_ask else "BUY"
    # Absorption is OPPOSITE to the aggressive side:
    # Aggressive sellers absorbed by hidden buyers → bullish absorption
    absorbed_by = "BUY" if side == "SELL" else "SELL"
    return {
        "detected": True,
        "aggressive_side": side,
        "absorbed_by": absorbed_by,
        "volume": dominant_side_vol,
        "dominance_ratio": dominance_ratio,
        "price_change_pct": price_change_pct,
    }


def detect_contested_zone(candles: list[FootprintCandle], window: int = 2) -> bool:
    """Detect contested zone: both BUY and SELL stacked imbalances colliding in the same price zone.

    When both sides show opposing stacked imbalances colliding at the same price zone,
    the market is contested — neither side has control. Best action is FLAT.
    """
    recent = candles[-window:] if len(candles) >= window else candles
    buy_stacked_prices: list[float] = []
    sell_stacked_prices: list[float] = []

    for candle in recent:
        if not candle.levels:
            continue
        for lv in candle.levels:
            if lv.stacked:
                if lv.delta > 0:
                    buy_stacked_prices.append(float(lv.price))
                elif lv.delta < 0:
                    sell_stacked_prices.append(float(lv.price))

    if not buy_stacked_prices or not sell_stacked_prices:
        return False

    # ponytail: opposing stacked imbalances collide at the same price zone within 5 ticks (0.25-0.50 pts)
    for bp in buy_stacked_prices:
        for sp in sell_stacked_prices:
            if abs(bp - sp) <= 0.50:
                return True

    return False
