import pytest
from quant.execution.risk import SessionRisk

def test_initial_state():
    r = SessionRisk()
    assert r.state().halted is False
    # Aggressive mode (base_risk_pct >= 5%): risk_per_trade_pct returns base_risk_pct
    assert r.state().risk_per_trade_pct == 0.05
    assert r.state().cushion_tier == "CONSERVATIVE"

def test_losses_shrink_risk():
    r = SessionRisk()
    r.record_trade(-200.0)
    r.record_trade(-300.0)
    assert r.state().consecutive_losses == 2
    # Aggressive mode: risk_per_trade_pct stays at base_risk_pct (5%)
    assert r.state().risk_per_trade_pct == 0.05

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
    # Conservative tier (base_risk_pct < 5%): first trades are CONSERVATIVE = 0.25%
    # quantity = 100000 * 0.0025 / 1.0 = 250
    qty = r.position_size(entry=100.0, sl=99.0)
    assert qty == pytest.approx(250.0)


def test_paper_capital_deployment_is_a_notional_ceiling():
    """Deployment policy caps notional without replacing stop-loss risk sizing."""
    r = SessionRisk(
        starting_equity=100_000.0,
        base_risk_pct=0.005,
        capital_deployment_pct=0.95,
    )

    qty = r.position_size(entry=100.0, sl=99.0, lot_size=100.0)

    # Conservative Fabio risk tier sizes 2 lots; deployment policy is only
    # the independent 95% notional ceiling.
    assert qty == pytest.approx(200.0)
    assert qty * 100.0 <= 100_000.0 * 0.95
    assert r.state().risk_per_trade_pct == pytest.approx(0.0025)


def test_paper_capital_deployment_does_not_change_stop_risk_tier():
    r = SessionRisk(
        starting_equity=100_000.0,
        base_risk_pct=0.005,
        capital_deployment_pct=0.95,
    )

    assert r.state().risk_per_trade_pct == pytest.approx(0.0025)

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
    pct = r._risk_per_trade_pct()
    assert pct <= 0.005 + 1e-9, "never exceed 0.50% total"
    bonus = pct - 0.004
    assert bonus <= 0.30 * 200_000 / 1_000_000 + 1e-9, "addition never exceeds 30% of session profit"


def test_day_of_week_multiplier_monday_defensive():
    """Monday (0) and Friday (4) apply 0.5x defensive multiplier."""
    from quant.execution.risk import DAY_OF_WEEK_MULTIPLIER

    # Monday: defensive sizing
    r_mon = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01, day_of_week=0)
    qty_mon = r_mon.position_size(entry=100.0, sl=99.0)
    assert qty_mon == pytest.approx(250.0 * DAY_OF_WEEK_MULTIPLIER[0])

    # Tuesday: full sizing
    r_tue = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01, day_of_week=1)
    qty_tue = r_tue.position_size(entry=100.0, sl=99.0)
    assert qty_tue == pytest.approx(250.0 * DAY_OF_WEEK_MULTIPLIER[1])

    # Friday: defensive sizing
    r_fri = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01, day_of_week=4)
    qty_fri = r_fri.position_size(entry=100.0, sl=99.0)
    assert qty_fri == pytest.approx(250.0 * DAY_OF_WEEK_MULTIPLIER[4])

    # Monday and Friday should be half of Tuesday
    assert qty_mon == pytest.approx(qty_tue * 0.5)
    assert qty_fri == pytest.approx(qty_tue * 0.5)
