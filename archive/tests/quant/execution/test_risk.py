import pytest
from quant.execution.risk import SessionRisk

def test_initial_state():
    r = SessionRisk()
    assert r.state().halted is False
    assert r.state().risk_per_trade_pct == 0.01

def test_losses_shrink_risk():
    r = SessionRisk()
    r.record_trade(-200.0)
    r.record_trade(-300.0)
    assert r.state().consecutive_losses == 2
    assert r.state().risk_per_trade_pct < 0.01

def test_win_resets_streak():
    r = SessionRisk()
    r.record_trade(-200.0); r.record_trade(-300.0)
    r.record_trade(+500.0)
    assert r.state().consecutive_losses == 0

def test_max_loss_halts():
    r = SessionRisk(starting_equity=100000.0, max_daily_loss_pct=0.03)
    r.record_trade(-2500.0); r.record_trade(-2500.0); r.record_trade(-2500.0)
    s = r.state()
    assert s.halted is True and "daily" in s.halt_reason

def test_max_streak_halts():
    r = SessionRisk(max_consecutive_losses=3)
    r.record_trade(-100.0); r.record_trade(-100.0); r.record_trade(-100.0)
    s = r.state()
    assert s.halted is True and "loss" in s.halt_reason

def test_position_size_risk_based():
    r = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01)
    qty = r.position_size(entry=100.0, sl=99.0)   # 1000 risk / 1.0 per unit
    assert qty == pytest.approx(1000.0)
