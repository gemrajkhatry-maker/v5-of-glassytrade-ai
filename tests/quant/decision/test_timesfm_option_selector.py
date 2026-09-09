"""Unit tests for TimesFM Quantitative Option Contract Selector."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest

from quant.decision.timesfm_agents import TimesFMForecast
from quant.decision.timesfm_option_selector import (
    ScoredOptionContract,
    TimesFMOptionSelector,
    find_velocity_horizon,
    simulate_contract_payoff,
)


def _make_mock_option(
    ltp=120.0,
    bid=119.5,
    ask=120.5,
    volume=25000,
    oi=500000,
    delta=0.52,
    gamma=0.0015,
    theta=-12.0,
    iv=16.0,
    symbol="NIFTY 24500 CE",
):
    opt = MagicMock()
    opt.symbol = symbol
    opt.ltp = ltp
    opt.bid = bid
    opt.ask = ask
    opt.volume = volume
    opt.oi = oi
    opt.delta = delta
    opt.gamma = gamma
    opt.theta = theta
    opt.iv = iv
    return opt


def _make_bullish_forecast(curr_price=24500.0, horizon=32, target_drift=60.0):
    p50 = np.linspace(curr_price, curr_price + target_drift, horizon)
    p10 = p50 - 15.0
    p90 = p50 + 20.0
    return TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=35.0,
        mean_forecast=float(p50[-1]),
        pct_change=(p50[-1] - curr_price) / curr_price,
        forecast_steps=["LONG"] * horizon,
        curr_price=curr_price,
        lat_ms=12.0,
    )


def test_find_velocity_horizon_long():
    forecast = _make_bullish_forecast(24500.0, horizon=32, target_drift=50.0)
    tau, drift = find_velocity_horizon(forecast, "LONG")
    assert tau >= 2
    assert drift > 0.0


def test_simulate_contract_payoff_bullish():
    forecast = _make_bullish_forecast(24500.0, horizon=32, target_drift=60.0)
    opt = _make_mock_option(
        ltp=150.0,
        bid=149.0,
        ask=151.0,
        volume=20000,
        oi=1000000,
        delta=0.50,
        gamma=0.001,
        theta=-8.0,
    )
    contract = simulate_contract_payoff(
        opt=opt,
        strike=24500,
        option_type="CE",
        underlying="NIFTY",
        expiry_str="2026-03-20",
        forecast=forecast,
        direction="LONG",
        bar_duration_minutes=5.0,
    )
    assert contract is not None
    assert contract.expected_delta_v > 0.0
    assert contract.expected_roc > 0.0
    assert contract.timesfm_edge > 0.0
    assert contract.is_theta_viable is True
    assert contract.composite_score > 40.0


def test_simulate_contract_payoff_theta_drain_trap():
    """Verify that a slow drift with severe theta decay triggers the theta trap."""
    curr = 24500.0
    # Price takes 30 bars to drift only 5 points (very slow, negligible drift)
    p50 = np.linspace(curr, curr + 5.0, 32)
    p10 = p50 - 20.0
    p90 = p50 + 20.0
    slow_forecast = TimesFMForecast(
        horizon=32,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=40.0,
        mean_forecast=float(p50[-1]),
        pct_change=0.0002,
        forecast_steps=["LONG"] * 32,
        curr_price=curr,
        lat_ms=10.0,
    )
    # Severe theta decay: -50/day on a 40 LTP option
    opt = _make_mock_option(
        ltp=40.0,
        bid=39.0,
        ask=41.0,
        volume=1000,
        oi=50000,
        delta=0.40,
        gamma=0.0005,
        theta=-50.0,
    )
    contract = simulate_contract_payoff(
        opt=opt,
        strike=24550,
        option_type="CE",
        underlying="NIFTY",
        expiry_str="2026-03-20",
        forecast=slow_forecast,
        direction="LONG",
        bar_duration_minutes=5.0,
        max_theta_ratio=0.25,
    )
    assert contract is not None
    assert contract.is_theta_viable is False
    assert contract.theta_drain_ratio > 0.25


def test_timesfm_option_selector_evaluate_chain():
    selector = TimesFMOptionSelector()
    forecast = _make_bullish_forecast(24500.0, horizon=32, target_drift=60.0)

    # Build mock chain around 24500
    chain = MagicMock()
    chain.atm_strike = 24500.0
    chain.expiry = datetime(2026, 3, 20, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    chain.calls = {
        24400.0: _make_mock_option(ltp=210.0, delta=0.68, gamma=0.0008, symbol="NIFTY 24400 CE"),
        24500.0: _make_mock_option(ltp=140.0, delta=0.52, gamma=0.0016, symbol="NIFTY 24500 CE"),
        24600.0: _make_mock_option(ltp=85.0, delta=0.36, gamma=0.0012, symbol="NIFTY 24600 CE"),
    }
    chain.puts = {
        24500.0: _make_mock_option(ltp=135.0, delta=-0.48, symbol="NIFTY 24500 PE"),
    }

    results = selector.evaluate_chain(
        chain=chain,
        underlying="NIFTY",
        forecast=forecast,
        direction="LONG",
        strikes_around_atm=2,
    )

    assert len(results) >= 2
    # Highest composite score should be first
    assert results[0].composite_score >= results[1].composite_score
    # All returned contracts must be CE for a LONG direction
    assert all(r.option_type == "CE" for r in results)
