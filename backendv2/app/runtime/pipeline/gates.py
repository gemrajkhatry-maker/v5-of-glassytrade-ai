"""Gate evaluation stage."""

from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Callable

from app.domain.amt.service.aggression_scorer import AggressionScorer
from app.domain.amt.service.drive_decay import DriveDecay
from app.domain.amt.service.entry_gates import calculate_position_size, run_entry_gates
from app.domain.amt.service.oi_analyzer import OIAnalyzer
from app.domain.amt.service.regime_detector import RegimeDetector
from app.domain.amt.service.rr_validator import RRValidator
from app.domain.amt.service.trade_thesis import build_trade_thesis, validate_trade_thesis
from app.shared.timezones import IST
from app.domain.trading.model.enums import SetupType
from app.domain.trading.model.value_objects import AMTResult, OHLC
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import Signal, GateResult, GateResultType

logger = logging.getLogger(__name__)


class _SymbolState:
    """Per-symbol gate state."""

    def __init__(self) -> None:
        self.scorer = AggressionScorer()
        self.regime = RegimeDetector()
        self.drive_decay = DriveDecay()
        self.oi_analyzer = OIAnalyzer()
        self.rr_validator = RRValidator()
        self._candles: list[OHLC] = []
        self._amt_result: SimpleNamespace | None = None
        self._orderflow: SimpleNamespace | None = None


