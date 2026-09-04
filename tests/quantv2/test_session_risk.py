from quantv2.session_risk import RiskLimits, SessionRisk


def test_halt_and_cooldown():
    r = SessionRisk(RiskLimits(daily_loss_limit=100.0, max_trades=3, cooldown_sec=60))
    r.record_fill(-10.0, now=1000.0)
    ok, why = r.can_trade(1010.0)
    assert ok is False and why == "COOLDOWN"
    ok, _ = r.can_trade(1070.0)
    assert ok is True
    r.record_fill(-95.0, now=2000.0)
    ok, why = r.can_trade(3000.0)
    assert ok is False and why == "DAILY_LOSS"


def test_max_trades_halt():
    r = SessionRisk(RiskLimits(daily_loss_limit=1e9, max_trades=2, cooldown_sec=0))
    r.record_fill(1.0, now=0.0)
    r.record_fill(1.0, now=0.0)
    ok, why = r.can_trade(1.0)
    assert ok is False and why == "MAX_TRADES"


def test_cushion_and_three_losses():
    r = SessionRisk(RiskLimits(mdl_pct=0.02, max_consec_losses=3, cooldown_sec=60), starting_equity=100000.0)
    r.record_fill(+1000.0, now=0.0)              # cushion 1000 -> offensive adds 0.4x1000
    assert r.size_multiplier() > 1.0
    r.record_fill(-100.0, now=1.0); r.record_fill(-100.0, now=2.0); r.record_fill(-100.0, now=3.0)
    assert r.halt == "THREE_LOSSES"
    r2 = SessionRisk(RiskLimits(mdl_pct=0.02, max_consec_losses=99, cooldown_sec=0), starting_equity=100000.0)
    r2.record_fill(-2100.0, now=0.0)             # > 2% MDL
    assert r2.halt == "DAILY_LOSS"


def test_cooldown_after_every_trade():
    r = SessionRisk(RiskLimits(daily_loss_limit=1e9, mdl_pct=0.0, max_trades=10, cooldown_sec=60), starting_equity=100000.0)
    r.record_fill(+100.0, now=0.0)
    ok, why = r.can_trade(10.0)
    assert ok is False and why == "COOLDOWN"
    ok, _ = r.can_trade(60.0)
    assert ok is True


def test_defensive_size_multiplier():
    r = SessionRisk(RiskLimits(daily_loss_limit=1e9, mdl_pct=0.02, max_consec_losses=3, cooldown_sec=0, base_risk_pct=0.0025), starting_equity=100000.0)
    r.record_fill(-1900.0, now=0.0)              # remaining = 2000 - 1900 = 100 < base 250
    assert 0.0 < r.size_multiplier() < 1.0
    r.record_fill(-100.0, now=1.0)               # breaches MDL
    assert r.halt == "DAILY_LOSS" and r.size_multiplier() == 0.0