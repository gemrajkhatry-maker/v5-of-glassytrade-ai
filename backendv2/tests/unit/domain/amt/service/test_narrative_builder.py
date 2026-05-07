"""Tests for narrative_builder.py — narrative construction for LLM prompts."""
from __future__ import annotations

from app.domain.amt.service.narrative_builder import (
    _build_core_amt_narrative,
    _build_narrative_market_state,
    _build_narrative_order_flow,
    _build_narrative_session_context,
)


class TestBuildNarrativeSessionContext:
    """Tests for _build_narrative_session_context()."""

    def test_includes_session_name(self):
        """Session name is included in output."""
        data = {"session_name": "NSE_EQUITY"}
        result = _build_narrative_session_context(data)
        assert any("SESSION: NSE_EQUITY" in part for part in result)

    def test_includes_trend_continuation_strategy(self):
        """TREND_CONTINUATION maps to TREND CONTINUATION narrative."""
        data = {"favor_strategy": "TREND_CONTINUATION"}
        result = _build_narrative_session_context(data)
        assert any("TREND CONTINUATION" in part for part in result)

    def test_includes_mean_reversion_strategy(self):
        """Non-TREND_CONTINUATION strategy maps to MEAN REVERSION narrative."""
        data = {"favor_strategy": "MEAN_REVERSION"}
        result = _build_narrative_session_context(data)
        assert any("MEAN REVERSION" in part for part in result)

    def test_skips_neutral_strategy(self):
        """NEUTRAL strategy is not included."""
        data = {"favor_strategy": "NEUTRAL"}
        result = _build_narrative_session_context(data)
        assert not any("Session favors" in part for part in result)

    def test_includes_prior_levels_when_all_present(self):
        """Prior POC/VAH/VAL included when all > 0."""
        data = {"prior_poc": 100.0, "prior_vah": 105.0, "prior_val": 95.0}
        result = _build_narrative_session_context(data)
        assert any("POC 100" in part for part in result)
        assert any("VAH 105" in part for part in result)
        assert any("VAL 95" in part for part in result)

    def test_fallback_when_prior_levels_missing(self):
        """Shows fallback message when prior levels are zero."""
        data = {"prior_poc": 0, "prior_vah": 0, "prior_val": 0}
        result = _build_narrative_session_context(data)
        assert any("No historical data" in part for part in result)

    def test_includes_gap_type(self):
        """Gap type is included when present."""
        data = {"gap_type": "OUTSIDE_VA"}
        result = _build_narrative_session_context(data)
        assert any("Gap: OUTSIDE_VA" in part for part in result)

    def test_includes_opening_bias_when_not_neutral(self):
        """Opening bias included when not NEUTRAL or IN_BALANCE."""
        data = {"opening_bias": "BULLISH"}
        result = _build_narrative_session_context(data)
        assert any("Opening bias: BULLISH" in part for part in result)

    def test_skips_neutral_opening_bias(self):
        """NEUTRAL opening bias is not included."""
        data = {"opening_bias": "NEUTRAL"}
        result = _build_narrative_session_context(data)
        assert not any("Opening bias" in part for part in result)

    def test_includes_complete_ib(self):
        """Complete IB included with status when IB levels valid."""
        data = {"ib_high": 105.0, "ib_low": 95.0, "ib_complete": True}
        result = _build_narrative_session_context(data)
        assert any("complete" in part for part in result)
        assert any("95.00-105.00" in part for part in result)

    def test_includes_forming_ib(self):
        """Forming IB included when not complete."""
        data = {"ib_high": 105.0, "ib_low": 95.0, "ib_complete": False}
        result = _build_narrative_session_context(data)
        assert any("forming" in part for part in result)


