# tests/quant/runtime/test_llm_hook.py
"""QuantEngine LLM fold-back hook: async inference results are folded into
snapshots via lock-guarded emits without perturbing the deterministic
bar/decision trace."""

import json
import time

from tests.helpers.synthetic import SyntheticGateway
from quant.events import (
    AgentDecisionProduced,
    LLMAnalysisProduced,
    OverseerProduced,
)
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws
from tests.quant.runtime.test_runtime import _ticks


class _FakeInference:
    """ILLMInference-compatible stub returning a canned JSON decision."""

    def __init__(self, payload=None):
        self.payload = payload or {
            "direction": "LONG",
            "confidence": "High",
            "rationale": "test",
        }
        self.calls = []

    def is_ready(self) -> bool:
        return True

    def predict(self, instruction, input_text, temperature=None, max_tokens=None,
                prefill=None):
        self.calls.append({"instruction": instruction, "input_text": input_text})
        return json.dumps(self.payload)


def _engine(inference=None, llm_history=None):
    return QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1,
                       inference=inference, llm_history=llm_history)


def test_llm_analysis_folds_into_snapshot():
    inference = _FakeInference()
    eng = _engine(inference)
    eng.run()
    time.sleep(0.2)
    ws = view_state_to_ws(eng.projector.snapshot("SYM"))
    assert ws["genAIAnalysis"] is not None
    # Contradiction guard: the engine's last bar has no Triple-A signal,
    # so the LLM's "LONG" is overridden to FLAT with an audit trail.
    assert ws["genAIAnalysis"]["direction"] == "FLAT"
    assert ws["genAIAnalysis"]["guard_overridden"] is True
    assert ws["genAIAnalysis"]["_original_direction"] == "LONG"
    assert ws["genAIAnalysis"]["confidence"] == "High"
    assert ws["genAIAnalysis"]["rationale"] == "test"
    assert ws["overseerAction"] == ""
    assert ws["agentDecision"]["direction"] == "FLAT"
    # Frontend contract (types.ts) requires a NUMBER probability — the raw
    # "High"/"Medium"/"Low" string would produce NaN in the UI and a TypeError
    # in gate 3's comparison.
    assert isinstance(ws["agentDecision"]["probability"], (int, float))
    assert ws["agentDecision"]["probability"] == 0.8
    assert inference.calls, "inference should have been invoked"


class _DeferredLoadingInference(_FakeInference):
    """Simulates the MLX cold-start race: the shared model is mid-load, so
    ``is_ready()`` is False but ``is_loading()`` is True. The engine must still
    schedule the fold-back (predict() waits for the load) instead of silently
    dropping the bar's LLM analysis."""

    def is_ready(self) -> bool:
        return False

    def is_loading(self) -> bool:
        return True


def test_fold_back_scheduled_while_model_loading():
    inference = _DeferredLoadingInference()
    eng = _engine(inference)
    eng.run()
    time.sleep(0.2)
    assert inference.calls, (
        "fold-back must be scheduled even while the model is loading "
        "(cold-start race across engines sharing one MLX singleton)"
    )
    ws = view_state_to_ws(eng.projector.snapshot("SYM"))
    # Contradiction guard: FLAT because no deterministic edge at this bar.
    assert ws["agentDecision"]["direction"] == "FLAT"
    assert ws["agentDecision"]["probability"] == 0.8


def test_no_fold_back_when_llm_permanently_unavailable():
    class _NeverReady(_FakeInference):
        def is_ready(self) -> bool:
            return False

        def is_loading(self) -> bool:
            return False

    inference = _NeverReady()
    eng = _engine(inference)
    eng.run()
    time.sleep(0.2)
    assert inference.calls == [], (
        "no fold-back when the backend will never be ready "
        "(no model / load failed)"
    )


def test_llm_instruction_allows_short_and_includes_amt_context():
    """The entry prompt passed to the model must permit SHORT (the engine is
    SHORT-capable) and carry the AMT-derived evidence the banner shows — the
    old prompt was LONG/FLAT-only and omitted aggression/VWAP bias, so the
    advisory always said LONG even on a SELL setup.

    Prompt-shape alignment: the schema lives in the SYSTEM instruction
    (matching scripts/dataset_render.py), the AMT narrative in the USER
    message — previously the narrative was in the system role while training
    put it in the user role."""
    inference = _FakeInference()
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM 100 CALL",
                      interval_seconds=1, inference=inference)
    eng.run()
    time.sleep(0.2)
    assert inference.calls
    instruction = inference.calls[0]["instruction"]
    input_text = inference.calls[0]["input_text"]
    # Schema: SHORT is a legal answer for the SHORT-capable engine (system).
    assert '"LONG" | "SHORT" | "FLAT"' in instruction
    # AMT evidence reaches the model in the USER narrative: aggression + VWAP.
    assert "Aggression Score:" in input_text
    assert "VWAP:" in input_text
    # CALL/PUT option-mapping block is present (direction refers to the option).
    assert "CALL OPTION contract" in input_text
    assert "LONG = Buy Call (bullish bet on underlying)" in input_text


