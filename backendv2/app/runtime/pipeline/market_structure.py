"""MarketStructureAnalysis — pipeline stage wrapping 11 AMT services."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.domain.amt.service.composite_profile import CompositeProfile
from app.domain.amt.service.market_structure_classifier import MarketStructureClassifier
from app.domain.amt.service.npoc_tracker import NPOCTracker
from app.domain.amt.service.opening_type_classifier import classify_opening_type
from app.domain.amt.service.order_book_analyzer import OrderBookAnalyzer
from app.domain.shared.port.storage import IStorage
from app.runtime.pipeline.events import Candle, CandleTimeframe, MarketStructureResult
from app.domain.amt.service.volume_profile import build_volume_profile
from app.domain.amt.service.lvn_detector import detect_lvn_hvn
from app.domain.amt.service.market_state_engine import detect_market_state
from app.domain.amt.service.break_detector import detect_break
from app.domain.amt.service.displacement_detector import detect_displacement
from app.domain.amt.service.initial_balance_engine import calculate_initial_balance, IBResult
from app.domain.amt.service.session_context import SessionContextEngine
from app.domain.amt.service.profile_classifier import classify_profile
from app.domain.amt.service.drive_tracker import DriveTracker
from app.domain.amt.service.mtf_analyzer import MultiTimeframeAMTAnalyzer
from app.domain.trading.model.value_objects import OHLC
from dataclasses import asdict

logger = logging.getLogger(__name__)


class _NullNPOCStorage:
    def save_npoc(self, underlying: str, date: str, poc: float) -> None:  # noqa: ARG002
        return None

    def mark_npoc_filled(self, underlying: str, date: str, filled_at: str) -> None:  # noqa: ARG002
        return None

    def get_active_npocs(self, underlying: str) -> list[dict]:
        return []


def _candle_to_bar(c: Candle) -> dict[str, Any]:
    return {
        "open": c.open, "high": c.high, "low": c.low, "close": c.close,
        "volume": c.volume, "timestamp": c.timestamp,
        "buyVolume": c.buy_volume, "sellVolume": c.sell_volume,
    }


class _SymbolState:
    def __init__(self, symbol: str, storage: IStorage | None = None):
        self.symbol = symbol
        self.bars: list[dict] = []
        self.prev_poc: Optional[float] = None
        self.drive_tracker = DriveTracker()
        self.mtf_analyzer = MultiTimeframeAMTAnalyzer()
        self.ctx_engine = SessionContextEngine()
        self.ms_classifier = MarketStructureClassifier()
        self.composite_profile = CompositeProfile()
        self.npoc_tracker = NPOCTracker(storage if storage is not None else _NullNPOCStorage())
        self.order_book = OrderBookAnalyzer()
        self.prior_profile: dict[str, float] = {}
        self.ohlc_history: list[OHLC] = []
        self.vwap_history: list[float] = []
        self.poc_history: list[float] = []
        self.last_result: Optional[MarketStructureResult] = None
        if storage is not None:
            try:
                self.npoc_tracker.load_from_storage(symbol)
                self.prior_profile = storage.get_previous_session_profile(symbol) or {}
            except Exception:
                logger.exception("Failed loading NPOC state for %s", symbol)


class MarketStructureAnalysis:
    def __init__(self, storage: IStorage | None = None):
        self._storage = storage
        self._states: dict[str, _SymbolState] = {}

    def _get_state(self, symbol: str) -> _SymbolState:
        if symbol not in self._states:
            self._states[symbol] = _SymbolState(symbol, storage=self._storage)
        return self._states[symbol]

    def process(self, candle: Candle) -> list[MarketStructureResult]:
        state = self._get_state(candle.symbol)
        bar = _candle_to_bar(candle)
        state.bars.append(bar)
        bars = state.bars

        # 1. Volume Profile
        bucket_size = 1.0
        vp = build_volume_profile(bars, bucket_size=bucket_size)
        vah = vp.vah if vp else 0
        val = vp.val if vp else 0
        poc = vp.poc if vp else 0
        levels = vp.levels if vp else []

        # 2. IB
        ib_result: Optional[IBResult] = calculate_initial_balance(bars) if len(bars) >= 2 else None

        # 3. Break detection
        break_result = detect_break(
            bars, {"vah": vah, "val": val, "poc": poc},
            ib_result.__dict__ if ib_result else None,
        )

        # 4. Displacement detection
        displ = detect_displacement(bars)

        # 5. LVN/HVN
        lvn_prices, hvn_prices = [], []
        if levels:
            lvns, hvns = detect_lvn_hvn(levels)
            if lvns:
                for lvn in lvns:
                    p = getattr(lvn, "price", lvn if isinstance(lvn, (int, float)) else 0)
                    lvn_prices.append(p)
            if hvns:
                for hvn in hvns:
                    p = getattr(hvn, "price", hvn if isinstance(hvn, (int, float)) else 0)
                    hvn_prices.append(p)

        # 6. Market State
        ms = detect_market_state(price=candle.close, vp_levels={"vah": vah, "val": val, "poc": poc})

        state.ohlc_history.append(
            OHLC.create(
                time=str(candle.timestamp),
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                vwap=getattr(candle, "vwap", 0.0),
            )
        )
        if len(state.ohlc_history) > 300:
            state.ohlc_history = state.ohlc_history[-300:]
        state.vwap_history.append(float(getattr(candle, "vwap", 0.0)))
        if len(state.vwap_history) > 300:
            state.vwap_history = state.vwap_history[-300:]
        state.poc_history.append(float(poc or 0.0))
        if len(state.poc_history) > 300:
            state.poc_history = state.poc_history[-300:]

        ms_classifier_result = state.ms_classifier.classify(
            state.ohlc_history,
            state.poc_history,
            state.vwap_history,
        )

        # 7. Session Context
        open_price = bars[0]["open"] if bars else candle.close
        prior_poc = state.prev_poc or float(state.prior_profile.get("poc", 0.0)) or (poc if poc else open_price)
        prior_vah = float(state.prior_profile.get("vah", 0.0))
        prior_val = float(state.prior_profile.get("val", 0.0))
        prior_close = float(state.prior_profile.get("close", open_price if not state.prev_poc else state.prev_poc))
        ctx = state.ctx_engine.analyze(
            open_price=open_price, prior_close=prior_close,
            prior_poc=prior_poc,
        )

        # 8. Profile Classification
        profile = classify_profile(levels, state.prev_poc, candle.close)
        state.prev_poc = poc or state.prev_poc

        # 8b. Composite profile + Opening type + NPOC + Order book imbalance
        composite = state.composite_profile.build([state.prior_profile] if state.prior_profile else [])
        opening = classify_opening_type(
            candles=bars,
            open_price=float(open_price),
            prior_vah=prior_vah,
            prior_val=prior_val,
            prior_poc=float(prior_poc),
            prior_close=prior_close,
        )
        state.npoc_tracker.check_and_fill(
            underlying=state.symbol,
            current_price=float(candle.close),
            tick_size=0.05,
        )
        npoc_payload = state.npoc_tracker.get_active_npocs(
            underlying=state.symbol,
            current_price=float(candle.close),
        )
        npoc_levels = tuple(
            float(item.price) for item in npoc_payload.all_active
        ) if npoc_payload.all_active else tuple()
        ob_state = state.order_book.analyze_depth20(
            symbol=state.symbol,
            timestamp=str(candle.timestamp),
            bids=[],
            asks=[],
        )

        # 9. Drive tracking
        drive = state.drive_tracker.update(
            price=candle.close, level=vah if vah > 0 else candle.high,
            direction="UP" if break_result and break_result.direction == "UP" else "DOWN",
        )

        # 10. MTF
        vp_profile = {"poc": poc, "vah": vah, "val": val}
        mtf = state.mtf_analyzer.analyze(vp_profile, vp_profile)

        # Build result
        result = MarketStructureResult(
            symbol=candle.symbol, timestamp=candle.timestamp,
            poc=poc, vah=vah, val=val,
            lvn_levels=tuple(lvn_prices),
            hvn_levels=tuple(hvn_prices),
            market_state=ms.state.value if ms else "BALANCED",
            market_zone=ms.zone.value if ms else "NEAR_POC",
            confidence=ms.confidence if ms else 0.5,
            is_extreme=ms.is_extreme if ms else False,
            composite_poc=float(getattr(composite, "weekly_poc", 0.0)),
            composite_vah=float(getattr(composite, "weekly_vah", 0.0)),
            composite_val=float(getattr(composite, "weekly_val", 0.0)),
            opening_type=getattr(opening, "opening_type", ""),
            npoc_levels=npoc_levels,
            ob_imbalance=float(getattr(ob_state, "obi", 0.0)),
            ms_classifier_state=ms_classifier_result.state if getattr(ms_classifier_result, "state", None) else "",
            break_detected=bool(break_result and break_result.direction),
            break_direction=break_result.direction if break_result else "",
            break_type=break_result.type if break_result else "",
            displacement_detected=bool(displ),
            displacement_direction=displ.direction if displ else "",
            profile_shape=profile.shape.value if profile else "D",
            poc_migration=profile.poc_migration.migration_type if profile else "NONE",
            drive_number=drive.drive_number if drive else 0,
            drive_exhausted=getattr(drive, 'is_exhausted', False),
            gap_size=ctx.gap_size.value if ctx else "NONE",
            opening_bias=ctx.opening_bias.value if ctx else "NEUTRAL",
            session_phase=ctx.session_phase.value if ctx else "MORNING",
            day_type=ctx.day_type if ctx else "",
            mtf_alignment=getattr(mtf, 'alignment', "") if mtf else "",
        )
        state.last_result = result
        return [result]

    def process_symbol(self, symbol: str, candle: Candle) -> list[MarketStructureResult]:
        return self.process(candle)

    def get_result(self, symbol: str) -> MarketStructureResult:
        state = self._states.get(symbol)
        if state and state.last_result:
            return state.last_result
        return MarketStructureResult(
            symbol=symbol,
            timestamp=0.0,
            poc=0.0,
            vah=0.0,
            val=0.0,
        )

    def warmup(self) -> None:
        self._states = {}

    def teardown(self) -> None:
        self._states = {}

    def reset(self) -> None:
        self._states = {}

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        state_payload: list[dict[str, object]] = []
        for symbol, state in self._states.items():
            state_payload.append({
                "symbol": symbol,
                "bars": list(state.bars),
                "prev_poc": state.prev_poc,
                "last_result": asdict(state.last_result) if state.last_result is not None else None,
            })
        return {"states": state_payload}

    def restore(self, payload: dict[str, object]) -> None:
        self._states = {}
        if not isinstance(payload, dict):
            return
        raw_states = payload.get("states")
        if not isinstance(raw_states, list):
            return

        for raw_state in raw_states:
            if not isinstance(raw_state, dict):
                continue
            symbol = str(raw_state.get("symbol", ""))
            if not symbol:
                continue
            bars_payload = raw_state.get("bars", [])
            if not isinstance(bars_payload, list):
                bars_payload = []

            bars: list[Candle] = []
            for raw_bar in bars_payload:
                if not isinstance(raw_bar, dict):
                    continue
                try:
                    tf_value = raw_bar.get("timeframe", "")
                    if isinstance(tf_value, CandleTimeframe):
                        tf = tf_value
                    else:
                        tf = CandleTimeframe(tf_value) if tf_value else CandleTimeframe.M1
                except ValueError:
                    tf = CandleTimeframe.M1
                try:
                    bars.append(Candle(
                        symbol=symbol,
                        timeframe=tf,
                        open=raw_bar.get("open", 0.0),
                        high=raw_bar.get("high", 0.0),
                        low=raw_bar.get("low", 0.0),
                        close=raw_bar.get("close", 0.0),
                        volume=raw_bar.get("volume", 0.0),
                        timestamp=raw_bar.get("timestamp", 0.0),
                        tick_count=raw_bar.get("tick_count", 0),
                        buy_volume=raw_bar.get("buy_volume", 0.0),
                        sell_volume=raw_bar.get("sell_volume", 0.0),
                        complete=raw_bar.get("complete", True),
                    ))
                except TypeError:
                    continue

            # Rebuild per-symbol analyzers from incoming bars.
            for candle in bars:
                self.process(candle)

            if "prev_poc" in raw_state and isinstance(raw_state.get("prev_poc"), (int, float)):
                state = self._states.get(symbol)
                if state is not None:
                    state.prev_poc = raw_state.get("prev_poc")

            last_result_payload = raw_state.get("last_result")
            if isinstance(last_result_payload, dict):
                state = self._states.get(symbol)
                if state is not None:
                    try:
                        state.last_result = MarketStructureResult(**last_result_payload)
                    except TypeError:
                        pass