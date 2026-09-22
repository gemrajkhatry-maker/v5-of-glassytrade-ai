import pytest
from quant.execution.risk import SessionRisk

def test_initial_state():
    r = SessionRisk()
    assert r.state().halted is False
    # House Money Protocol conservative tier: 0.25% of equity
    assert r.state().risk_per_trade_pct == 0.0025
    assert r.state().cushion_tier == "CONSERVATIVE"

def test_losses_shrink_risk():
    r = SessionRisk()
    r.record_trade(-200.0)
    r.record_trade(-300.0)
    assert r.state().consecutive_losses == 2
    # Still in CONSERVATIVE HMP tier after losses (no aggressive 5% branch)
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
    # The hard 2% session kill switch fires before the configured 3% limit.
    assert s.halted is True and "kill switch" in s.halt_reason

def test_max_streak_halts():
    r = SessionRisk(max_consecutive_losses=3)
    r.record_trade(-100.0); r.record_trade(-100.0); r.record_trade(-100.0)
    s = r.state()
    assert s.halted is True and "loss" in s.halt_reason

def test_position_size_risk_based():
    # Pin a mid-week day: DAY_OF_WEEK_MULTIPLIER halves risk on Mon/Fri, so an unpinned day makes this assertion calendar-dependent.
    r = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01, day_of_week=1)
    # Flat CONSERVATIVE tier uses 0.25% risk (not base_risk_pct)
    # quantity = 100000 * 0.0025 / 1.0 = 250
    qty = r.position_size(entry=100.0, sl=99.0)
    assert qty == pytest.approx(250.0)


def test_paper_capital_deployment_is_a_notional_ceiling():
    """Deployment policy caps notional without replacing stop-loss risk sizing."""
    # Pin a mid-week day: DAY_OF_WEEK_MULTIPLIER halves risk on Mon/Fri, so an unpinned day makes this assertion calendar-dependent.
    r = SessionRisk(
        starting_equity=100_000.0,
        base_risk_pct=0.005,
        capital_deployment_pct=0.95,
        day_of_week=1,
    )

    qty = r.position_size(entry=100.0, sl=99.0, lot_size=100.0)

    # CONSERVATIVE tier: 0.25% risk → risk_amount = 250 → raw_qty = 250
    # snap_to_lot(250, 100) = 200 (2 lots); deployment cap allows 2 lots
    assert qty == pytest.approx(200.0)
    assert qty * 100.0 <= 100_000.0 * 0.95
    assert r.state().risk_per_trade_pct == pytest.approx(0.0025)


def test_paper_capital_deployment_does_not_change_stop_risk_tier():
    r = SessionRisk(
        starting_equity=100_000.0,
        base_risk_pct=0.005,
        capital_deployment_pct=0.95,
    )

    # CONSERVATIVE tier uses 0.25% risk (not base_risk_pct)
    assert r.state().risk_per_trade_pct == pytest.approx(0.0025)

def test_cushion_tier_progression():
    """Test Fabio's tier escalation: CUSHION_TIER_1 → CONSERVATIVE."""
    r = SessionRisk(starting_equity=100000.0)
    # Trade 1: win → session R = 1.0, pnl > 0 → CUSHION_TIER_1
    r.record_trade(+500.0)
    assert r.state().cushion_tier == "CUSHION_TIER_1"
    # Trade 2: win → session R = 2.0, 2 consecutive wins, r_mult >= 0.5 → MOMENTUM
    r.record_trade(+500.0)
    assert r.state().cushion_tier == "MOMENTUM"
    # Trade 3: loss → session R = 1.6, consecutive_wins reset → CUSHION_TIER_1
    r.record_trade(-200.0)
    assert r.state().cushion_tier == "CUSHION_TIER_1"
    # Trade 4: loss → 2 consecutive losses → CONSERVATIVE
    r.record_trade(-200.0)
    assert r.state().cushion_tier == "CONSERVATIVE"

def test_partial_fills_do_not_inflate_trades_today():
    from quant.execution.risk import SessionRisk

    r = SessionRisk(storage=None, symbol="COUNT_TEST")
    r.record_trade(10.0, count_as_trade=False)  # TP1 partial
    r.record_trade(5.0, count_as_trade=False)   # TP2 partial
    r.record_trade(7.0)                          # runner close = the trade
    st = r.state()
    assert st.trades_today == 1
    assert st.daily_pnl == 22.0

def test_partial_fills_do_not_reset_loss_streak():
    r = SessionRisk(storage=None, symbol="PARTIAL_STREAK_TEST")
    r.record_trade(-1000.0); r.record_trade(-1000.0)          # 2 real losses
    r.record_trade(+500.0, count_as_trade=False)              # TP1 partial "win"
    st = r.state()
    assert st.consecutive_losses == 2, "partial must not reset the loss streak"
    r.record_trade(-1000.0)                                    # 3rd real loss
    assert r.state().halted, "3 consecutive REAL losses must trip the halt"
    assert "consecutive" in r._halt_reason

def test_scratch_exit_does_not_count_as_consecutive_loss():
    from quant.execution.risk import SessionRisk

    r = SessionRisk(storage=None, symbol="SCRATCH_TEST")
    r.record_trade(0.0)
    r.record_trade(0.0)
    r.record_trade(0.0)
    st = r.state()
    assert st.consecutive_losses == 0
    assert not st.halted

def test_house_money_bonus_capped():
    r = SessionRisk(starting_equity=1_000_000, base_risk_pct=0.01)
    r._daily_pnl = 200_000      # huge winning day
    r._consecutive_wins = 2
    r._trades_today = 2         # past the 1-2 trade CONSERVATIVE warmup
    # 2+ consecutive wins with r_mult >= 0.5 → MOMENTUM (capped at 0.40%)
    assert r._cushion_tier() == "MOMENTUM"
    assert r._risk_per_trade_pct() == pytest.approx(0.0040)


def test_day_of_week_multiplier_monday_defensive():
    """Monday (0) and Friday (4) apply 0.5x defensive multiplier."""
    from quant.execution.risk import DAY_OF_WEEK_MULTIPLIER

    # CONSERVATIVE tier: 0.25% risk → risk_amount = 250 → raw_qty = 250
    # Monday: defensive sizing (0.5x)
    r_mon = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01, day_of_week=0)
    qty_mon = r_mon.position_size(entry=100.0, sl=99.0)
    assert qty_mon == pytest.approx(250.0 * DAY_OF_WEEK_MULTIPLIER[0])

    # Tuesday: full sizing (1.0x)
    r_tue = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01, day_of_week=1)
    qty_tue = r_tue.position_size(entry=100.0, sl=99.0)
    assert qty_tue == pytest.approx(250.0 * DAY_OF_WEEK_MULTIPLIER[1])

    # Friday: defensive sizing (0.5x)
    r_fri = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01, day_of_week=4)
    qty_fri = r_fri.position_size(entry=100.0, sl=99.0)
    assert qty_fri == pytest.approx(250.0 * DAY_OF_WEEK_MULTIPLIER[4])

    # Monday and Friday should be half of Tuesday
    assert qty_mon == pytest.approx(qty_tue * 0.5)
    assert qty_fri == pytest.approx(qty_tue * 0.5)
