import pytest
from quant.execution.risk import SessionRisk

def test_initial_state():
    r = SessionRisk()
    assert r.state().halted is False
    # Fabio cushion system: first trades are CONSERVATIVE tier = 0.25% (was 0.5% static)
    assert r.state().risk_per_trade_pct == 0.0025
    assert r.state().cushion_tier == "CONSERVATIVE"

def test_losses_shrink_risk():
    r = SessionRisk()
    r.record_trade(-200.0)
    r.record_trade(-300.0)
    assert r.state().consecutive_losses == 2
    # 2+ consecutive losses → stays CONSERVATIVE = 0.25%
    assert r.state().risk_per_trade_pct == 0.0025

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
    # Fabio: first trades are CONSERVATIVE tier = 0.25%, not the base_risk_pct
    # quantity = 100000 * 0.0025 / 1.0 = 250
    qty = r.position_size(entry=100.0, sl=99.0)
    assert qty == pytest.approx(250.0)

def test_cushion_tier_progression():
    """Test Fabio's tier escalation: CONSERVATIVE → CUSHION → MOMENTUM."""
    r = SessionRisk(starting_equity=100000.0)
    # Trade 1: win → still < 2 trades, CONSERVATIVE
    r.record_trade(+500.0)
    assert r.state().cushion_tier == "CONSERVATIVE"
    # Trade 2: win → 2 trades done, 2 consecutive wins, pnl > 0 → MOMENTUM
    r.record_trade(+500.0)
    assert r.state().cushion_tier == "MOMENTUM"
    # Trade 3: loss → breaks win streak → pnl still > 0 → CUSHION
    r.record_trade(-200.0)
    assert r.state().cushion_tier == "CUSHION"
    # Trade 4: loss → 2 consecutive losses → CONSERVATIVE
    r.record_trade(-200.0)
    assert r.state().cushion_tier == "CONSERVATIVE"
