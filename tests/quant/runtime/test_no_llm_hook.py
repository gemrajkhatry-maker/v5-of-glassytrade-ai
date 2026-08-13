# tests/quant/runtime/test_no_llm_hook.py
"""QuantEngine has no LLM wiring: the engine never schedules inference,
never folds back model events, and its decision trace is fully
deterministic from ticks alone."""

from tests.helpers.synthetic import SyntheticGateway
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws
from tests.quant.runtime.test_runtime import _ticks


def _engine():
    return QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1)


def test_engine_has_no_llm_machinery():
    """The LLM layer was removed: no executor, no inference, no consensus
    gate, no advisory state should exist on the engine."""
    eng = _engine()
    for attr in (
        "_llm_executor", "_llm_history", "_llm_state_lock",
        "_llm_entry_temperature", "_llm_execution_enabled",
        "_last_llm_bar_index", "_inference", "_schedule_llm",
        "_llm_consensus_state",
    ):
        assert not hasattr(eng, attr), f"LLM machinery {attr} must not exist"


def test_amt_populated_without_inference():
    eng = _engine()
    eng.run()
    ws = view_state_to_ws(eng.projector.snapshot("SYM"))
    assert ws["amt"] is not None
    # Full AMTAnalysis contract — profile histogram, market state, VWAP bands.
    assert set(ws["amt"]) >= {
        "marketState", "poc", "valueAreaHigh", "valueAreaLow",
        "profile", "legProfile", "lvns", "hvns", "sessionVwap",
    }


def test_no_llm_events_in_trace():
    """The LLM event types are gone from the event catalog, so no trace can
    carry a fold-back, overseer, or agent-decision event."""
    import quant.events as events_mod
    for name in ("LLMAnalysisProduced", "OverseerProduced", "AgentDecisionProduced"):
        assert not hasattr(events_mod, name), f"{name} must be removed from quant.events"

    eng = _engine()
    trace = eng.run()
    from quant.events import DecisionProduced, SignalApproved, RiskUpdated
    allowed = (DecisionProduced, SignalApproved, RiskUpdated)
    for event in trace:
        assert not any(name in type(event).__name__ for name in
                       ("LLM", "Overseer", "AgentDecision")), \
            f"LLM-derived event {type(event).__name__} must not appear"


def test_decision_emitted_deterministically():
    """A decision is produced from auction state alone (no model call)."""
    eng = _engine()
    trace = eng.run()
    from quant.events import DecisionProduced
    assert any(isinstance(e, DecisionProduced) for e in trace)


def test_engine_constructs_without_llm_kwargs():
    """The constructor no longer accepts inference/llm kwargs — calling with
    them must raise TypeError (signature is LLM-free)."""
    import pytest
    with pytest.raises(TypeError):
        QuantEngine(
            SyntheticGateway(_ticks()), "SYM",
            inference=object(), llm_history=[],
        )
