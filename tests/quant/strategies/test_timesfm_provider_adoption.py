import numpy as np

from quant.decision.context import DecisionContext
from quant.decision.timesfm_agents import TimesFMForecast
from quant.modeling.contracts import ForecastStatus
from quant.modeling.forecast_provider import ForecastProvider
from quant.strategies.timesfm_strategy import TimesFMTradingStrategy


def test_strategy_uses_injected_provider_snapshot(monkeypatch):
    provider = ForecastProvider(model_loader=lambda: None)
    strategy = TimesFMTradingStrategy(forecast_provider=provider)
    ctx = DecisionContext(symbol="NIFTY", bar=type("Bar", (), {"close": 100.0, "time": "t"})())

    monkeypatch.setattr(provider, "forecast", lambda *args, **kwargs: type(
        "Snapshot", (), {"status": ForecastStatus.UNAVAILABLE, "failure_reason": "offline"}
    )())

    assert strategy._compute_forecast(ctx) is None
