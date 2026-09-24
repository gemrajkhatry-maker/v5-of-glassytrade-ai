"""DecisionService — the quant decision engine of record.

Runs GatePipeline (gates 1-4, the Fabio AMT playbook) then SignalBuilder;
when the gates pass but no Triple-A signal materializes, falls back to a
Value-Area fade (tier-2); returns NO_EDGE when nothing qualifies. The returned
QuantDecision is consumed by the backend wiring (quant signal → domain Signal
→ execution).
"""

from __future__ import annotations
import logging

from quant.contracts.constants import amt_stop_distance_limit
from quant.contracts.enums import MarketState

from dataclasses import dataclass, field

from quant.contracts.instrument_registry import is_option_contract
from quant.decision.context import DecisionContext
from quant.decision.model_router import allows, select_model
from quant.decision.pipeline import GatePipeline
from quant.decision.result import GateResult
from quant.decision.setup_labels import label_from_setup_key
from quant.decision.signal_builder import Signal, SignalBuilder, is_min_stop_met
from quant.decision.va_fade import detect_va_fade

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuantDecision:
    approved: bool
    signal: Signal | None
    reason: str          # "Triple-A" | "LVN_Sniper" | "VA_FADE" | "NO_EDGE" | "GATE_REJECTED" | "HALTED"
    phase: str           # "" (deprecated)
    gate_results: tuple[GateResult, ...]
    # Every failed gate as "NAME: reason" (GateResult.name) so UI/logs can
    # show the full rejection detail, not just one gate's reason.
    block_reasons: tuple[str, ...] = ()
    # Which Fabio playbook produced the approval — matches Signal.model_label.
    # "Triple-A" | "LVN_Sniper" | "VA_Fade" | "" (not approved)
    model_label: str = ""
    metadata: dict = field(default_factory=dict)


def _block_reasons(results) -> tuple[str, ...]:
    return tuple(f"{r.name}: {r.reason}" for r in results if not r.passed)


def _label_from_gate_results(results) -> str:
    """Identify which Gate 3 path fired. Empty setup_key → unlabeled (never Triple-A)."""
    for r in results:
        if r.gate == 3 and r.passed:
            key = str(getattr(r, "setup_key", "") or "")
            label = label_from_setup_key(key)
            if label:
                return label
            return ""
    return ""


class DecisionService:
    def __init__(self, min_rr: float = 0.0) -> None:
        self.min_rr = min_rr

    def evaluate(
        self, ctx: DecisionContext, *, allow_positioned: bool = False
    ) -> QuantDecision:
        if ctx.bar is None:
            return QuantDecision(False, None, "NO_EDGE", "", ())

        # Data-quality provenance is enforced by exactly ONE authority:
        # DecisionLoop._build_decision (capability-aware — live OMS requires
        # TICK_EXACT, paper marks PROXY_MODE). This service previously ran a
        # second, stricter provenance pre-gate here whose conviction-threshold
        # condition was constant-true; it force-blocked paper/replay and
        # masked the real gate (v7 prune N3). Gates 1-4 and the fallbacks
        # below are quality-agnostic by design.

        if ctx.risk_halted and not allow_positioned:
            return QuantDecision(
                approved=False,
                signal=None,
                reason="HALTED",
                phase="",
                gate_results=(),
                block_reasons=("Risk: session halted",),
                model_label="",
            )

        results = tuple(
            GatePipeline().evaluate(ctx, allow_positioned=allow_positioned)
        )
        active_model = select_model(ctx)
        gate3_key = next(
            (r.setup_key for r in results if r.gate == 3 and r.passed),
            "",
        )
        blocked = _block_reasons(results)
        if all(r.passed for r in results):
            if gate3_key and not allows(gate3_key, active_model):
                _log.info(
                    "Model router blocked %s (active model=%s, state=%s)",
                    gate3_key, active_model,
                    getattr(ctx.market_state, "value", ctx.market_state),
                )
                # fall through to the reversion fallback
            else:
                label = _label_from_gate_results(results)
                if not label:
                    return QuantDecision(
                        False, None, "GATE_REJECTED", "", results,
                        blocked + ("LABEL: unlabeled setup",),
                    )
                sig, drop_why = SignalBuilder().build_or_reason(ctx, results, model_label=label)
                if sig is not None:
                    return QuantDecision(
                        True, sig, label, "", results,
                        model_label=label,
                    )
                return QuantDecision(
                    False, None, "GATE_REJECTED", "", results,
                    blocked + (f"SIGNAL_BUILDER: {drop_why}",),
                )
        # If Gate 1 (session/spread) or Gate 2 (position/cooldown) failed, hard reject —
        # no trades or fades allowed. Identified by gate NUMBER, never list position:
        # positional indexing silently coupled fade eligibility to pipeline order
        # (audit D-GATE-05) — a reorder or inserted gate would let fades fire while
        # session-closed or position-open.
        hard_gate_failed = any(
            (r.gate in (1, 2)) and not r.passed for r in results
        )
        if hard_gate_failed:
            return QuantDecision(False, None, "GATE_REJECTED", "", results, blocked)

        # VA-fade fallback — the balance-returning reversion trade. It targets
        # the POC and requires price OUTSIDE the value area, so it never fires
        # in balanced rotation; a dead market refuses even the reversion.
        if ctx.market_state == MarketState.DEAD:
            return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
        # The reversion fallback only exists for the MEAN_REVERSION model; in a
        # trend (IMBALANCED) auction a fade would be counter-trend.
        if not allows("VA_FADE", active_model):
            return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
        fade = detect_va_fade(ctx)
        if fade:
            import logging
            logging.getLogger(__name__)
        if fade and (ctx.agent_direction in (fade.direction, None)) and fade.rr >= self.min_rr:
            # Option contracts are buy-only: never short naked options on VA-fade.
            # A bearish certificate needs a long put via OptionChainPort — without
            # one, refuse rather than invent a short or stay on a call.
            if is_option_contract(ctx.symbol) and fade.direction == "SHORT":
                return QuantDecision(
                    False, None, "NO_EDGE", "", tuple(results),
                    ("NEED_LONG_PUT: bearish certificate on option requires a put contract",),
                )
            if not is_min_stop_met(fade.entry, fade.sl):
                return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
            if fade.sl <= 0:
                return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
            tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
            fade_risk = abs(fade.entry - fade.sl)
            stop_limit = amt_stop_distance_limit(
                fade.entry,
                tick,
                is_option=is_option_contract(ctx.symbol),
            )
            if fade_risk > stop_limit:
                return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
            sig = Signal(
                type=fade.direction, reason="Value-Area fade", entry=fade.entry,
                sl=fade.sl, tp=fade.tp, rr=fade.rr, model_label="VA_Fade",
                symbol=ctx.symbol, timestamp=ctx.time_str,
            )
            return QuantDecision(
                True, sig, "VA_FADE", "", tuple(results),
                model_label="VA_Fade",
            )
        return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
