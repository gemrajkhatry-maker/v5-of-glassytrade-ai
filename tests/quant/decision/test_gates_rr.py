# tests/quant/decision/test_gates_rr.py
"""Tests for gate 4 (risk-reward) — structural stop cap enforcement."""


def test_gate4_rejects_stop_beyond_20_ticks(monkeypatch):
    from quant.decision import gates_rr
    from quant.decision.context_builder import DecisionContextBuilder
    from quant.bars import Bar
    from quant.execution.risk import SessionRisk

    monkeypatch.setattr(gates_rr, "structural_anchor", lambda ctx, direction: 80.0)

    ctx = DecisionContextBuilder().build(
        bar=Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0),
        symbol="S", market="NSE", contract_expiry=None, tick_size=0.05,
        bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=SessionRisk(storage=None, symbol="S").state(),
        amt_dto={"absorptionSide": "SELL_ABSORBED"},  # gives agent_direction LONG
    )
    assert ctx.agent_direction == "LONG"
    result = gates_rr.gate_risk_reward(ctx)
    assert not result.passed
    assert "wide" in result.reason.lower()


def test_gate4_passes_stop_within_cap(monkeypatch):
    from quant.decision import gates_rr
    from quant.decision.context_builder import DecisionContextBuilder
    from quant.bars import Bar
    from quant.execution.risk import SessionRisk

    monkeypatch.setattr(gates_rr, "structural_anchor", lambda ctx, direction: 99.5)

    ctx = DecisionContextBuilder().build(
        bar=Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0),
        symbol="S", market="NSE", contract_expiry=None, tick_size=0.05,
        bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=SessionRisk(storage=None, symbol="S").state(),
        amt_dto={"absorptionSide": "SELL_ABSORBED"},
    )
    result = gates_rr.gate_risk_reward(ctx)
    assert result.passed