def test_llm_instruction_prefers_amt_dto_levels():
    """The prompt's POC/VAH/VAL/CVD must come from the AMT DTO — the numbers
    the dashboard banner shows — not the decision-path profile, so the model
    and the user see one source of truth. (Narrative lives in the USER
    message; the compact bar footer is DTO-priority too.)"""
    from quant.auction_state import AuctionState
    from quant.location import LocationState
    from quant.order_flow import OrderFlowState
    from quant.volume_profile import VolumeProfile
    from quant.vwap import VWAPState

    # Decision-path profile says POC=90/VAH=95/VAL=85; the AMT DTO (what the
    # banner shows) says POC=102/VAH=105/VAL=95 with cvdSlope=45.5.
    state = AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(
            levels=(), poc=90.0, vah=95.0, val=85.0, step=1.0, total_volume=100.0
        ),
        vwap=VWAPState(value=99.0, upper_1=101.0, lower_1=97.0,
                       upper_2=103.0, lower_2=95.0, std=2.0, deviation_sigmas=0.5),
        order_flow=OrderFlowState(delta=5.0, cvd=10.0, cvd_slope=2.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=0, ib_low=0, ib_complete=False,
                               zone="UNKNOWN", nearest_level=0, distance_to_level=0),
        triple_a_phase="WAITING", triple_a_signal=None,
    )
    dto = {
        "poc": 102.0, "valueAreaHigh": 105.0, "valueAreaLow": 95.0,
        "sessionVwap": 99.0, "aggression": 1.2, "cvdSlope": 45.5,
        "marketState": "BALANCED",
    }
    from quant.bars import Bar

    eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    bar = Bar(time="t", open=99.0, high=101.0, low=97.0, close=100.0,
              volume=50.0, delta=1.0)
    text = eng._llm_input(state, bar, dto, "SYM")
    # DTO values win over the decision-path profile.
    assert "POC=102" in text and "VAH=105" in text and "VAL=95" in text
    assert "POC=90" not in text
    # CVD slope comes from the DTO too (45.5 >= 3 → "Sustained buying"; the
    # decision path's 2.0 would render nothing).
    assert "Sustained buying" in text
    # VWAP bias line renders from sessionVwap.
    assert "above VWAP" in text


def test_llm_instruction_persisted_for_audit():
    """Every decision must carry the full instruction it was generated from
    so prompts can be audited after the fact (stored in the extra JSON by the
    DB sink — the compact input_text alone can't prove what the model saw)."""
    history = []
    inference = _FakeInference()
    eng = _engine(inference, llm_history=history)
    eng.run()
    time.sleep(0.2)
    assert history
    entry = history[-1]
    assert entry.get("instruction"), "full instruction must be persisted"
    # Schema lives in the system instruction; the AMT narrative + bar footer
    # in the persisted user message.
    assert '"LONG" | "SHORT" | "FLAT"' in entry["instruction"]
    assert "Aggression Score:" in entry["input_prompt"]
    assert entry.get("input_prompt") and "Bar " in entry["input_prompt"]


def test_llm_input_delta_matches_chart_body_ratio():
    """The compact input's delta must be the same body-ratio estimate the
    REST chart serves (estimate_tick_delta), not the live per-tick split —
    Dhan's WS has no traded buy/sell split, so the two would diverge and the
    model would reason from a different number than the user's chart."""
    from quant.auction_state import AuctionState
    from quant.bars import Bar
    from quant.contracts.market_data_utils import estimate_tick_delta
    from quant.location import LocationState
    from quant.order_flow import OrderFlowState
    from quant.volume_profile import VolumeProfile
    from quant.vwap import VWAPState

    state = AuctionState(
        time="t", close=108.0,
        volume_profile=VolumeProfile(
            levels=(), poc=90.0, vah=95.0, val=85.0, step=1.0, total_volume=500.0
        ),
        vwap=VWAPState(value=100.0, upper_1=102.0, lower_1=98.0,
                       upper_2=104.0, lower_2=96.0, std=2.0, deviation_sigmas=0.0),
        order_flow=OrderFlowState(delta=200.0, cvd=200.0, cvd_slope=10.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=0, ib_low=0, ib_complete=False,
                               zone="UNKNOWN", nearest_level=0, distance_to_level=0),
        triple_a_phase="WAITING", triple_a_signal=None,
    )
    bar = Bar(time="t", open=100.0, high=110.0, low=90.0, close=108.0,
              volume=500.0, delta=999.0)  # delta=999 would leak if unused
    eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    text = eng._llm_input(state, bar)
    expected = int(estimate_tick_delta(100.0, 110.0, 90.0, 108.0, 500.0))
    assert expected == 200
    assert f"V=500 delta={expected}" in text
    assert "delta=999" not in text
    assert "POC=90.00 VAH=95.00 VAL=85.00" in text


