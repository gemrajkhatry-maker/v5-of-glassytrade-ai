from quant.decision.context import DecisionContext
from quant.decision.gate_position_cooldown import gate_position_cooldown
from quant.decision.gate_session_phase import gate_session_phase

def _ctx(**kw):
    d = dict(state=None, bar=None, bid=99.95, ask=100.05, tick_size=0.05)
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


def test_gate1_option_spread_allows_normal_liquidity():
    """Option with contract_symbol set allows healthy option spread (> 0.50)."""
    # 0.90 spread on a ~300 premium option (0.30%)
    ctx = _ctx(
        symbol="BANKNIFTY SEP FUT",
        contract_symbol="BANKNIFTY 29 SEP 55700 PUT",
        bid=299.10,
        ask=300.00,
        tick_size=0.05,
    )
    r = gate_session_phase(ctx)
    assert r.passed, f"Option spread should pass but failed with: {r.reason}"


def test_gate1_futures_spread_rejects_wide_spread():
    """Futures contract strictly enforces the tight futures spread limit (0.50)."""
    ctx = _ctx(
        symbol="BANKNIFTY SEP FUT",
        contract_symbol="",
        bid=55700.00,
        ask=55770.00,
        tick_size=0.05,
    )
    r = gate_session_phase(ctx)
    assert not r.passed
    assert "Wide spread" in r.reason
