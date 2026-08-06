"""Candle Aggregator — Handles OHLCV candle aggregation from ticks.

Responsibilities:
- Tick-to-candle aggregation
- Volume tracking from cumulative data
- VWAP calculation
- Delta computation from buy/sell volumes
- Footprint accumulation
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel
from quant.amt.orderflow.footprint import TickFootprintAccumulator
from quant.amt.orderflow.tick_delta import TickDeltaClassifier, candle_delta_proxy
from quant.contracts.timezones import IST

logger = logging.getLogger(__name__)




def _new_candle_state() -> dict:
    """Create a new candle state dictionary."""
    return {
        "start": None,
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 0,
        "volume": 0,
        "buy_volume": 0,
        "oi": 0,
        "vwap_num": 0,
        "vwap_den": 0,
        "prev_cum_vol": -1,
        "candle_vol": 0,
        "prev_cum_buy": -1,
        "prev_cum_sell": -1,
        "candle_buy_vol": 0,
        "candle_sell_vol": 0,
    }


def _interval_to_seconds(interval: str) -> int:
    """Convert interval string to seconds.

    Args:
        interval: Interval string (e.g., "5m", "1h", "1d")

    Returns:
        Interval in seconds
    """
    unit = interval[-1]
    val = int(interval[:-1])
    if unit == "m":
        return val * 60
    elif unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    return val * 60


class CandleAggregator:
    """Aggregates ticks into OHLCV candles.

    This module encapsulates all candle aggregation logic, providing a single
    source of truth for candle building across the codebase.
    """

    def __init__(self, interval: str = "5m"):
        self._interval_secs = _interval_to_seconds(interval)
        self._candle_states: dict[str, dict] = {}
        self._fp_accumulators: dict[str, TickFootprintAccumulator] = {}
        self._delta_classifiers: dict[str, TickDeltaClassifier] = {}
        self._use_lee_ready: bool = False  # Set from feature flag

    def initialize_symbol(self, symbol: str) -> None:
        """Initialize state for a symbol.

        Args:
            symbol: Trading symbol
        """
        self._candle_states[symbol] = _new_candle_state()
        self._fp_accumulators[symbol] = TickFootprintAccumulator()
        self._delta_classifiers[symbol] = TickDeltaClassifier()

    def remove_symbol(self, symbol: str) -> None:
        """Clean up state for a symbol that is no longer active.

        Args:
            symbol: Trading symbol to remove
        """
        self._candle_states.pop(symbol, None)
        self._fp_accumulators.pop(symbol, None)
        self._delta_classifiers.pop(symbol, None)

    def _candle_start(self, ts: datetime) -> datetime:
        """Get candle start time by flooring to interval boundary.

        Args:
            ts: Timestamp

        Returns:
            Candle start time
        """
        epoch = int(ts.timestamp())
        floored = epoch - (epoch % self._interval_secs)
        return datetime.fromtimestamp(floored, tz=IST)

    def set_delta_mode(self, use_lee_ready: bool) -> None:
        """Set delta classification mode. True = Lee-Ready, False = body_ratio proxy."""
        self._use_lee_ready = use_lee_ready

    def aggregate(
        self,
        symbol: str,
        now: datetime,
        ltp: float,
        vol: int,
        cum_buy: int,
        cum_sell: int,
        oi: int,
        best_bid: float = 0.0,
        best_ask: float = 0.0,
    ) -> OHLC | None:
        """Aggregate a tick into the current candle.

        Args:
            symbol: Trading symbol
            now: Current timestamp
            ltp: Last traded price
            vol: Cumulative volume
            cum_buy: Cumulative buy quantity
            cum_sell: Cumulative sell quantity
            oi: Open interest
            best_bid: Best bid price (for Lee-Ready delta)
            best_ask: Best ask price (for Lee-Ready delta)

        Returns:
            OHLC if candle updated, None if tick invalid
        """
        if symbol not in self._candle_states:
            self.initialize_symbol(symbol)

        cs = self._candle_states[symbol]
        c_start = self._candle_start(now)

        # Volume from cumulative
        if cs["prev_cum_vol"] < 0:
            cs["prev_cum_vol"] = vol
            candle_vol = 0
        elif vol < cs["prev_cum_vol"]:
            cs["prev_cum_vol"] = vol
            candle_vol = 0
        else:
            candle_vol = vol - cs["prev_cum_vol"]
            # Contextual spike cap: >5% of cumulative likely means session reset
            vol_cap = (
                max(10000, cs["prev_cum_vol"] * 0.05)
                if cs["prev_cum_vol"] > 0
                else 10000
            )
            if candle_vol > vol_cap:
                cs["prev_cum_vol"] = vol
                candle_vol = vol_cap
            else:
                cs["prev_cum_vol"] = vol

        # Buy/sell from cumulative
        if cs["prev_cum_buy"] < 0:
            cs["prev_cum_buy"] = cum_buy
            cs["prev_cum_sell"] = cum_sell
            tick_buy = 0
            tick_sell = 0
        elif cum_buy < cs["prev_cum_buy"] or cum_sell < cs["prev_cum_sell"]:
            cs["prev_cum_buy"] = cum_buy
            cs["prev_cum_sell"] = cum_sell
            tick_buy = 0
            tick_sell = 0
        else:
            tick_buy = cum_buy - cs["prev_cum_buy"]
            tick_sell = cum_sell - cs["prev_cum_sell"]
            # Contextual cap: >5% of cumulative = likely session reset
            buy_sell_total = max(cs["prev_cum_buy"], 1) + max(cs["prev_cum_sell"], 1)
            bs_cap = max(10000, buy_sell_total * 0.05)
            if tick_buy > bs_cap:
                tick_buy = 0
            if tick_sell > bs_cap:
                tick_sell = 0
            cs["prev_cum_buy"] = cum_buy
            cs["prev_cum_sell"] = cum_sell

        if cs["start"] is None or c_start != cs["start"]:
            cs["start"] = c_start
            cs["open"] = ltp
            cs["high"] = ltp
            cs["low"] = ltp
            cs["close"] = ltp
            cs["candle_vol"] = candle_vol
            cs["candle_buy_vol"] = tick_buy
            cs["candle_sell_vol"] = tick_sell
            cs["buy_volume"] = 0
            cs["oi"] = oi
            cs["vwap_num"] = ltp * candle_vol
            cs["vwap_den"] = candle_vol
        else:
            cs["high"] = max(cs["high"], ltp)
            cs["low"] = min(cs["low"], ltp)
            cs["close"] = ltp
            cs["candle_vol"] += candle_vol
            cs["candle_buy_vol"] += tick_buy
            cs["candle_sell_vol"] += tick_sell
            cs["oi"] = oi
            cs["vwap_num"] += ltp * candle_vol
            cs["vwap_den"] += candle_vol

        vwap = cs["vwap_num"] / cs["vwap_den"] if cs["vwap_den"] > 0 else ltp

        cv = cs["candle_vol"]
        cbuy = cs["candle_buy_vol"]
        csell = cs["candle_sell_vol"]
        if cbuy > 0 or csell > 0:
            delta = float(cbuy - csell)
            buy_vol = float(cbuy)
        else:
            if self._use_lee_ready and best_bid > 0 and best_ask > 0:
                if symbol not in self._delta_classifiers:
                    self._delta_classifiers[symbol] = TickDeltaClassifier()
                td = self._delta_classifiers[symbol].classify(
                    price=cs["close"],
                    volume=cv,
                    bid=best_bid,
                    ask=best_ask,
                )
                delta = td.delta
            else:
                delta = candle_delta_proxy(
                    open_=cs["open"],
                    high=cs["high"],
                    low=cs["low"],
                    close=cs["close"],
                    volume=cv,
                )
            buy_vol = max(0.0, (cv + delta) / 2)

        return OHLC(
            time=cs["start"].isoformat(),
            open=cs["open"],
            high=cs["high"],
            low=cs["low"],
            close=cs["close"],
            volume=float(cv),
            vwap=vwap,
            taker_buy_volume=buy_vol,
            delta=delta,
        )

    def update_footprint(
        self,
        symbol: str,
        ltp: float,
        ltq: int,
        best_bid: float,
        best_ask: float,
        candle_time: datetime | None = None,
    ) -> None:
        """Update footprint accumulator with a tick.

        Args:
            symbol: Trading symbol
            ltp: Last traded price
            ltq: Last traded quantity
            best_bid: Best bid price
            best_ask: Best ask price
            candle_time: Candle timestamp
        """
        if symbol not in self._fp_accumulators:
            self._fp_accumulators[symbol] = TickFootprintAccumulator()

        candle_t = candle_time or self._candle_start(datetime.now(IST))
        self._fp_accumulators[symbol].on_tick(
            ltp,
            ltq,
            float(best_bid),
            float(best_ask),
            candle_t.isoformat(),
        )

    def get_footprint(self, symbol: str) -> dict | None:
        """Get footprint data for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Footprint data or None
        """
        if symbol not in self._fp_accumulators:
            return None
        return self._fp_accumulators[symbol].get_all()

    def validate_tick(self, tick: OHLC) -> str | None:
        """Validate a tick for obvious errors.

        Args:
            tick: OHLC tick to validate

        Returns:
            Error message if invalid, None if valid
        """
        for name, val in [
            ("open", tick.open),
            ("high", tick.high),
            ("low", tick.low),
            ("close", tick.close),
        ]:
            if math.isnan(val) or math.isinf(val) or val <= 0:
                return f"Invalid tick: {name}={val}"
        if math.isnan(tick.volume) or math.isinf(tick.volume) or tick.volume < 0:
            return f"Invalid tick: volume={tick.volume}"
        if tick.high < tick.low:
            return f"Invalid tick: high ({tick.high}) < low ({tick.low})"
        return None
