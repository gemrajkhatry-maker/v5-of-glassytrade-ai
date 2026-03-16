"""CandleBuilderProcessor — aggregates raw ticks into OHLCV candles.

Consumes RawTickMessage from inbox["raw_ticks"].
Produces CandleMessage to outbox["candles"]:
  - closed=False on every tick (live/partial candle update)
  - closed=True  when a candle period boundary is crossed (final bar)

Completely data-source agnostic: it only cares about the RawTickMessage
contract. The same processor handles WS, REST-poll, file-replay, or sim ticks.

Configuration (ProcessorConfig.settings):
  interval: str  — candle period, e.g. "1m", "5m", "15m", "1h" (default "5m")
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from app.pipeline.channel import Channel
from app.pipeline.message import CandlePayload, Message, RawTickMessage
from app.pipeline.processor import BaseProcessor, ProcessorConfig

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Interval parsing
# ---------------------------------------------------------------------------

_SUFFIX_TO_MINUTES: dict[str, int] = {
    "m": 1,
    "h": 60,
    "d": 1440,
}


def _parse_interval_minutes(interval: str) -> int:
    """Convert interval string to minutes.

    Examples:
        "1m"  -> 1
        "5m"  -> 5
        "15m" -> 15
        "1h"  -> 60
    """
    interval = interval.strip().lower()
    for suffix, multiplier in _SUFFIX_TO_MINUTES.items():
        if interval.endswith(suffix):
            try:
                value = int(interval[: -len(suffix)])
            except ValueError:
                raise ValueError(f"Invalid interval '{interval}': cannot parse numeric part")
            if value <= 0:
                raise ValueError(f"Invalid interval '{interval}': must be positive")
            return value * multiplier
    # Pure integer treated as minutes
    try:
        return int(interval)
    except ValueError:
        raise ValueError(f"Unrecognised interval format: '{interval}'")


def _floor_to_interval(ts: datetime, interval_minutes: int) -> datetime:
    """Return the candle-open timestamp for *ts* (floored to interval boundary).

    Example: ts=09:17:32, interval=5m  ->  09:15:00
    """
    epoch = int(ts.timestamp())
    interval_secs = interval_minutes * 60
    floored = epoch - (epoch % interval_secs)
    return datetime.fromtimestamp(floored, tz=IST)


# ---------------------------------------------------------------------------
# Per-symbol mutable candle state
# ---------------------------------------------------------------------------

@dataclass
class _CandleState:
    """Mutable accumulator for the candle currently being built."""

    start: Optional[datetime] = None
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    candle_vol: float = 0.0
    candle_buy_vol: float = 0.0
    candle_sell_vol: float = 0.0
    vwap_num: float = 0.0
    vwap_den: float = 0.0

    # Cumulative counters from previous tick — used to compute per-tick deltas
    prev_cum_vol: int = -1
    prev_cum_buy: int = -1
    prev_cum_sell: int = -1


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------

class CandleBuilderProcessor(BaseProcessor):
    """Aggregates RawTickMessages into OHLCV CandleMessages.

    One processor instance may handle multiple symbols simultaneously:
    separate _CandleState objects are maintained per symbol.

    inbox  channels:
        "raw_ticks" — RawTickMessage stream

    outbox channels:
        "candles"   — CandleMessage stream (closed=False live, closed=True final)
    """

    name = "candle_builder"

    async def setup(self, config: ProcessorConfig) -> None:
        await super().setup(config)
        interval_str: str = config.settings.get("interval", "5m")
        self._interval_minutes: int = _parse_interval_minutes(interval_str)
        self._interval_str: str = interval_str
        # Per-symbol candle accumulators
        self._states: Dict[str, _CandleState] = {}

    async def process(
        self,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None:
        """Main loop: read raw ticks, emit live + closed candle messages."""
        in_ch: Channel = inbox["raw_ticks"]
        out_ch: Channel = outbox["candles"]

        async for tick_msg in in_ch:
            tick_msg: RawTickMessage
            try:
                await self._handle_tick(tick_msg, out_ch)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "[%s] Error processing tick for %s",
                    self.name,
                    tick_msg.symbol,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_tick(self, msg: RawTickMessage, out: Channel) -> None:
        """Process a single raw tick and emit the appropriate CandleMessages."""
        symbol = msg.symbol
        p = msg.payload
        ts = msg.timestamp  # market time (IST)

        candle_ts = _floor_to_interval(ts, self._interval_minutes)

        # Initialise per-symbol state on first tick
        if symbol not in self._states:
            self._states[symbol] = _CandleState()

        cs = self._states[symbol]

        # -----------------------------------------------------------------
        # 1. Compute per-tick volume and delta from cumulative counters
        # -----------------------------------------------------------------
        tick_vol, tick_buy, tick_sell = self._compute_per_tick_values(cs, p)

        # -----------------------------------------------------------------
        # 2. Candle period management
        # -----------------------------------------------------------------
        if cs.start is None:
            # First tick for this symbol: start a new candle
            self._start_candle(cs, candle_ts, p.ltp, tick_vol, tick_buy, tick_sell)
            live_msg = self._build_message(msg, cs, closed=False)
            await self._safe_send(out, live_msg)

        elif candle_ts == cs.start:
            # Same candle period: update running values
            self._update_candle(cs, p.ltp, tick_vol, tick_buy, tick_sell)
            live_msg = self._build_message(msg, cs, closed=False)
            await self._safe_send(out, live_msg)

        else:
            # New candle period: close the previous candle, open a new one
            closed_msg = self._build_message(msg, cs, closed=True)
            await self._safe_send(out, closed_msg)

            self._start_candle(cs, candle_ts, p.ltp, tick_vol, tick_buy, tick_sell)
            live_msg = self._build_message(msg, cs, closed=False)
            await self._safe_send(out, live_msg)

    def _compute_per_tick_values(
        self,
        cs: _CandleState,
        p,  # RawTickPayload
    ) -> tuple[float, float, float]:
        """Extract per-tick volume and buy/sell from cumulative counters.

        Mirrors the engine's _aggregate_candle logic:
        - On first tick (prev_cum_vol == -1): baseline the counters, return zeros
        - On reset (cumulative went backwards): re-baseline, return zeros
        - Spike cap (>5% of cumulative): treat as session reset, return zeros
        """
        vol = int(p.volume)
        cum_buy = int(p.total_buy_qty)
        cum_sell = int(p.total_sell_qty)

        # --- Volume ---
        if cs.prev_cum_vol < 0:
            cs.prev_cum_vol = vol
            tick_vol = 0.0
        elif vol < cs.prev_cum_vol:
            # Cumulative counter reset (session restart)
            cs.prev_cum_vol = vol
            tick_vol = 0.0
        else:
            tick_vol = float(vol - cs.prev_cum_vol)
            # Contextual spike cap: >5% of cumulative likely means session reset
            vol_cap = max(10000, cs.prev_cum_vol * 0.05) if cs.prev_cum_vol > 0 else 10000
            if tick_vol > vol_cap:
                cs.prev_cum_vol = vol
                tick_vol = 0.0
            else:
                cs.prev_cum_vol = vol

        # --- Buy / sell ---
        if cs.prev_cum_buy < 0:
            cs.prev_cum_buy = cum_buy
            cs.prev_cum_sell = cum_sell
            tick_buy = 0.0
            tick_sell = 0.0
        elif cum_buy < cs.prev_cum_buy or cum_sell < cs.prev_cum_sell:
            cs.prev_cum_buy = cum_buy
            cs.prev_cum_sell = cum_sell
            tick_buy = 0.0
            tick_sell = 0.0
        else:
            tick_buy = float(cum_buy - cs.prev_cum_buy)
            tick_sell = float(cum_sell - cs.prev_cum_sell)
            # Spike cap
            buy_sell_total = max(cs.prev_cum_buy, 1) + max(cs.prev_cum_sell, 1)
            bs_cap = max(10000, buy_sell_total * 0.05)
            if tick_buy > bs_cap:
                tick_buy = 0.0
            if tick_sell > bs_cap:
                tick_sell = 0.0
            cs.prev_cum_buy = cum_buy
            cs.prev_cum_sell = cum_sell

        return tick_vol, tick_buy, tick_sell

    def _start_candle(
        self,
        cs: _CandleState,
        candle_ts: datetime,
        ltp: float,
        tick_vol: float,
        tick_buy: float,
        tick_sell: float,
    ) -> None:
        """Reset the candle state to begin a new period."""
        cs.start = candle_ts
        cs.open = ltp
        cs.high = ltp
        cs.low = ltp
        cs.close = ltp
        cs.candle_vol = tick_vol
        cs.candle_buy_vol = tick_buy
        cs.candle_sell_vol = tick_sell
        cs.vwap_num = ltp * tick_vol
        cs.vwap_den = tick_vol

    def _update_candle(
        self,
        cs: _CandleState,
        ltp: float,
        tick_vol: float,
        tick_buy: float,
        tick_sell: float,
    ) -> None:
        """Update an in-progress candle with the latest tick values."""
        cs.high = max(cs.high, ltp)
        cs.low = min(cs.low, ltp)
        cs.close = ltp
        cs.candle_vol += tick_vol
        cs.candle_buy_vol += tick_buy
        cs.candle_sell_vol += tick_sell
        cs.vwap_num += ltp * tick_vol
        cs.vwap_den += tick_vol

    def _compute_delta(self, cs: _CandleState) -> float:
        """Compute candle delta (buy_vol - sell_vol), with body-ratio fallback."""
        if cs.candle_buy_vol > 0 or cs.candle_sell_vol > 0:
            return cs.candle_buy_vol - cs.candle_sell_vol
        # Fallback: body-ratio proxy (no depth data available)
        spread = cs.high - cs.low
        cv = cs.candle_vol
        if spread > 0 and cv > 0:
            body_ratio = (cs.close - cs.open) / spread
            return body_ratio * cv
        return 0.0

    def _build_message(
        self,
        source_msg: RawTickMessage,
        cs: _CandleState,
        closed: bool,
    ) -> Message:
        """Construct a CandleMessage from the current candle state."""
        assert cs.start is not None, "Candle state must have a start timestamp"

        vwap = cs.vwap_num / cs.vwap_den if cs.vwap_den > 0 else cs.close
        delta = self._compute_delta(cs)

        payload = CandlePayload(
            time=cs.start.isoformat(),
            open=cs.open,
            high=cs.high,
            low=cs.low,
            close=cs.close,
            volume=cs.candle_vol,
            delta=delta,
            vwap=vwap,
            closed=closed,
        )
        return Message(
            payload=payload,
            symbol=source_msg.symbol,
            timestamp=cs.start,
            correlation_id=source_msg.correlation_id,
            source_processor=self.name,
            pipeline_id=source_msg.pipeline_id,
        )
