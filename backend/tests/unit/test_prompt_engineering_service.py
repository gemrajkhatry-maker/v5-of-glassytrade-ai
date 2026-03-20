"""Unit tests for PromptEngineeringService.

Tests the dedicated prompt building service that extracts prompt construction
from the 500-line LLM worker loop.
"""

import pytest
from unittest.mock import MagicMock
from app.domain.fabio_ai.services.prompt_engineering_service import PromptEngineeringService


class TestPromptEngineeringService:
    """Test suite for PromptEngineeringService."""

    def _make_context(self, market_state="BALANCED", profile_shape="D"):
        """Create a mock TradingContext."""
        ctx = MagicMock()
        ctx.price = 100.0
        ctx.volume = 1000
        ctx.delta = 50
        ctx.market_state = market_state
        ctx.poc = 100.0
        ctx.vah = 101.0
        ctx.val = 99.0
        ctx.cvd_slope = 0.5
        ctx.aggression = 2.5
        ctx.vwap = 100.0
        ctx.profile_shape = profile_shape
        ctx.opening_relation = "ABOVE_PRIOR_VAH"

        ctx.amt_result = MagicMock()
        ctx.amt_result.hvns = (100.5, 101.0)
        ctx.amt_result.lvns = (99.5, 99.0)
        ctx.amt_result.leg_poc = 100.0
        ctx.amt_result.leg_lvns = (99.5,)
        ctx.amt_result.market_structure = "BALANCE"
        ctx.amt_result.structure_confidence = 0.8
        ctx.amt_result.balance_ratio = 0.6
        ctx.amt_result.ib_high = 101.0
        ctx.amt_result.ib_low = 99.0
        ctx.amt_result.ib_complete = True
        ctx.amt_result.prior_poc = 100.5
        ctx.amt_result.prior_vah = 101.0
        ctx.amt_result.prior_val = 99.0
        ctx.amt_result.gap_type = "ABOVE"
        ctx.amt_result.opening_bias = "BULLISH"
        ctx.amt_result.acceptance_above = False
        ctx.amt_result.acceptance_below = False
        ctx.amt_result.rejection_at_high = False
        ctx.amt_result.rejection_at_low = False
        ctx.amt_result.price_velocity = 0.1
        ctx.amt_result.break_direction = ""
        ctx.amt_result.break_type = ""
        ctx.amt_result.break_level = 0.0
        ctx.amt_result.poc_signal = ""
        ctx.amt_result.poc_vs_price = 0.0
        ctx.amt_result.lvn_play = None
        ctx.amt_result.cvd_divergence = ""

        return ctx

    def _make_session_info(self, allow_trend=True):
        """Create a mock SessionInfo."""
        si = MagicMock()
        si.session = "NSE_PRIMARY"
        si.allow_trend = allow_trend
        si.allow_entry = True
        si.opening_relation = "ABOVE_PRIOR_VAH"
        return si

    def test_build_market_data_ai_basic(self):
        """Should return dict with basic market data."""
        ctx = self._make_context()
        si = self._make_session_info()
        result = PromptEngineeringService.build_market_data_ai(ctx, si)
        assert result["ltp"] == 100.0
        assert result["poc"] == 100.0
        assert result["vah"] == 101.0
        assert result["val"] == 99.0
        assert "market_state" in result
        assert "aggression" in result

    def test_build_market_data_ai_profile_shape(self):
        """Should include profile shape description."""
        ctx = self._make_context(profile_shape="P")
        si = self._make_session_info()
        result = PromptEngineeringService.build_market_data_ai(ctx, si)
        assert "P-shape" in result["profile_shape"]

    def test_build_market_data_ai_strategy_hint_trending(self):
        """Should include trending strategy hint for IMBALANCED."""
        ctx = self._make_context(market_state="IMBALANCED")
        si = self._make_session_info(allow_trend=True)
        result = PromptEngineeringService.build_market_data_ai(ctx, si)
        assert "trending" in result["strategy_hint"].lower()

    def test_build_market_data_ai_strategy_hint_balanced(self):
        """Should include balanced strategy hint for BALANCED."""
        ctx = self._make_context(market_state="BALANCED")
        si = self._make_session_info()
        result = PromptEngineeringService.build_market_data_ai(ctx, si)
        assert "balanced" in result["strategy_hint"].lower()

    def test_build_session_context_for_llm(self):
        """Should build session context string."""
        si = self._make_session_info()
        result = PromptEngineeringService.build_session_context_for_llm(si)
        assert "Trend setups allowed" in result

    def test_build_session_context_no_entry(self):
        """Should warn when entry not allowed."""
        si = self._make_session_info()
        si.allow_entry = False
        result = PromptEngineeringService.build_session_context_for_llm(si)
        assert "WARNING" in result

    def test_build_episodic_memory_empty(self):
        """Should return empty string when no storage."""
        result = PromptEngineeringService.build_episodic_memory(None, "CRUDEOIL")
        assert result == ""

    def test_build_episodic_memory_with_trades(self):
        """Should build memory string from trades."""
        storage = MagicMock()
        storage.get_recent_trades.return_value = [
            {"side": "LONG", "pnl": 500, "reason": "TARGET", "time": "2026-03-20T10:00:00"},
            {"side": "SHORT", "pnl": -200, "reason": "SL", "time": "2026-03-20T09:30:00"},
        ]
        result = PromptEngineeringService.build_episodic_memory(storage, "CRUDEOIL")
        assert "LONG" in result
        assert "SHORT" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])