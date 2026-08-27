"""AMTEngine — encapsulates AMT analysis, history seeding, and candle management.

Extracted from QuantEngine to improve locality: AMT analysis is a single
concern with its own state (candle ring, incremental profile, session tracking).
The engine receives dependencies via constructor injection.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable

from quant.amt.analyzer import AMTAnalyzer
from quant.amt.dto import amt_result_to_dto
from quant.amt.profile.volume_profile import IncrementalVolumeProfile
from quant.amt.orderflow.footprint import TickFootprintAccumulator
from quant.amt.session.npoc import NPOCTracker
from quant.bars import Bar
from quant.contracts.value_objects import FloatOHLC
from quant.session_levels import SessionLevelStore
from quant.state import _epoch_to_iso, session_date_key

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# History-seed startup backoff
# ---------------------------------------------------------------------------
# Startup spawns one AMT history-seed thread per engine almost simultaneously
# (QuantCoordinator._spawn_engine starts every engine in a tight loop). Dhan's
# REST history endpoint rate-limits bursts ([DH-3001]); a burst of concurrent
# get_historical calls trips the broker circuit breaker before the first seed
# succeeds. Fix: stagger first-fetch starts across engines (fixed interval +
# jitter) and retry failures with jittered exponential backoff, so the seed
# is absorbed without ever opening the breaker.
_SEED_STAGGER_SEC = 2.0      # spacing between per-engine first-fetch starts
_SEED_STAGGER_JITTER = 0.5   # random noise so repeated restarts don't re-collide
_SEED_FETCH_RETRIES = 3      # max attempts per symbol (1 + 2 backoff retries)
_SEED_FETCH_BASE_DELAY = 1.5  # exponential backoff base between attempts (s)
_SEED_GATE_LOCK = threading.Lock()
_SEED_NEXT_START = 0.0


def _reserve_seed_slot() -> None:
    """Serialise and stagger history-seed starts across engines.

    Each seed thread reserves the next slot (``stagger`` after the previous
    reservation, plus up to ``jitter`` of random noise) and sleeps until its
    turn, so N engines never hit Dhan's REST history endpoint at the same
    instant. Thread-safe; the sleep happens outside the lock so one engine's
    delay never blocks another's reservation.
    """
    global _SEED_NEXT_START
    with _SEED_GATE_LOCK:
        now = time.monotonic()
        target = max(now, _SEED_NEXT_START)
        _SEED_NEXT_START = target + _SEED_STAGGER_SEC
    delay = max(0.0, target - now) + random.uniform(0.0, _SEED_STAGGER_JITTER)
    if delay > 0:
        logger.info("AMT history seed: staggering start by %.2fs", delay)
        time.sleep(delay)


def _get_val(c, key, default=0.0):
    if isinstance(c, dict):
        return c.get(key, default)
    return getattr(c, key, default)


def session_scope(candles: list) -> list:
    """Keep only candles from the most recent session (the calendar date of the newest candle)."""
    if not candles:
        return []
    newest = candles[-1]
    newest_time = str(_get_val(newest, "time", ""))
    date = session_date_key(newest_time)
    if not date:
        return list(candles)
    return [c for c in candles if session_date_key(str(_get_val(c, "time", ""))) == date]


def to_float_ohlc(c) -> FloatOHLC:
    """Convert any OHLC-like object or dict to FloatOHLC."""
    return FloatOHLC(
        time=str(_get_val(c, "time", "")),
        open=float(_get_val(c, "open", 0.0)),
        high=float(_get_val(c, "high", 0.0)),
        low=float(_get_val(c, "low", 0.0)),
        close=float(_get_val(c, "close", 0.0)),
        volume=float(_get_val(c, "volume", 0.0)),
        vwap=float(_get_val(c, "vwap", 0.0) or 0.0),
        taker_buy_volume=float(_get_val(c, "taker_buy_volume", _get_val(c, "takerBuyVolume", 0.0)) or 0.0),
        delta=float(_get_val(c, "delta", 0.0) or 0.0),
    )


def to_bar(c) -> Bar:
    """History OHLC -> decision-path Bar (buy_volume from taker_buy_volume)."""
    vol = float(_get_val(c, "volume", 0.0) or 0.0)
    buy = float(_get_val(c, "taker_buy_volume", _get_val(c, "takerBuyVolume", 0.0)) or 0.0)
    return Bar(
        time=str(_get_val(c, "time", "")),
        open=float(_get_val(c, "open", 0.0)),
        high=float(_get_val(c, "high", 0.0)),
        low=float(_get_val(c, "low", 0.0)),
        close=float(_get_val(c, "close", 0.0)),
        volume=vol,
        buy_volume=buy,
        sell_volume=max(0.0, vol - buy),
        delta=float(_get_val(c, "delta", 0.0) or 0.0),
        vwap=float(_get_val(c, "vwap", 0.0) or 0.0),
    )


class AMTEngine:
    """Owns the AMT candle ring, incremental profile, analyzer, and seed logic.
    
    The AMTEngine manages all state related to AMT analysis:
    - Candle ring (rolling 1000-bar window)
    - Incremental volume profile
    - Session date tracking and rollover
    - History seeding from REST
    
    Dependencies are injected via constructor:
    - coordinator: AuctionCoordinator for seeding history
    - session_levels: SessionLevelStore for persisting session POC/VAH/VAL
    - history_source: IMarketData adapter for fetching history
    - underlying_fn: Callable that returns the underlying symbol
    - get_depth: Callable that returns the current order book
    - get_risk_pnl: Callable that returns the current session PnL
    """

    def __init__(
        self,
        symbol: str,
        market: str,
        session_levels: SessionLevelStore,
        history_source=None,
        underlying_fn: Callable[[], str] | None = None,
        get_depth: Callable[[], object | None] | None = None,
        get_risk_pnl: Callable[[], float] | None = None,
        interval_seconds: int = 60,
    ) -> None:
        self.symbol = symbol
        self._market = market
        self._session_levels = session_levels
        self._history_source = history_source
        self._underlying_fn = underlying_fn or (lambda: "NIFTY")
        self._get_depth = get_depth or (lambda: None)
        self._get_risk_pnl = get_risk_pnl or (lambda: 0.0)
        self._interval_seconds = interval_seconds

        # AMT state
        self._amt_analyzer = AMTAnalyzer()
        self._amt_candles: list[FloatOHLC] = []
        self._amt_lock = threading.Lock()
        self._amt_incremental: IncrementalVolumeProfile | None = None
        self._footprint = TickFootprintAccumulator()
        
        # Session tracking
        self._session_date: str | None = None
        self._prior = session_levels.load_levels(symbol)
        self._npoc = NPOCTracker(storage_port=session_levels)
        self._npoc.load_from_storage(self._underlying())
        
        # State for engine integration
        self._last_amt_dto: dict | None = None
        self._warm_bars: int = 0
        self._amt_fail_logged: bool = False

    def _underlying(self) -> str:
        return self._underlying_fn()

    def on_tick(self, tick, current_bar) -> None:
        if current_bar is None:
            return
            
        best_bid = 0.0
        best_ask = 0.0
        if tick.depth:
            bids = tick.depth.get("bids", [])
            asks = tick.depth.get("asks", [])
            if bids:
                best_bid = float(bids[0].get("price", 0.0))
            if asks:
                best_ask = float(asks[0].get("price", 0.0))
                
        candle_time = _epoch_to_iso(current_bar.time)
        with self._amt_lock:
            self._footprint.on_tick(
                ltp=tick.price,
                ltq=int(tick.volume),
                best_bid=best_bid,
                best_ask=best_ask,
                candle_time=candle_time
            )

    def seed(self) -> None:
        """Best-effort: seed the AMT candle ring from REST history.

        Synchronous so spawn cannot start live bars before today's session
        profile exists. Sequential coordinator spawn is the rate-limit stagger
        (``_reserve_seed_slot`` remains for a future parallel seed).
        """
        if self._history_source is None:
            return

        candles: list = []
        seed_interval = self._seed_interval_str()
        for attempt in range(1, _SEED_FETCH_RETRIES + 1):
            try:
                result = self._history_source.fetch_history(
                    self.symbol, seed_interval, 500
                )
                awaitable = inspect.isawaitable(result)
                candles = asyncio.run(result) if awaitable else (result or [])
            except Exception as e:
                awaitable = True
                if not isinstance(e, (TimeoutError, ConnectionError, OSError, asyncio.CancelledError)):
                    logger.critical("Unexpected error", exc_info=True)
                logger.warning(
                    "AMT history seed failed for %s (attempt %d/%d)",
                    self.symbol, attempt, _SEED_FETCH_RETRIES, exc_info=True,
                )
                candles = []
            if candles:
                break
            # ponytail: sync [] means no history source, not DH-3001. Only async
            # empty responses (Dhan swallowed rate-limit) are retried.
            if not awaitable:
                break
            if attempt < _SEED_FETCH_RETRIES:
                delay = _SEED_FETCH_BASE_DELAY * (
                    2 ** (attempt - 1)
                ) + random.uniform(0.0, 1.0)
                logger.info(
                    "AMT history seed retry %d/%d for %s in %.1fs",
                    attempt + 1, _SEED_FETCH_RETRIES, self.symbol, delay,
                )
                time.sleep(delay)
        if not candles:
            return

        # ponytail: cold-start prior session levels from history if storage was empty
        if not self._prior or not self._prior.get("poc"):
            prev_sessions: dict[str, list] = {}
            for c in candles:
                c_time = str(_get_val(c, "time", ""))
                d_key = session_date_key(c_time)
                if d_key:
                    prev_sessions.setdefault(d_key, []).append(c)
            today_key = session_date_key(str(_get_val(candles[-1], "time", ""))) if candles else None
            other_dates = sorted([d for d in prev_sessions if d != today_key])
            if other_dates:
                last_date = other_dates[-1]
                prev_candles = [to_float_ohlc(c) for c in prev_sessions[last_date]]
                if len(prev_candles) >= 5:
                    prev_inc = IncrementalVolumeProfile()
                    for pc in prev_candles:
                        prev_inc.update(pc)
                    try:
                        prev_res = self._amt_analyzer.analyze(prev_candles, incremental_profile=prev_inc)
                        if prev_res.poc > 0:
                            self._prior = {
                                "poc": float(prev_res.poc),
                                "vah": float(prev_res.value_area_high),
                                "val": float(prev_res.value_area_low),
                            }
                            self._session_levels.save_levels(
                                self.symbol, last_date, float(prev_res.poc), float(prev_res.value_area_high), float(prev_res.value_area_low)
                            )
                            self._npoc.add_session_poc(self._underlying(), last_date, float(prev_res.poc))
                            logger.info(
                                "Cold-start seeded prior session levels for %s (%s): POC=%.2f VAH=%.2f VAL=%.2f",
                                self.symbol, last_date, prev_res.poc, prev_res.value_area_high, prev_res.value_area_low
                            )
                    except Exception:
                        pass

        scoped = session_scope(candles)
        with self._amt_lock:
            if self._amt_candles:
                return  # live bars already flowing — keep them
            ohlcs = [to_float_ohlc(c) for c in scoped]
            self._amt_candles = ohlcs
            inc = IncrementalVolumeProfile()
            for c in ohlcs:
                inc.update(c)
            self._amt_incremental = inc
            # ponytail: warm_bars tracks available history depth (>= 15) so Phase 2 morning entries (09:30+) aren't blocked by cold-session warmup lock
            self._warm_bars = len(candles)
            if ohlcs:
                last_ohlc = ohlcs[-1]
                iso_date = session_date_key(last_ohlc.time)
                if iso_date:
                    self._session_date = iso_date
                try:
                    result = self._amt_analyzer.analyze(
                        ohlcs,
                        order_book=self._get_depth(),
                        incremental_profile=inc,
                        cushion_tier="Conservative",
                        session_pnl=self._get_risk_pnl(),
                        underlying=self._underlying(),
                        symbol=self.symbol,
                        prior_poc=self._prior["poc"],
                        prior_vah=self._prior["vah"],
                        prior_val=self._prior["val"],
                        npoc_tracker=self._npoc,
                        option_tick=last_ohlc,
                        footprint_accumulator=self._footprint,
                    )
                    self._last_amt_dto = amt_result_to_dto(result)
                except Exception:
                    logger.warning("Initial AMT analyze after seed failed for %s", self.symbol, exc_info=True)
        logger.info(
            "AMT seeded %d session candles for %s (initial DTO: %s)", len(scoped), self.symbol, bool(self._last_amt_dto)
        )

    def _seed_interval_str(self) -> str:
        """Dhan history interval string matching the engine's bar aggregation."""
        seconds = self._interval_seconds
        if seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        if seconds % 60 == 0:
            return f"{seconds // 60}m"
        return f"{seconds}s"

    def analyze(self, bar) -> dict:
        """Append the closed bar to the AMT ring and run the full AMTAnalyzer.

        Returns the complete 60-field ``amt`` DTO (profile histogram, market
        state, VWAP bands, LVNs/HVNs, absorption, ...) that the frontend
        ``AMTAnalysis`` contract expects. Called once per bar close on the
        engine thread — the analyzer's rolling session state accumulates
        exactly one candle per call.
        """
        # Session rollover: when the bar's date changes, the previous session
        # is complete. Persist its levels and reload the prior levels.
        iso_now = _epoch_to_iso(bar.time)
        iso_date = session_date_key(iso_now)
        if iso_date and self._session_date and iso_date != self._session_date:
            prev = self._last_amt_dto or {}
            prev_poc = float(prev.get("poc") or 0.0)
            if prev_poc > 0:
                self._session_levels.save_levels(
                    self.symbol,
                    self._session_date,
                    prev_poc,
                    float(prev.get("valueAreaHigh") or 0.0),
                    float(prev.get("valueAreaLow") or 0.0),
                )
                self._npoc.add_session_poc(
                    self._underlying(), self._session_date, prev_poc
                )
            self._prior = self._session_levels.load_levels(self.symbol)
        if iso_date:
            self._session_date = iso_date
        try:
            ohlc = FloatOHLC(
                time=iso_now,
                open=float(bar.open), high=float(bar.high),
                low=float(bar.low), close=float(bar.close),
                volume=float(bar.volume), vwap=float(bar.vwap or 0.0),
                taker_buy_volume=float(bar.buy_volume), delta=float(bar.delta),
            )
        except Exception:
            logger.warning("AMT bar->OHLC mapping failed: %r — keeping last DTO", bar, exc_info=True)
            return self._last_amt_dto or {}
        if ohlc is not None:
            with self._amt_lock:
                self._amt_candles.append(ohlc)
                oldest: FloatOHLC | None = None
                if len(self._amt_candles) > 1000:
                    oldest = self._amt_candles[0]
                    self._amt_candles = self._amt_candles[-1000:]
                if self._amt_incremental is not None:
                    self._amt_incremental.update(ohlc, oldest)
        try:
            with self._amt_lock:
                candles = list(self._amt_candles)
                incremental = self._amt_incremental
            result = self._amt_analyzer.analyze(
                candles,
                order_book=self._get_depth(),
                incremental_profile=incremental,
                cushion_tier="Conservative",
                session_pnl=self._get_risk_pnl(),
                underlying=self._underlying(),
                symbol=self.symbol,
                prior_poc=self._prior["poc"],
                prior_vah=self._prior["vah"],
                prior_val=self._prior["val"],
                npoc_tracker=self._npoc,
                option_tick=ohlc,
                footprint_accumulator=self._footprint,
            )
        except Exception:
            if not self._amt_fail_logged:
                logger.warning(
                    "AMT analyze failed for %s — keeping last good DTO",
                    self.symbol, exc_info=True,
                )
                self._amt_fail_logged = True
            return self._last_amt_dto or {}
        dto = amt_result_to_dto(result)
        with self._amt_lock:
            self._last_amt_dto = dto
        return dto

    @property
    def warm_bars(self) -> int:
        return self._warm_bars

    @property
    def last_amt_dto(self) -> dict | None:
        with self._amt_lock:
            return self._last_amt_dto

    @property
    def last_bar(self) -> Bar | None:
        with self._amt_lock:
            if not self._amt_candles:
                return None
            return to_bar(self._amt_candles[-1])