def test_llm_instruction_matches_training_system_shape():
    """The live system instruction must equal the training shape produced by
    scripts/dataset_render.py (``_DEFAULT_INSTRUCTION`` + entry JSON schema),
    so a retrain sees the exact prompt the app sends at runtime."""
    from quant.inference.generative_ai import _DEFAULT_INSTRUCTION

    eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    instruction = eng._llm_instruction(None, None, None)
    assert instruction.startswith(_DEFAULT_INSTRUCTION)
    assert '"LONG" | "SHORT" | "FLAT"' in instruction


def test_llm_consensus_state_stamped_after_foldback():
    """After a fold-back lands, the engine's LLM-consensus state exposes the
    advisory direction/confidence and marks it fresh for the current bar.
    The contradiction guard overrides the direction to FLAT when the engine
    has no Triple-A signal for that bar (Fabio: no edge -> flat)."""
    inference = _FakeInference()  # LONG / High
    eng = _engine(inference, llm_history=[])
    eng.run()
    time.sleep(0.2)
    direction, confidence, fresh = eng._llm_consensus_state()
    # The last bar's fold-back overridden by the guard (no deterministic edge).
    assert direction == "FLAT"
    assert confidence == "High"
    assert fresh is True


def test_llm_consensus_state_empty_before_any_foldback():
    """No history yet -> no direction, not fresh (gate 6 blocks when enabled)."""
    eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    direction, confidence, fresh = eng._llm_consensus_state()
    assert direction is None and confidence is None and fresh is False


def test_amt_populated_without_inference():
    eng = _engine(inference=None)
    eng.run()
    ws = view_state_to_ws(eng.projector.snapshot("SYM"))
    assert ws["amt"] is not None
    # Full AMTAnalysis contract — profile histogram, market state, VWAP bands.
    assert set(ws["amt"]) >= {
        "marketState", "poc", "valueAreaHigh", "valueAreaLow",
        "profile", "legProfile", "lvns", "hvns", "sessionVwap",
    }


def test_bar_decision_trace_identical_with_and_without_inference():
    eng_plain = _engine(inference=None)
    eng_llm = _engine(_FakeInference())
    trace_plain = eng_plain.run()
    trace_llm = eng_llm.run()
    time.sleep(0.2)

    def _deterministic(events):
        return [
            e for e in events
            if not isinstance(e, (LLMAnalysisProduced, OverseerProduced,
                                  AgentDecisionProduced))
        ]

    assert _deterministic(trace_plain) == _deterministic(trace_llm)


def test_llm_history_appends_and_caps_at_50():
    history = []
    eng = _engine(_FakeInference(), llm_history=history)
    eng.run()
    time.sleep(0.2)
    assert len(history) >= 1
    # Contradiction guard overrides the direction; audit trail preserved.
    assert history[-1]["direction"] == "FLAT"
    assert history[-1]["guard_overridden"] is True
    assert history[-1]["_original_direction"] == "LONG"
    # Enriched bar timestamps must be attached so the UI shows real times.
    for entry in history:
        assert "timestamp" in entry and isinstance(entry["timestamp"], int)
        assert entry.get("created_at"), "created_at must be stamped per entry"
        assert entry.get("input_prompt") is not None
        assert entry.get("raw_output") is not None


def test_normalize_probability_maps_confidence_words():
    from quant.runtime import QuantEngine
    assert QuantEngine._normalize_probability("High") == 0.8
    assert QuantEngine._normalize_probability("medium") == 0.6
    assert QuantEngine._normalize_probability("LOW") == 0.4


def test_normalize_probability_handles_numbers_and_percent():
    from quant.runtime import QuantEngine
    assert QuantEngine._normalize_probability(0.85) == 0.85
    assert QuantEngine._normalize_probability("0.72") == 0.72
    assert QuantEngine._normalize_probability(75) == 0.75   # percent form
    # Out-of-range values fail closed: >1 is treated as a percentage (1.5% ->
    # 0.015, below the 0.55 gate threshold), negatives clamp to 0.
    assert QuantEngine._normalize_probability(1.5) == 0.015
    assert QuantEngine._normalize_probability(-0.2) == 0.0


def test_normalize_probability_falls_back_safely():
    from quant.runtime import QuantEngine
    assert QuantEngine._normalize_probability(None) == 0.0
    assert QuantEngine._normalize_probability("garbage") == 0.0
    assert QuantEngine._normalize_probability(True) == 1.0
    assert QuantEngine._normalize_probability(False) == 0.0


def test_bar_time_stamp_helpers():
    """ISO (history path) and epoch-seconds (live path) bars both resolve to a
    real epoch-ms timestamp and an IST created_at string."""
    from quant.runtime import QuantEngine
    iso_ms = QuantEngine._bar_epoch_ms("2026-08-07T22:46:12+05:30")
    assert iso_ms == 1786122972000
    assert QuantEngine._ist_created_at("2026-08-07T22:46:12+05:30", iso_ms) == \
        "2026-08-07 22:46:12"
    epoch_ms = QuantEngine._bar_epoch_ms("1786122972")
    assert epoch_ms == 1786122972000
    assert QuantEngine._bar_epoch_ms("not-a-time") == 0
    assert QuantEngine._ist_created_at("not-a-time", 0) == "not-a-time"
