from unittest.mock import MagicMock
from quant.decision.forecast_provider import fresh_forecast


def test_prefers_advisor_native_engine():
    fc = object()
    advisor = MagicMock()
    advisor._native_engine.last_forecast_for.return_value = fc
    assert fresh_forecast(advisor, None, symbol="NIFTY", bar_index=5) is fc


def test_falls_back_to_strategy_then_none():
    strategy = MagicMock()
    strategy.get_latest_forecast.return_value = None
    advisor = MagicMock()
    advisor._native_engine.last_forecast_for.return_value = None
    assert fresh_forecast(advisor, strategy, symbol="NIFTY", bar_index=5) is None


def test_no_advisor_no_strategy_returns_none():
    assert fresh_forecast(None, None, symbol="NIFTY", bar_index=5) is None
