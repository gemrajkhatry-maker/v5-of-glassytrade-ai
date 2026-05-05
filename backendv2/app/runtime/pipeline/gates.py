"""Gate evaluation stage."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from types import SimpleNamespace

from app.domain.amt.service.entry_gates import calculate_position_size, run_entry_gates
from app.domain.amt.service.aggression_scorer import AggressionScorer
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import Signal, GateResult, GateResultType

logger = logging.getLogger(__name__)


class GateEvaluation:
    """Gate checks and confidence filtering for signals."""

    def __init__(self):
        self._metrics = StageMetrics(stage_name="GateEvaluation")
        self._scorer = AggressionScorer()
        self._seen = set[str]()

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def process(self, signal: Signal) -> list[GateResult]:
        try:
            if signal.type == "NO_TRADE":
                return []

            gate_key = f"{signal.symbol}:{signal.timestamp}:{signal.type}:{signal.entry}"
            gate_passed, gate_reason, gate_detail, soft_passed, soft_total = run_entry_gates(
                data=[{"price": signal.entry, "timestamp": signal.timestamp}] * 10,
                amt_result=SimpleNamespace(
                    point_of_control=signal.entry,
                    value_area_high=max(signal.tp, signal.entry, signal.sl),
                    value_area_low=min(signal.tp, signal.entry, signal.sl),
                    setup=signal.reason,
                ),
                tick=SimpleNamespace(close=signal.entry),
                aggression_score=signal.confidence * 4.0,
                r_r_ratio=signal.rr,
                position_size_ok=calculate_position_size(
                    equity=1_000_000.0,
                    entry_price=signal.entry,
                    stop_loss=signal.sl,
                    point_value=10.0,
                )[0]
                > 0,
            )
            if not gate_passed:
                self._seen.add(gate_key)
                self._metrics.record(0)
                return [
                    GateResult(
                        symbol=signal.symbol,
                        timestamp=signal.timestamp,
                        signal=signal,
                        result=GateResultType.REJECTED,
                        rejection_reason=f"{gate_reason}: {gate_detail} (soft: {soft_passed}/{soft_total})",
                        aggression_score=signal.confidence * 2.5,
                        aggression_confidence="LOW" if gate_reason != "TRADE" else "MEDIUM",
                        persistence_met=signal.confidence >= 0.5,
                        session_phase_ok=soft_passed >= soft_total / 2,
                        playbook_ok=False,
                        llm_overseer_ok=True,
                        gate_results=(("entry_gate", gate_reason),),
                    )
                ]

            score = self._scorer.score(
                footprint_ratio=0.4,
                cvd_confirms=signal.confidence >= 0.5,
                big_trade_cluster=False,
                absorption=(signal.type in ("LONG", "SHORT")),
                ofi=0.25 if signal.type == "LONG" else -0.25,
                lvn_near_level=True,
                volume_bubble=signal.confidence >= 0.6,
                side=signal.type,
            )

            if signal.confidence < 0.5:
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
                gate_results=(("confidence", signal.confidence), ("rr", signal.rr)),
            )
            self._seen.add(gate_key)
            self._metrics.record(0)
            return [gate]
        except Exception:
            self._metrics.record_error()
            logger.exception("Gate evaluation failed")
            return []

    def warmup(self) -> None:
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
