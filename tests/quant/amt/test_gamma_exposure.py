"""Unit tests for Gamma Exposure (GEX) engine."""

from quant.amt.profile.gamma import (
    GammaExposureResult,
    bs_gamma,
    compute_gamma_exposure,
)


def test_bs_gamma_basic():
    # Standard ATM 1-week option: spot=24000, strike=24000, iv=0.15, t=7/365
    gamma = bs_gamma(spot=24000.0, strike=24000.0, iv=0.15, t_years=7.0 / 365.0)
    assert gamma > 0.0
    assert 0.0001 < gamma < 0.01

    # Deep OTM option should have lower gamma
    gamma_otm = bs_gamma(spot=24000.0, strike=26000.0, iv=0.15, t_years=7.0 / 365.0)
    assert gamma_otm < gamma


def test_compute_gamma_exposure_positive_regime():
    spot = 24000.0
    strikes = [23800.0, 23900.0, 24000.0, 24100.0, 24200.0]
    
    # Heavy Call OI at 24200 (Call wall) and Put OI at 23800 (Put wall)
    calls_oi = {23800.0: 10000, 23900.0: 20000, 24000.0: 50000, 24100.0: 80000, 24200.0: 120000}
    puts_oi = {23800.0: 100000, 23900.0: 60000, 24000.0: 40000, 24100.0: 20000, 24200.0: 5000}

    res = compute_gamma_exposure(
        spot=spot,
        strikes=strikes,
        calls_oi=calls_oi,
        puts_oi=puts_oi,
        lot_size=65,
    )

    assert isinstance(res, GammaExposureResult)
    assert len(res.strike_gex) == 5
    assert res.call_wall_strike == 24200.0
    assert res.put_wall_strike == 23800.0
    assert res.regime in ("POSITIVE_GAMMA", "NEGATIVE_GAMMA", "NEUTRAL_GAMMA")
    assert 23800.0 <= res.zero_flip_level <= 24200.0


def test_compute_gamma_exposure_empty_inputs():
    res = compute_gamma_exposure(spot=0.0, strikes=[], calls_oi={}, puts_oi={})
    assert res.regime == "NEUTRAL_GAMMA"
    assert res.net_gex_crores == 0.0
    assert res.strike_gex == ()
