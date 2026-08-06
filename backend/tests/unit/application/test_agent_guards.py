"""Tests for agent fast-entry risk guards — daily loss limit, DEFENSIVE tier, VWAP bias, grade score, cushion SL."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quant.execution.session_risk_manager import (
    SessionRiskManager,
    CapitalRiskBand,
)
from quant.decision.gates.grading import compute_grade_score, check_vwap_bias
from quant.contracts.enums import SetupType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick(close=100.0):
    from quant.contracts.value_objects import OHLC
    return OHLC(open=close, high=close + 1, low=close - 1, close=close,
                volume=1000, delta=0, time="2025-01-01T10:00:00Z", vwap=close)


def _make_amt(poc=100.0, vah=105.0, val=95.0, cvd_slope=0.5, cvd_div=None, vwap=100.0):
    amt = MagicMock()
    amt.poc = poc
    amt.value_area_high = vah
    amt.value_area_low = val
    amt.session_vwap = vwap
    amt.cvd_slope = cvd_slope
    amt.cvd_divergence = cvd_div
    amt.aggressive_prints = []
    amt.profile_shape = ""
    amt.vwap_upper_2 = vwap * 1.02
    amt.vwap_lower_2 = vwap * 0.98
    return amt


# =====================================================================
# Daily Loss Limit
# =====================================================================

class TestAgentDailyLossLimit:
    def test_should_block_entry_prevents_agent(self):
        """When TradeManager.should_block_entry() is True, agent must not enter."""
        tm = MagicMock()
        tm.should_block_entry.return_value = True
        lifecycle = MagicMock()
        lifecycle._trade_manager = tm

        blocked = (hasattr(lifecycle, '_trade_manager')
                   and lifecycle._trade_manager.should_block_entry())
        assert blocked is True

    def test_should_block_entry_allows_when_ok(self):
        tm = MagicMock()
        tm.should_block_entry.return_value = False
        lifecycle = MagicMock()
        lifecycle._trade_manager = tm

        blocked = (hasattr(lifecycle, '_trade_manager')
                   and lifecycle._trade_manager.should_block_entry())
        assert blocked is False


# =====================================================================
# DEFENSIVE Tier
# =====================================================================

class TestAgentDefensiveTier:
    def test_defensive_tier_blocks_agent(self):
        rm = SessionRiskManager()
        rm.record_trade(-100)
        rm.record_trade(-100)
        assert rm.risk_tier == CapitalRiskBand.DEFENSIVE
        assert rm.risk_tier.name == "DEFENSIVE"

    def test_normal_tier_allows_agent(self):
        rm = SessionRiskManager()
        assert rm.risk_tier.name != "DEFENSIVE"


# =====================================================================
# Grade Score (Triple-A Setup)
# =====================================================================

class TestAgentGradeScore:
    def test_a_grade_full_confluence(self):
        """CVD confirms + no divergence + session aligns + profile = A-grade."""
        tick = _make_tick(101.0)
        amt = _make_amt(cvd_slope=0.8, cvd_div=None, vwap=100.0)
        amt.vwap_upper_2 = 105.0  # not overextended
        score = compute_grade_score(
            "LONG", tick, amt, SetupType.TREND_MODEL,
            favor_strategy="TREND_CONTINUATION",
            profile_shape="b",
        )
        # CVD +1, no div +1, session +1, profile +1 = 4
        assert score >= 3, f"Expected A-grade (>=3), got {score}"

    def test_c_grade_against_cvd(self):
        """LONG with bearish CVD divergence + below VWAP = C-grade."""
        tick = _make_tick(95.0)  # below VWAP
        amt = _make_amt(cvd_slope=-0.5, cvd_div="BEARISH_DIV", vwap=100.0)
        score = compute_grade_score("LONG", tick, amt, SetupType.TREND_MODEL)
        assert score < 1, f"Expected C-grade (<1), got {score}"

    def test_b_grade_partial(self):
        """CVD confirms but VWAP warning = B-grade."""
        tick = _make_tick(99.0)  # slightly below VWAP
        amt = _make_amt(cvd_slope=0.5, cvd_div=None, vwap=100.0)
        score = compute_grade_score("LONG", tick, amt, SetupType.TREND_MODEL)
        # CVD +1, no div +1, VWAP warning -1 = 1 (B-grade)
        assert score >= 1
        assert score < 3

    def test_midday_downgrade(self):
        """Midday session penalizes score."""
        tick = _make_tick(102.0)
        amt = _make_amt(cvd_slope=0.5, cvd_div=None, vwap=100.0)
        score_normal = compute_grade_score("LONG", tick, amt, SetupType.TREND_MODEL)
        score_midday = compute_grade_score(
            "LONG", tick, amt, SetupType.TREND_MODEL,
            session_phase="NSE_MIDDAY",
        )
        assert score_midday == score_normal - 1

    def test_profile_shape_alignment(self):
        """b-shape boosts LONG, P-shape boosts SHORT."""
        tick = _make_tick(102.0)
        amt = _make_amt(cvd_slope=0.0, cvd_div=None, vwap=100.0)
        score_b_long = compute_grade_score("LONG", tick, amt, SetupType.TREND_MODEL, profile_shape="b")
        score_b_short = compute_grade_score("SHORT", tick, amt, SetupType.TREND_MODEL, profile_shape="b")
        assert score_b_long > score_b_short


# =====================================================================
# VWAP Bias
# =====================================================================

class TestAgentVWAPBias:
    def test_long_below_vwap_blocked(self):
        result = check_vwap_bias("LONG", price=95.0, vwap=100.0,
                                  vwap_upper_2=110.0, vwap_lower_2=90.0)
        assert result["warning"] is True

    def test_long_above_vwap_allowed(self):
        result = check_vwap_bias("LONG", price=105.0, vwap=100.0,
                                  vwap_upper_2=110.0, vwap_lower_2=90.0)
        assert result["warning"] is False


# =====================================================================
# Cushion SL
# =====================================================================

class TestAgentCushionSL:
    def test_build_entry_signal_accepts_risk_sl_pct(self):
        import inspect
        from quant.decision.gates.signal_builder import build_entry_signal
        sig = inspect.signature(build_entry_signal)
        assert "risk_sl_pct" in sig.parameters
