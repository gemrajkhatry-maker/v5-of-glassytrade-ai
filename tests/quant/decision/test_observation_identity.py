from quant.decision.timesfm_agents import TimesFMForecast
from quant.modeling.observation import ForecastObservationIdentity
import numpy as np


def test_forecast_can_carry_observation_identity():
    identity = ForecastObservationIdentity("NIFTY", "NIFTY FUT", 300, "t1", 7, 100.0, True)
    p = np.full(4, 100.0)
    forecast = TimesFMForecast(
        horizon=4, p50_path=p, p10_path=p - 1, p90_path=p + 1,
        q_spread=2.0, mean_forecast=100.0, pct_change=0.0,
        forecast_steps=["FLAT"] * 4, curr_price=100.0, lat_ms=1.0,
        observation=identity,
    )
    assert forecast.observation == identity
    assert forecast.observation.is_complete is True