class GateEvaluation:
    """Gate checks and confidence filtering for signals."""

    def __init__(self, equity_fn: Callable[[str], float] | None = None):
        self._metrics = StageMetrics(stage_name="GateEvaluation")
        self._equity_fn = equity_fn
        self._states: dict[str, _SymbolState] = {}
        self._seen = set[str]()

    def _get_state(self, symbol: str) -> _SymbolState:
        if symbol not in self._states:
            self._states[symbol] = _SymbolState()
        return self._states[symbol]

    def ingest_market_structure(self, symbol: str, market_result) -> None:
        """Ingest market structure result (contains AMT data) for squeeze detection.

        Wiring: SessionRuntime calls this when market structure is updated.
        """
        state = self._get_state(symbol)
        if market_result and hasattr(market_result, 'value_area_low'):
            state._amt_result = market_result

    def ingest_orderflow(self, symbol: str, orderflow_data) -> None:
        """Ingest orderflow data for gate evaluation.

        Also updates RegimeDetector absorption state when absorption is detected.
        Wiring: SessionRuntime calls this when orderflow metrics are available.
        """
        state = self._get_state(symbol)
        state._orderflow = orderflow_data
        if orderflow_data and getattr(orderflow_data, 'absorption_detected', False):
            absorption_side = getattr(orderflow_data, 'absorption_side', 'NONE')
            if absorption_side in ('BUY', 'SELL'):
                state.regime.set_absorption(detected=True, side=absorption_side)

    def ingest_candle(self, symbol: str, candle: OHLC) -> None:
        """Ingest a candle for squeeze detection.

        Stores up to 100 recent candles per symbol.
        Wiring: SessionRuntime calls this when new candles are available.
        """
        state = self._get_state(symbol)
        state._candles.append(candle)
        if len(state._candles) > 100:
            state._candles = state._candles[-100:]

    @staticmethod
    def _to_dt(timestamp: float) -> datetime:
        if timestamp > 1_000_000_000_000:
            return datetime.fromtimestamp(timestamp / 1_000_000_000, tz=IST)
        return datetime.fromtimestamp(timestamp, tz=IST)

    @staticmethod
    def _compute_session_phase(timestamp: float) -> int:
        """Compute NSE session phase (1-5) from signal timestamp.

        Phase 1: Opening (09:15-09:30)
        Phase 2: AAA Window (09:30-11:30)
        Phase 3: Midday (11:30-14:00)
        Phase 4: Power Hour (14:00-15:15)
        Phase 5: Close Protection (15:15-15:30)
        """
        dt = GateEvaluation._to_dt(timestamp)
        hour, minute = dt.hour, dt.minute
        t = hour * 60 + minute  # minutes since midnight
        p1_end = 9 * 60 + 30    # 09:30
        p2_end = 11 * 60 + 30   # 11:30
        p3_end = 14 * 60        # 14:00
        p4_end = 15 * 60 + 15   # 15:15
        p5_end = 15 * 60 + 30   # 15:30
        if t < p1_end:
            return 1
        if t < p2_end:
            return 2
        if t < p3_end:
            return 3
        if t < p4_end:
            return 4
        if t < p5_end:
            return 5
        return 5  # After hours, treat as phase 5

    @staticmethod
    def _reject_result(
        signal: Signal,
        reason: str,
        score: str | float | int | None = None,
        extra: str = "",
        gate_key: str | None = None,
        seen: set[str] | None = None,
    ) -> list[GateResult]:
        if seen is not None and gate_key:
            seen.add(gate_key)
        return [
            GateResult(
                symbol=signal.symbol,
                timestamp=signal.timestamp,
                signal=signal,
                result=GateResultType.REJECTED,
                rejection_reason=f"{reason}{': ' + str(extra) if extra else ''}",
                aggression_score=float(score) if score is not None else 0.0,
                aggression_confidence="LOW",
                persistence_met=signal.confidence >= 0.5,
                session_phase_ok=False,
                playbook_ok=False,
                llm_overseer_ok=True,
                gate_results=(("entry_gate", reason),),
            )
        ]

    @staticmethod
    def _default_amt_result(signal: Signal) -> AMTResult:
        return AMTResult(
            market_state="IMBALANCED",
            poc=signal.entry,
            value_area_high=max(signal.tp, signal.entry, signal.sl),
            value_area_low=min(signal.tp, signal.entry, signal.sl),
            aggression=signal.confidence * 4.0,
            prior_poc=signal.entry,
            prior_vah=signal.entry,
            prior_val=min(signal.tp, signal.sl, signal.entry),
            setup="pipeline",
            drive_number=1,
            profile_shape="D",
            ofi=signal.confidence * 2.0,
        )

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def process(self, signal: Signal) -> list[GateResult]:
        try:
            if signal.type == "NO_TRADE":
                return []

            gate_key = f"{signal.symbol}:{signal.timestamp}:{signal.type}:{signal.entry}"
            state = self._get_state(signal.symbol)

            gate_passed, gate_reason, gate_detail, soft_passed, soft_total = run_entry_gates(
                data=[{"price": signal.entry, "timestamp": signal.timestamp}] * 45,
                amt_result=SimpleNamespace(
                    point_of_control=signal.entry,
                    value_area_high=signal.entry,
                    value_area_low=signal.entry,
                    setup=signal.reason,
                ),
                tick=SimpleNamespace(close=signal.entry),
                aggression_score=signal.confidence * 4.0,
                r_r_ratio=signal.rr,
                position_size_ok=calculate_position_size(
                    equity=self._equity_fn(signal.symbol) if self._equity_fn else 1_000_000.0,
                    entry_price=signal.entry,
                    stop_loss=signal.sl,
                    point_value=10.0,
                    risk_pct=0.01,
                )[0]
                > 0,
            )
            if not gate_passed:
                return self._reject_result(
                    signal=signal,
                    reason=f"{gate_reason}: {gate_detail}",
                    score=signal.confidence * 2.5,
                    extra=f"soft: {soft_passed}/{soft_total}",
                    gate_key=gate_key,
                    seen=self._seen,
                )

            # 1. Regime-based re-entry block
            session_phase = self._compute_session_phase(signal.timestamp)
            squeeze_active = (
                len(state._candles) >= 20
                and state._amt_result is not None
                and state.regime.detect_squeeze(state._candles, state._amt_result) is not None
            )
            if state.regime.is_re_entry_blocked(
                level=float(signal.entry),
                direction=str(signal.type),
                session_phase=session_phase,
                squeeze_active=squeeze_active,
                atr=abs(signal.tp - signal.sl),
            ):
                return self._reject_result(
                    signal=signal,
                    reason="Re-entry blocked by RegimeDetector",
                    score=signal.confidence * 2.5,
                    gate_key=gate_key,
                    seen=self._seen,
                )

            # 2. Drive decay requirement
            if state.drive_decay._drive_1_records:
                decay = state.drive_decay.validate_drive_2(
                    level=float(signal.entry),
                    current_price=float(signal.entry),
                    current_time=self._to_dt(signal.timestamp),
                )
                if not decay.valid:
                    return self._reject_result(
                        signal=signal,
                        reason=f"Drive decay blocked: {decay.reason}",
                        score=signal.confidence * 2.5,
                        gate_key=gate_key,
                        seen=self._seen,
                    )

            # 3. Trade thesis contract
            tick = OHLC.create(
                time=str(signal.timestamp),
                open=signal.entry,
                high=signal.entry,
                low=signal.entry,
                close=signal.entry,
                volume=1.0,
            )
            thesis = build_trade_thesis(
                tick=tick,
                amt_result=self._default_amt_result(signal),
                setup_type=SetupType.TREND_MODEL if signal.type == "LONG" else SetupType.MEAN_REVERSION,
                session_context="ACTIVE",
                invalidation_level=float(signal.sl),
            )
            valid_thesis, thesis_reason = validate_trade_thesis(thesis)
            if not valid_thesis:
                return self._reject_result(
                    signal=signal,
                    reason=f"Trade thesis failed: {thesis_reason}",
                    score=signal.confidence * 2.5,
                    gate_key=gate_key,
                    seen=self._seen,
                )

            # 4. OI pressure wall reduces confidence
            strike = round(signal.entry / 100.0) * 100.0
            oi_result = state.oi_analyzer.check_oi_pressure(
                symbol=signal.symbol,
                strike=strike,
                option_type="CE" if signal.type == "LONG" else "PE",
            )
            signal_confidence = min(1.0, signal.confidence * oi_result.confidence_multiplier)

            # 5. Live R:R validation
            if (
                signal.tp > 0
                and signal.entry != signal.sl
            ):
                expected_rr = abs(signal.tp - signal.entry) / abs(signal.entry - signal.sl)
                rr_value = signal.rr if expected_rr == 0 else max(signal.rr, 0.0)
                rr_take_profit = (
                    signal.tp
                    if rr_value > 0 and abs(expected_rr - rr_value) < 0.05
                    else (
                        signal.entry + (signal.entry - signal.sl) * rr_value
                        if signal.type == "LONG"
                        else signal.entry - (signal.sl - signal.entry) * rr_value
                    )
                )
            else:
                rr_take_profit = signal.tp
                rr_value = signal.rr
            rr_check = state.rr_validator.validate_live_ask(
                entry_ltp=signal.entry,
                stop_loss=signal.sl,
                take_profit=rr_take_profit,
                live_ask=signal.entry,
                is_long=signal.type == "LONG",
            )
            if rr_value <= 0:
                rr_value = rr_check.rr_ratio
            if not rr_check.valid:
                return self._reject_result(
                    signal=signal,
                    reason=f"Live R:R failed: {rr_check.reason}",
                    score=signal_confidence * 2.5,
                    gate_key=gate_key,
                    seen=self._seen,
                )

            score = state.scorer.score(
                footprint_ratio=0.4,
                cvd_confirms=signal.confidence >= 0.5,
                big_trade_cluster=False,
                absorption=(signal.type in ("LONG", "SHORT")),
                ofi=signal.ofi,
                lvn_near_level=True,
                volume_bubble=signal.confidence >= 0.6,
                side=signal.type,
            )

            if signal_confidence < 0.5:
                result = GateResultType.REJECTED
            elif score.confidence in {"LOW", "MEDIUM"} and signal.rr < 1.2:
                result = GateResultType.REJECTED
            else:
                result = GateResultType.APPROVED

            reason = ""
            if result is not GateResultType.APPROVED:
                reason = "Confidence or R:R rejected"
            gate = GateResult(
                symbol=signal.symbol,
                timestamp=signal.timestamp,
                signal=signal,
                result=result,
                rejection_reason=reason,
                aggression_score=score.score,
                aggression_confidence=score.confidence,
                persistence_met=True,
                session_phase_ok=True,
                playbook_ok=result is GateResultType.APPROVED,
                llm_overseer_ok=True,
                gate_results=(
                    ("confidence", signal_confidence),
                    ("rr", signal.rr),
                    ("oi_pressure", oi_result.pressure.value),
                ),
            )
            self._seen.add(gate_key)
            self._metrics.record(0)
            return [gate]
        except Exception:
            self._metrics.record_error()
            logger.exception("Gate evaluation failed")
            return []

    def warmup(self) -> None:
        self._states = {}
        self._seen = set()
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def snapshot(self) -> dict[str, list[str]]:
        return {"seen": sorted(self._seen)}

    def restore(self, payload: dict[str, list[str]]) -> None:
        self._seen = set()
        if isinstance(payload, dict):
            seen = payload.get("seen")
            if isinstance(seen, list):
                self._seen = set(str(item) for item in seen)
