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

    @staticmethod
    def _to_dt(timestamp: float) -> datetime:
        if timestamp > 1_000_000_000_000:
            return datetime.fromtimestamp(timestamp / 1_000_000_000, tz=IST)
        return datetime.fromtimestamp(timestamp, tz=IST)

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
            if state.regime.is_re_entry_blocked(
                level=float(signal.entry),
                direction=str(signal.type),
                session_phase=1,
                squeeze_active=False,
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
