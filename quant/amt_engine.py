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
from typing import Any, Callable

from quant.amt.analyzer import AMTAnalyzer
from quant.amt.dto import amt_result_to_dto
from quant.amt.snapshot import AnalysisSnapshot, analysis_snapshot_from_result
from quant.amt.session_kernel import SessionKernel
from quant.amt.profile.volume_profile import IncrementalVolumeProfile
from quant.amt.orderflow.footprint import TickFootprintAccumulator
from quant.amt.session.npoc import NPOCTracker
from quant.bars import Bar
from quant.contracts.constants import SEED_CACHE_TTL_SECONDS
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
_SEED_STAGGER_SEC = 0.8      # spacing between per-engine first-fetch starts
_SEED_STAGGER_JITTER = 0.2   # random noise so repeated restarts don't re-collide
_SEED_FETCH_RETRIES = 4      # max attempts per symbol (1 + 3 backoff retries)
_SEED_FETCH_BASE_DELAY = 1.0  # exponential backoff base between attempts (s)
_SEED_GATE_LOCK = threading.Lock()
_SEED_NEXT_START = 0.0
_SEED_CACHE: dict[tuple[str, str], tuple[float, list]] = {}


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
    """Owns the AMT candle ring, incremental profile, analyzer, and seed logic."""

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
        seed_scheduler: Any = None,
        range_bars_enabled: bool = False,
        tick_size: float = 0.05,
    ) -> None:
        self.symbol = symbol
        self._market = market
        self._session_levels = session_levels
        self._history_source = history_source
        self._seed_scheduler = seed_scheduler
        self._underlying_fn = underlying_fn or (lambda: "NIFTY")
        self._get_depth = get_depth or (lambda: None)
        self._get_risk_pnl = get_risk_pnl or (lambda: 0.0)
        self._interval_seconds = interval_seconds
        self._tick_size = float(tick_size)
        # Plan T8: range mode seeds synth range bars; seed-only analyze never
        # emits drive / hard absorption / Triple-A progress (seed ≠ live).
        self._range_bars_enabled = range_bars_enabled
        self._last_range_h: float = 0.0
        # Optional callback: timesfm_seed_fn(symbol, closes) is called after
        # AMT candle seeding so the TimesFM price buffer is pre-warmed.
        self._timesfm_seed_fn: Any = None

        # AMT state
        self._amt_analyzer = AMTAnalyzer()
        self._amt_candles: list[FloatOHLC] = []
        self._amt_lock = threading.Lock()
        self._amt_incremental: IncrementalVolumeProfile | None = None
        self._footprint = TickFootprintAccumulator()
        self._kernel = SessionKernel(
            self._amt_analyzer, footprint_accumulator=self._footprint,
        )
        
        # Session tracking
        self._session_date: str | None = None
        self._prior = session_levels.load_levels(symbol)
        self._npoc = NPOCTracker(storage_port=session_levels)
        self._npoc.load_from_storage(self._underlying())
        
        # State for engine integration
        self._last_snapshot: AnalysisSnapshot | None = None
        self._last_amt_dto: dict | None = None
        self._last_underlying_close: float = 0.0
        self._warm_bars: int = 0
        # Seed status: NOT_STARTED → SEEDING → READY | DEGRADED_RATE_LIMIT | DEGRADED_EMPTY | FAILED
        from quant.execution.seed_scheduler import SeedStatus
        self._seed_status: SeedStatus = SeedStatus.NOT_STARTED
        self._gex: object | None = None
        self._amt_fail_logged: bool = False

    def set_gex(self, gex: object | None) -> None:
        """Update GEX snapshot for this symbol and sync the latest DTO."""
        with self._amt_lock:
            self._gex = gex
            if self._last_amt_dto is not None and gex is not None:
                self._last_amt_dto["gex"] = {
                    "netGexCrores": getattr(gex, "net_gex_crores", 0.0),
                    "regime": getattr(gex, "regime", "NEUTRAL_GAMMA"),
                    "zeroFlipLevel": getattr(gex, "zero_flip_level", 0.0),
                    "callWallStrike": getattr(gex, "call_wall_strike", 0.0),
                    "putWallStrike": getattr(gex, "put_wall_strike", 0.0),
                    "gammaPinStrike": getattr(gex, "gamma_pin_strike", 0.0),
                    "strikeGex": [
                        {
                            "strike": s.strike,
                            "callGex": s.call_gex,
                            "putGex": s.put_gex,
                            "netGex": s.net_gex,
                        }
                        for s in getattr(gex, "strike_gex", ())
                    ],
                }

    def _underlying(self) -> str:
        return self._underlying_fn()

    def _scrub_seed_side_effects(self) -> None:
        """Seed bars must not leave drive / hard-absorption / Triple-A state.

        ``analyze`` is shared with the live path, so the one-shot seed call
        can advance those machines; reset them immediately after seed so a
        seed-only history never presents as live evidence (plan T8).
        """
        try:
            self._amt_analyzer._drive_tracker.reset()
        except Exception:
            logger.debug("seed drive-tracker reset failed", exc_info=True)
        try:
            self._amt_analyzer._triple_a.reset()
        except Exception:
            logger.debug("seed triple-a reset failed", exc_info=True)
        det = getattr(self._amt_analyzer, "_absorption_detector", None)
        clear = getattr(det, "_clear_pending", None)
        if callable(clear):
            try:
                clear()
            except Exception:
                logger.debug("seed absorption clear failed", exc_info=True)

    @staticmethod
    def _scrub_seed_result(result):
        """Zero drive / hard-abs / Triple-A fields on a seed ``AMTResult``."""
        from dataclasses import replace

        agg = dict(getattr(result, "aggression_components", None) or {})
        agg["absorption_detected"] = False
        return replace(
            result,
            drive_number=0,
            drive_entry_valid=False,
            absorption_side="",
            absorption_cluster_high=0.0,
            absorption_cluster_low=0.0,
            absorption_range_ratio=0.0,
            absorption_vol_ratio=0.0,
            triple_a_phase="WAITING",
            triple_a_signal="",
            aggression_components=agg,
        )

    @property
    def _cvd_source(self) -> str:
        from quant.contracts.instrument_registry import is_option_contract, is_futures_contract
        if is_option_contract(self.symbol):
            return "option"
        if is_futures_contract(self.symbol) or self.symbol in (
            "CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM",
            "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"
        ):
            return "underlying"
        return ""

    def on_tick(self, tick, forming_bar=None) -> None:
        """Feed live tick to the footprint accumulator."""
        price = getattr(tick, "price", 0.0)
        vol = getattr(tick, "volume", 0.0)
        best_bid = 0.0
        best_ask = 0.0
        depth = getattr(tick, "depth", None)
        if isinstance(depth, dict):
            bids = depth.get("bids", [])
            asks = depth.get("asks", [])
            if bids and isinstance(bids[0], dict):
                best_bid = float(bids[0].get("price", 0.0))
            if asks and isinstance(asks[0], dict):
                best_ask = float(asks[0].get("price", 0.0))
        candle_time = getattr(forming_bar, "time", "") if forming_bar else ""
        if price > 0 and vol > 0 and candle_time:
            self._footprint.on_tick(
                ltp=float(price),
                ltq=int(vol),
                best_bid=best_bid,
                best_ask=best_ask,
                candle_time=str(candle_time),
            )

    def seed(self) -> None:
        """Best-effort: seed the AMT candle ring from REST history.

        Synchronous so spawn cannot start live bars before today's session
        profile exists. Uses the shared HistorySeedScheduler when available
        to respect broker rate limits (DH-3001).
        """
        if self._history_source is None:
            return

        from quant.execution.seed_scheduler import SeedStatus

        self._seed_status = SeedStatus.SEEDING
        seed_interval = self._seed_interval_str()
        cache_key = (self.symbol, seed_interval)
        cached = _SEED_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < SEED_CACHE_TTL_SECONDS:
            logger.info("AMT history seed: reusing cached history for %s (%d candles)", self.symbol, len(cached[1]))
            candles = list(cached[1])
        elif self._seed_scheduler is not None:
            # Shared scheduler path: rate-limited, cached, deduplicated
            try:
                result = self._seed_scheduler.fetch(self.symbol, seed_interval, 500)
                if result is not None:
                    candles = list(result)
                    if candles:
                        _SEED_CACHE[cache_key] = (time.monotonic(), list(candles))
                        self._seed_status = SeedStatus.READY
                    else:
                        self._seed_status = SeedStatus.DEGRADED_EMPTY
                else:
                    self._seed_status = SeedStatus.DEGRADED_RATE_LIMIT
                    candles = []
            except Exception as exc:
                logger.warning("AMT history seed failed for %s: %s", self.symbol, exc)
                self._seed_status = SeedStatus.FAILED
                candles = []
        else:
            # Legacy path: no scheduler (tests/replay)
            _reserve_seed_slot()
            candles: list = []
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
                    _SEED_CACHE[cache_key] = (time.monotonic(), list(candles))
                    self._seed_status = SeedStatus.READY
                    break
                if not awaitable:
                    self._seed_status = SeedStatus.DEGRADED_EMPTY
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
            if not candles and self._seed_status == SeedStatus.SEEDING:
                self._seed_status = SeedStatus.FAILED
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
                        prev_res = self._amt_analyzer.analyze(
                            prev_candles,
                            incremental_profile=prev_inc,
                        )
                        # Prior-session cold start is also seed-only: strip
                        # drive / hard-abs / Triple-A before levels are read.
                        prev_res = self._scrub_seed_result(prev_res)
                        self._scrub_seed_side_effects()
                        if prev_res.poc > 0:
                            self._prior = {
                                "poc": float(prev_res.poc),
                                "vah": float(prev_res.value_area_high),
                                "val": float(prev_res.value_area_low),
                                # parity with rollover/save_levels: seed close so
                                # first analyze classifies gaps vs settlement.
                                "close": float(prev_candles[-1].close),
                            }
                            self._last_underlying_close = float(prev_candles[-1].close)
                            self._session_levels.save_levels(
                                self.symbol, last_date,
                                float(prev_res.poc),
                                float(prev_res.value_area_high),
                                float(prev_res.value_area_low),
                                close=self._last_underlying_close,
                            )
                            self._npoc.add_session_poc(self._underlying(), last_date, float(prev_res.poc))
                            logger.info(
                                "Cold-start seeded prior session levels for %s (%s): POC=%.2f VAH=%.2f VAL=%.2f",
                                self.symbol, last_date, prev_res.poc, prev_res.value_area_high, prev_res.value_area_low
                            )
                    except Exception:
                        logger.warning("%s: cold-start seed of prior session levels failed", self.symbol, exc_info=True)

        scoped = session_scope(candles)
        with self._amt_lock:
            if self._amt_candles:
                return  # live bars already flowing — keep them
            ohlcs = [to_float_ohlc(c) for c in scoped]
            if self._range_bars_enabled and ohlcs:
                # Plan T8: range mode seeds SYNTH range bars (span ≤ H) into
                # the profile ring; they stay non-live for warmup/drive.
                from quant.amt.range_seed import h_range_from_ohlcs, synth_range_bars
                h = h_range_from_ohlcs(ohlcs, self._tick_size)
                self._last_range_h = h
                try:
                    synth = synth_range_bars(ohlcs, h)
                except ValueError:
                    synth = []
                if synth:
                    ohlcs = [
                        FloatOHLC(
                            time=b.time, open=b.open, high=b.high, low=b.low,
                            close=b.close, volume=b.volume, vwap=b.vwap,
                            taker_buy_volume=b.buy_volume, delta=b.delta,
                        )
                        for b in synth
                    ]
            self._amt_candles = ohlcs
            inc = IncrementalVolumeProfile()
            for c in ohlcs:
                inc.update(c)
            self._amt_incremental = inc
            # ponytail: warm_bars = candles fully processed by every tracker.
            self._warm_bars = 0
            if ohlcs:
                # Replay the complete seed through each idempotent session tracker.
                self._amt_analyzer.warmup_candles(ohlcs)
                self._kernel.warm_bars = len(ohlcs)
                self._warm_bars = self._kernel.warm_bars
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
                        prior_close=self._prior.get("close", 0.0),
                        npoc_tracker=self._npoc,
                        option_tick=last_ohlc,
                        footprint_accumulator=self._footprint,
                        gex=self._gex,
                        cvd_source=self._cvd_source,
                    )
                    # Seed-only: scrub evidence + reset trackers so seed bars
                    # never present as drive / hard-abs / Triple-A (plan T8).
                    # Self-contained in amt_engine (does not require analyzer
                    # is_seed kwarg — analyzer may be reverted externally).
                    result = self._scrub_seed_result(result)
                    self._scrub_seed_side_effects()
                    iso_time = _epoch_to_iso(last_ohlc.time)
                    snap = analysis_snapshot_from_result(result, asof_time=iso_time)
                    dto = amt_result_to_dto(result)
                    dto["time"] = iso_time
                    self._last_snapshot = snap
                    self._last_amt_dto = dto
                    self._last_underlying_close = float(last_ohlc.close)
                except Exception:
                    logger.warning("Initial AMT analyze after seed failed for %s", self.symbol, exc_info=True)
        logger.info(
            "AMT seeded %d session candles for %s (initial DTO: %s)", len(scoped), self.symbol, bool(self._last_amt_dto)
        )
        # Session candles remain available for H_range / range-seed synth (T8).

        # Push historical closes into TimesFM price buffer so model starts warm.
        if self._timesfm_seed_fn is not None and ohlcs:
            try:
                closes = [float(c.close) for c in ohlcs if c.close and c.close > 0]
                if closes:
                    self._timesfm_seed_fn(self.symbol, closes)
            except Exception as _e:
                logger.debug("TimesFM history pre-seed skipped for %s: %s", self.symbol, _e)

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
        # is complete. Persist its levels, reset rolling state, and reload prior levels.
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
                    close=self._last_underlying_close,
                )
                # Options engines must not write underlying NPOC (audit §5.5).
                from quant.contracts.instrument_registry import is_option_contract
                if not is_option_contract(self.symbol):
                    self._npoc.add_session_poc(
                        self._underlying(), self._session_date, prev_poc
                    )
            self._prior = self._session_levels.load_levels(self.symbol)
            # Reset candle ring, incremental profile, and ALL session trackers
            with self._amt_lock:
                self._amt_candles = []
                self._amt_incremental = IncrementalVolumeProfile()
                self._last_snapshot = None
                self._last_amt_dto = None
            self._kernel.reset()
            self._warm_bars = 0
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
                if self._amt_candles and self._amt_candles[-1].time == ohlc.time:
                    # Duplicate timestamp re-feed: update all trackers, not just profile.
                    self._amt_candles[-1] = ohlc
                    inc = IncrementalVolumeProfile()
                    for c in self._amt_candles:
                        inc.update(c)
                    self._amt_incremental = inc
                    self._kernel.allow_duplicate_refeed()
                else:
                    self._amt_candles.append(ohlc)
                    oldest: FloatOHLC | None = None
                    if len(self._amt_candles) > 1000:
                        oldest = self._amt_candles[0]
                        self._amt_candles = self._amt_candles[-1000:]
                    if self._amt_incremental is not None:
                        self._amt_incremental.update(ohlc, oldest)
                    self._kernel.record_warm_bar()
                    self._warm_bars = self._kernel.warm_bars
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
                prior_close=self._prior.get("close", 0.0),
                npoc_tracker=self._npoc,
                option_tick=ohlc,
                footprint_accumulator=self._footprint,
                gex=self._gex,
                cvd_source=self._cvd_source,
            )
        except Exception:
            if not self._amt_fail_logged:
                logger.warning(
                    "AMT analyze failed for %s — keeping last good DTO",
                    self.symbol, exc_info=True,
                )
                self._amt_fail_logged = True
            return self._last_amt_dto or {}
        snap = analysis_snapshot_from_result(result, asof_time=iso_now)
        dto = amt_result_to_dto(result)
        dto["time"] = iso_now
        with self._amt_lock:
            self._last_snapshot = snap
            self._last_amt_dto = dto
            self._last_underlying_close = float(ohlc.close)
        return dto

    @property
    def warm_bars(self) -> int:
        return self._warm_bars

    @property
    def last_range_h(self) -> float:
        """H_range derived during a range-mode seed (0.0 when never set)."""
        return self._last_range_h

    @property
    def session_candles(self) -> list:
        """Seed/live session OHLC snapshot (H_range + range-seed synth input)."""
        with self._amt_lock:
            return list(self._amt_candles)

    def export_kernel_state(self) -> dict:
        """Order-flow warmth snapshot for mid-session restart."""
        return self._kernel.export_state()

    def import_kernel_state(self, data: dict | None) -> None:
        self._kernel.import_state(data)
        self._warm_bars = self._kernel.warm_bars

    @property
    def last_amt_dto(self) -> dict | None:
        with self._amt_lock:
            return self._last_amt_dto

    @property
    def last_snapshot(self) -> AnalysisSnapshot | None:
        with self._amt_lock:
            return self._last_snapshot

    @property
    def last_bar(self) -> Bar | None:
        with self._amt_lock:
            if not self._amt_candles:
                return None
            return to_bar(self._amt_candles[-1])

    def set_prior_profile(
        self,
        poc: float,
        vah: float,
        val: float,
        close: float = 0.0,
    ) -> None:
        """Explicitly set prior session profile levels (e.g. from storage/prior run)."""
        self._prior = {
            "poc": float(poc or 0.0),
            "vah": float(vah or 0.0),
            "val": float(val or 0.0),
            "close": float(close or 0.0),
        }
        if close > 0:
            self._last_underlying_close = float(close)

    def persist_session_levels(self) -> None:
        """Write current session POC/VA/close — call on EOD / engine stop.

        Ensures prior levels survive restart-between-sessions (audit §5.4).
        """
        prev = self._last_amt_dto or {}
        prev_poc = float(prev.get("poc") or 0.0)
        date = self._session_date
        if prev_poc <= 0 or not date:
            return
        self._session_levels.save_levels(
            self.symbol,
            date,
            prev_poc,
            float(prev.get("valueAreaHigh") or 0.0),
            float(prev.get("valueAreaLow") or 0.0),
            close=self._last_underlying_close,
        )
        from quant.contracts.instrument_registry import is_option_contract
        if not is_option_contract(self.symbol):
            self._npoc.add_session_poc(self._underlying(), date, prev_poc)
