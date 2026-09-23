"""Task 1: literal §12.2 house-money offensive risk (retracement veto only).

offensive = min(E0*0.0025 + 0.40*pnl, 0.0050) — the 30%-of-profit
cushion cap is deleted; retracement veto and the 0.50% ceiling stay.
"""

from __future__ import annotations

from quant.execution.risk import SessionRisk


def test_offensive_cushion_is_literal_spec_formula():
    r = SessionRisk(starting_equity=100_000.0, day_of_week=1)
    r._daily_pnl = 5_000.0
    r._consecutive_losses = 0
    r._consecutive_wins = 1
    # CUSHION_TIER_1: min(0.0025 + 0.40*5000/100000, 0.0050) = 0.0050
    assert r._cushion_tier() == "CUSHION_TIER_1"
    assert abs(r._risk_per_trade_pct() - 0.0050) < 1e-9


def test_offensive_has_no_30pct_profit_cap_below_ceiling():
    r = SessionRisk(starting_equity=100_000.0, day_of_week=1)
    r._daily_pnl = 500.0
    r._consecutive_losses = 0
    r._consecutive_wins = 1
    # force CUSHION_TIER_1 not MOMENTUM (1 consecutive win, r_mult=1.0)
    assert r._cushion_tier() == "CUSHION_TIER_1"
    # 0.40*500/100000 = 0.002 → 0.0045 (old 30% cap → 0.00265)
    assert abs(r._risk_per_trade_pct() - (0.0025 + 0.002)) < 1e-9


def test_retracement_veto_stays():
    r = SessionRisk(starting_equity=100_000.0, day_of_week=1)
    r._peak_daily_pnl = 4_000.0
    r._daily_pnl = 1_000.0
    r._consecutive_losses = 0
    r._consecutive_wins = 1
    assert r._cushion_tier() == "BASE_RETRACEMENT_VETO"
    assert abs(r._risk_per_trade_pct() - 0.0025) < 1e-9
