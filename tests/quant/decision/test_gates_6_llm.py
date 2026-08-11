from quant.decision.context import DecisionContext
from quant.decision.gates_llm import gate_llm_consensus


def _ctx(**kw):
    return DecisionContext(
        state=None,
        bar=None,
        agent_direction=kw.get("agent_direction", "LONG"),
        llm_direction=kw.get("llm_direction"),
        llm_confidence=kw.get("llm_confidence"),
        llm_fresh=kw.get("llm_fresh", True),
        llm_execution_enabled=kw.get("llm_execution_enabled", False),
    )


def test_disabled_passes_even_with_conflicting_advisory():
    r = gate_llm_consensus(_ctx(llm_direction="SHORT", llm_confidence="High"))
    assert r.passed and r.gate == 7
    assert "advisory-only" in r.reason


def test_enabled_agree_high_passes():
    r = gate_llm_consensus(_ctx(
        llm_direction="LONG", llm_confidence="High",
        llm_execution_enabled=True,
    ))
    assert r.passed
    assert "confirms" in r.reason


def test_enabled_disagreement_blocks():
    r = gate_llm_consensus(_ctx(
        llm_direction="SHORT", llm_confidence="High",
        llm_execution_enabled=True,
    ))
    assert not r.passed
    assert "disagrees" in r.reason


def test_enabled_low_confidence_blocks():
    r = gate_llm_consensus(_ctx(
        llm_direction="LONG", llm_confidence="Medium",
        llm_execution_enabled=True,
    ))
    assert not r.passed
    assert "confidence" in r.reason


def test_enabled_no_llm_direction_blocks():
    r = gate_llm_consensus(_ctx(
        llm_direction="FLAT", llm_confidence="High",
        llm_execution_enabled=True,
    ))
    assert not r.passed
    assert "no direction" in r.reason


def test_enabled_stale_advisory_blocks():
    r = gate_llm_consensus(_ctx(
        llm_direction="LONG", llm_confidence="High", llm_fresh=False,
        llm_execution_enabled=True,
    ))
    assert not r.passed
    assert "stale" in r.reason


def test_enabled_no_agent_direction_not_applicable():
    # Gate 4 already blocks no-direction; gate 7 must not double-report.
    r = gate_llm_consensus(_ctx(
        agent_direction=None, llm_direction="LONG", llm_confidence="High",
        llm_execution_enabled=True,
    ))
    assert r.passed
