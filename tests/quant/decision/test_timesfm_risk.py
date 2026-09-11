from quant.decision.timesfm_risk import TimesFMRiskAuthority


def test_timesfm_risk_authority_has_no_position_trail_store():
    """Risk calculation must be stateless; ExitEngine owns stop state."""
    authority = TimesFMRiskAuthority()
    assert not hasattr(authority, "_trail_stops")
    assert not hasattr(authority, "_is_risk_free")


def test_evaluate_exit_returns_candidate_without_mutating_position_state():
    import numpy as np
    from quant.decision.timesfm_agents import TimesFMForecast

    authority = TimesFMRiskAuthority()
    p50 = np.linspace(100.0, 103.0, 8)
    fc = TimesFMForecast(
        horizon=8, p50_path=p50, p10_path=p50 - 1.0, p90_path=p50 + 1.0,
        q_spread=2.0, mean_forecast=103.0, pct_change=0.03,
        forecast_steps=["LONG"] * 8, curr_price=100.0, lat_ms=1.0,
    )
    result = authority.evaluate_exit(
        position_id="p1", side="LONG", entry=100.0, current_price=102.0,
        bars_held=3, forecast=fc, active_sl=99.0,
    )
    assert result.new_stop is not None
    assert not hasattr(authority, "_trail_stops")
