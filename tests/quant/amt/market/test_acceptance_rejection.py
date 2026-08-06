"""Unit tests for acceptance_rejection — acceptance/rejection at VA boundaries."""

import pytest

from quant.amt.market.acceptance_rejection import ARResult, AcceptanceRejectionEngine
from quant.contracts.value_objects import OHLC


def _candle(t, o, h, l, c, v=1000, delta=0.0) -> OHLC:
    return OHLC(time=t, open=o, high=h, low=l, close=c, volume=v,
                delta=delta, taker_buy_volume=0.0)


class TestAcceptanceRejectionEngine:
    def test_initial_update_returns_flags_false(self):
        engine = AcceptanceRejectionEngine()
        result = engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        assert isinstance(result, ARResult)
        assert result.acceptance_above is False
        assert result.acceptance_below is False

    def test_dict_like_access(self):
        engine = AcceptanceRejectionEngine()
        result = engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        assert result["acceptance_above"] is False
        assert "acceptance_below" in result
        assert result.get("rejection_at_high") is False
        assert result.get("missing_key", "default") == "default"

    def test_acceptance_above_vah(self):
        engine = AcceptanceRejectionEngine(time_threshold=100.0)
        engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        result = engine.update(_candle("2024-01-01T09:17:00+00:00", 106, 107, 105.5, 106.5, v=2000), 105.0, 95.0, 1000.0)
        assert result.acceptance_above is True

    def test_acceptance_below_val(self):
        engine = AcceptanceRejectionEngine(time_threshold=100.0)
        engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        result = engine.update(_candle("2024-01-01T09:17:00+00:00", 94, 95, 93, 93.5, v=2000), 105.0, 95.0, 1000.0)
        assert result.acceptance_below is True

    def test_rejection_at_high(self):
        engine = AcceptanceRejectionEngine()
        # Wicks above VAH with volume spike, close back below
        result = engine.update(
            _candle("2024-01-01T09:15:00+00:00", 104.5, 105.3, 104.0, 104.8, v=2000), 105.0, 95.0, 1000.0
        )
        assert result.rejection_at_high is True

    def test_rejection_at_low(self):
        engine = AcceptanceRejectionEngine()
        result = engine.update(
            _candle("2024-01-01T09:15:00+00:00", 95.6, 96.0, 94.8, 95.5, v=2000), 105.0, 95.0, 1000.0
        )
        assert result.rejection_at_low is True

    def test_liquidity_sweep_high(self):
        engine = AcceptanceRejectionEngine()
        result = engine.update(
            _candle("2024-01-01T09:15:00+00:00", 104.5, 105.6, 104.0, 104.6, v=2000), 105.0, 95.0, 1000.0
        )
        assert result.liquidity_sweep == "SWEEP_HIGH"

    def test_reset_clears_state(self):
        engine = AcceptanceRejectionEngine(time_threshold=100.0)
        engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        engine.update(_candle("2024-01-01T09:17:00+00:00", 106, 107, 105.5, 106.5, v=2000), 105.0, 95.0, 1000.0)
        engine.reset()
        result = engine.update(_candle("2024-01-01T09:19:00+00:00", 106, 107, 105.5, 106.5, v=2000), 105.0, 95.0, 1000.0)
        assert result.acceptance_above is False
