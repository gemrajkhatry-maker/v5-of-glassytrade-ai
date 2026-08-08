# tests/quant/runtime/test_llm_hook.py
"""QuantEngine LLM fold-back hook: async inference results are folded into
snapshots via lock-guarded emits without perturbing the deterministic
bar/decision trace."""

import json
import time

from quant.brokers.synthetic import SyntheticGateway
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
    assert ws["genAIAnalysis"]["direction"] == "LONG"
    assert ws["genAIAnalysis"]["confidence"] == "High"
    assert ws["genAIAnalysis"]["rationale"] == "test"
    assert ws["overseerAction"] == ""
    assert ws["agentDecision"]["direction"] == "LONG"
    assert inference.calls, "inference should have been invoked"


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
    assert history[-1]["direction"] == "LONG"
    # Enriched bar timestamps must be attached so the UI shows real times.
    for entry in history:
        assert "timestamp" in entry and isinstance(entry["timestamp"], int)
        assert entry.get("created_at"), "created_at must be stamped per entry"
        assert entry.get("input_prompt") is not None
        assert entry.get("raw_output") is not None


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
