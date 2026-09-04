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