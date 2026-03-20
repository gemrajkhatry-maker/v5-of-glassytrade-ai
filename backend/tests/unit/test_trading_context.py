"""Unit tests for TradingContext dataclass.

Tests the immutable context object that eliminates parameter clumps.
"""

import pytest
from unittest.mock import MagicMock
from app.domain.trading.models.trading_context import TradingContext


class TestTradingContext:
    """Test suite for TradingContext."""

    def test_frozen_dataclass(self):
        """TradingContext should be immutable (frozen)."""
        tick = MagicMock()
        tick.close = 100.0
        tick.volume = 1000
        tick.delta = 50
        tick.time = "2026-03-17T09:30:00"

        amt_result = MagicMock()
        amt_result.market_state = "BALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = 0.5
        amt_result.aggression = 2.5
        amt_result.session_vwap = 100.0
        amt_result.profile_shape = "D"

        ctx = TradingContext(tick=tick, amt_result=amt_result)

        # Should not be able to mutate
        with pytest.raises(AttributeError):
            ctx.tick = MagicMock()

    def test_price_property(self):
        """price property should return tick.close as float."""
        tick = MagicMock()
        tick.close = 100.5
        tick.volume = 1000
        tick.delta = 50

        amt_result = MagicMock()
        amt_result.market_state = "BALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = 0.5
        amt_result.aggression = 2.5
        amt_result.session_vwap = 100.0
        amt_result.profile_shape = "D"

        ctx = TradingContext(tick=tick, amt_result=amt_result)
        assert ctx.price == 100.5

    def test_market_state_property(self):
        """market_state property should return amt_result.market_state as string."""
        tick = MagicMock()
        tick.close = 100.0
        tick.volume = 1000
        tick.delta = 50

        amt_result = MagicMock()
        amt_result.market_state = "IMBALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = 0.5
        amt_result.aggression = 2.5
        amt_result.session_vwap = 100.0
        amt_result.profile_shape = "P"

        ctx = TradingContext(tick=tick, amt_result=amt_result)
        assert ctx.market_state == "IMBALANCED"

    def test_agent_direction_with_decision(self):
        """agent_direction should return agent_decision.direction."""
        tick = MagicMock()
        tick.close = 100.0
        tick.volume = 1000
        tick.delta = 50

        amt_result = MagicMock()
        amt_result.market_state = "BALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = 0.5
        amt_result.aggression = 2.5
        amt_result.session_vwap = 100.0
        amt_result.profile_shape = "D"

        agent_decision = MagicMock()
        agent_decision.direction = "LONG"
        agent_decision.probability = 0.75
        agent_decision.regime = "TREND"

        ctx = TradingContext(
            tick=tick,
            amt_result=amt_result,
            agent_decision=agent_decision,
        )
        assert ctx.agent_direction == "LONG"
        assert ctx.agent_probability == 0.75
        assert ctx.agent_regime == "TREND"

    def test_agent_direction_without_decision(self):
        """agent_direction should return FLAT when no agent_decision."""
        tick = MagicMock()
        tick.close = 100.0
        tick.volume = 1000
        tick.delta = 50

        amt_result = MagicMock()
        amt_result.market_state = "BALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = 0.5
        amt_result.aggression = 2.5
        amt_result.session_vwap = 100.0
        amt_result.profile_shape = "D"

        ctx = TradingContext(tick=tick, amt_result=amt_result)
        assert ctx.agent_direction == "FLAT"
        assert ctx.agent_probability == 0.5

    def test_with_tick_returns_new_context(self):
        """with_tick should return a new context with updated tick."""
        tick1 = MagicMock()
        tick1.close = 100.0
        tick1.volume = 1000
        tick1.delta = 50

        tick2 = MagicMock()
        tick2.close = 101.0
        tick2.volume = 2000
        tick2.delta = 100

        amt_result = MagicMock()
        amt_result.market_state = "BALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = 0.5
        amt_result.aggression = 2.5
        amt_result.session_vwap = 100.0
        amt_result.profile_shape = "D"

        ctx1 = TradingContext(tick=tick1, amt_result=amt_result)
        ctx2 = ctx1.with_tick(tick2)

        # Original unchanged
        assert ctx1.price == 100.0
        # New context has updated tick
        assert ctx2.price == 101.0
        # AMT result preserved
        assert ctx2.market_state == "BALANCED"

    def test_vwap_fallback_to_price(self):
        """vwap should fall back to price when session_vwap is 0."""
        tick = MagicMock()
        tick.close = 100.0
        tick.volume = 1000
        tick.delta = 50

        amt_result = MagicMock()
        amt_result.market_state = "BALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = 0.5
        amt_result.aggression = 2.5
        amt_result.session_vwap = 0  # No VWAP
        amt_result.profile_shape = "D"

        ctx = TradingContext(tick=tick, amt_result=amt_result)
        assert ctx.vwap == 100.0  # Falls back to price


if __name__ == "__main__":
    pytest.main([__file__, "-v"])