class TestBuildNarrativeMarketState:
    """Tests for _build_narrative_market_state()."""

    def test_balanced_market_mean_reversion(self):
        """BALANCED market produces mean reversion narrative."""
        data = {"market_state": "BALANCED", "ltp": 100.0, "poc": 100.0, "vah": 105.0, "val": 95.0}
        result = _build_narrative_market_state(data)
        assert any("BALANCED" in part for part in result)
        assert any("MEAN REVERSION" in part for part in result)
        assert any("snap back to POC" in part for part in result)

    def test_imbalanced_market_trend_continuation(self):
        """IMBALANCED market produces trend continuation narrative."""
        data = {"market_state": "IMBALANCED", "ltp": 110.0, "poc": 100.0, "vah": 105.0, "val": 95.0}
        result = _build_narrative_market_state(data)
        assert any("IMBALANCED" in part for part in result)
        assert any("TREND CONTINUATION" in part for part in result)
        assert any("continuation" in part for part in result)

    def test_includes_price_and_va_range(self):
        """Market state narrative includes price and VA range."""
        data = {"market_state": "BALANCED", "ltp": 100.0, "vah": 105.0, "val": 95.0}
        result = _build_narrative_market_state(data)
        # The function returns list of strings; check combined content
        assert len(result) >= 1
        assert any("BALANCED" in part for part in result)


class TestBuildNarrativeOrderFlow:
    """Tests for _build_narrative_order_flow()."""

    def test_positive_delta_buying_pressure(self):
        """Positive delta produces buying pressure narrative."""
        data = {"delta": 150.0, "cvd_slope": 0.5}
        result = _build_narrative_order_flow(data)
        assert any("+150" in part for part in result)
        assert any("buying pressure" in part for part in result)

    def test_negative_delta_selling_pressure(self):
        """Negative delta produces selling pressure narrative."""
        data = {"delta": -200.0}
        result = _build_narrative_order_flow(data)
        assert any("-200" in part for part in result)
        assert any("selling pressure" in part for part in result)

    def test_positive_cvd_slope_upward(self):
        """Positive CVD slope produces upward momentum narrative."""
        data = {"cvd_slope": 0.8}
        result = _build_narrative_order_flow(data)
        assert len(result) >= 1
        assert any("upward" in part for part in result)

    def test_negative_cvd_slope_downward(self):
        """Negative CVD slope produces downward momentum narrative."""
        data = {"cvd_slope": -0.5}
        result = _build_narrative_order_flow(data)
        assert any("downward" in part for part in result)

    def test_empty_when_no_order_flow_data(self):
        """Returns empty list when no delta/cvd data."""
        data = {"delta": 0, "cvd_slope": 0}
        result = _build_narrative_order_flow(data)
        assert result == []


class TestBuildCoreAmtNarrative:
    """Tests for _build_core_amt_narrative()."""

    def test_combines_all_narrative_parts(self):
        """Core AMT narrative combines session, market state, and order flow."""
        data = {
            "session_name": "NSE",
            "favor_strategy": "TREND_CONTINUATION",
            "prior_poc": 100.0,
            "prior_vah": 105.0,
            "prior_val": 95.0,
            "market_state": "IMBALANCED",
            "ltp": 110.0,
            "poc": 100.0,
            "vah": 105.0,
            "val": 95.0,
            "delta": 50.0,
            "cvd_slope": 0.3,
        }
        result = _build_core_amt_narrative(data)
        assert "SESSION: NSE" in result
        assert "TREND CONTINUATION" in result
        assert "IMBALANCED" in result
        assert "+50" in result

    def test_handles_empty_data(self):
        """Handles empty data dict gracefully."""
        data = {}
        result = _build_core_amt_narrative(data)
        assert len(result) > 0
        assert "BALANCED" in result or "IMBALANCED" in result

    def test_returns_newline_joined_string(self):
        """Output is a single newline-joined string."""
        data = {
            "session_name": "NSE",
            "market_state": "BALANCED",
            "ltp": 100.0, "poc": 100.0, "vah": 105.0, "val": 95.0,
            "delta": 10.0,
        }
        result = _build_core_amt_narrative(data)
        assert isinstance(result, str)
        assert "\n" in result
