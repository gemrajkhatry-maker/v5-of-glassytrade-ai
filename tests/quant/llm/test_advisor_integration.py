"""Integration tests for non-blocking LLM Advisor and ViewState streaming."""

import time
import pytest
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_runtime import _ticks
from quant.ws_adapter import view_state_to_ws
from quant.llm.advisor import LLMAdvisor
from quant.decision.context import DecisionContext
from quant.bars import Bar
from quant.contracts.enums import MarketState


def test_advisor_non_blocking_performance():
    """Verify that advisor.on_context() returns in microseconds without blocking."""
    emitted = []
    advisor = LLMAdvisor(emit_fn=lambda evt: emitted.append(evt))

    bar = Bar(time="2026-08-25T10:00:00+05:30", open=24200.0, high=24210.0, low=24190.0, close=24205.0, volume=1500.0, buy_volume=800.0, sell_volume=700.0, delta=100.0, vwap=24202.0)
    ctx = DecisionContext(
        symbol="NIFTY",
        bar=bar,
        market_state=MarketState.BALANCED,
        poc=24200.0,
        vah=24220.0,
        val=24180.0,
        session_phase="PRIMARY",
        cvd_slope=2.0,
    )

    t0 = time.perf_counter()
    advisor.on_context(ctx)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Must return immediately without blocking (< 5.0 ms queue push)
    assert elapsed_ms < 5.0

    # Wait for background worker to produce advisory
    for _ in range(20):
        if len(emitted) >= 1:
            break
        time.sleep(0.05)
    advisor.shutdown()
    assert len(emitted) >= 1
    assert emitted[0].symbol == "NIFTY"
    assert "rationale" in emitted[0].decision
    assert "action" in emitted[0].decision


def test_engine_emits_agent_decision_in_ws_snapshot(monkeypatch):
    """Verify engine runs deterministically and includes agentDecision in WS snapshot.

    F4: the engine no longer env-sniffs MLX_MODEL_PATH inside __init__; the
    live wiring injects the advisor explicitly via ``advisor=...``.
    """
    monkeypatch.setenv("LLM_ADVISOR_ENABLED", "1")
    from quant.wiring_advisor import build_live_advisor
    eng = QuantEngine(SyntheticGateway(_ticks()[:120]), "NIFTY", interval_seconds=1)
    eng._advisor = build_live_advisor(eng._emit)
    eng.run()

    from quant.state import project_state
    from dataclasses import replace
    vs = project_state(eng.event_store.fold())
    vs = replace(vs, amt=eng.latest_amt, quant_decision=eng.latest_quant_decision,
                 agent_decision=eng.latest_agent_decision)
    ws_data = view_state_to_ws(vs)

    assert "_symbol" in ws_data
    assert "agentDecision" in ws_data
    assert "quantDecision" in ws_data
    assert ws_data["agentDecision"] is not None
