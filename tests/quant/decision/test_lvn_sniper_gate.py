"""Unit tests for Gate 3 Path C — Impulse Leg LVN Sniper (Playbook C per spec §9.3)."""

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge


def _ctx(leg_lvn: float = 100.0, close: float = 100.0, absorption_side: str = "SELL_ABSORBED", direction: str = "LONG") -> DecisionContext:
    bar = Bar(time="t1", open=close, high=close, low=close, close=close, volume=100.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM",
        agent_direction=direction,
        agent_probability=0.8,
        market_state="BALANCED",
        session_open=True,
        warmup_complete=True,
        leg_lvn=leg_lvn,
        tick_size=0.05,
        absorption_side=absorption_side,
    )


def test_lvn_sniper_passes_on_retest_and_fresh_absorption():
    ctx = _ctx(leg_lvn=100.0, close=100.05, absorption_side="SELL_ABSORBED", direction="LONG")
    result = gate_triple_a_edge(ctx)

    assert result.passed is True
    assert result.gate == 3
    assert "LVN Sniper LONG" in result.reason


def test_lvn_sniper_rejects_when_price_is_far_from_lvn():
    ctx = _ctx(leg_lvn=100.0, close=102.0, absorption_side="SELL_ABSORBED", direction="LONG")
    result = gate_triple_a_edge(ctx)

    assert result.passed is False
    assert "No Triple-A edge" in result.reason


def test_lvn_sniper_rejects_when_no_fresh_absorption():
    ctx = _ctx(leg_lvn=100.0, close=100.05, absorption_side="", direction="LONG")
    result = gate_triple_a_edge(ctx)

    assert result.passed is False
    assert "No Triple-A edge" in result.reason
