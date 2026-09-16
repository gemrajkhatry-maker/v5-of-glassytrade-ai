from quant.decision.context import DecisionContext
from quant.decision.gates import (
    gate_session_phase, gate_position_cooldown)

def _ctx(**kw):
    d = dict(state=None, bar=None)
    d.update(kw)
    return DecisionContext(**d)

def test_gate1_passes_when_open_and_warm():
    r = gate_session_phase(_ctx(session_open=True, warmup_complete=True))
    assert r.passed and r.gate == 1

def test_gate1_fails_when_closed():
    r = gate_session_phase(_ctx(session_open=False))
    assert not r.passed and r.gate == 1

def test_gate1_fails_when_warming_up():
    r = gate_session_phase(_ctx(warmup_complete=False))
    assert not r.passed

def test_gate2_passes_when_flat_no_cooldown():
    r = gate_position_cooldown(_ctx(position_open=False, cooldown_remaining_sec=0))
    assert r.passed and r.gate == 2

def test_gate2_fails_when_position_open():
    assert not gate_position_cooldown(_ctx(position_open=True)).passed

def test_gate2_fails_in_cooldown():
    assert not gate_position_cooldown(_ctx(cooldown_remaining_sec=30)).passed
