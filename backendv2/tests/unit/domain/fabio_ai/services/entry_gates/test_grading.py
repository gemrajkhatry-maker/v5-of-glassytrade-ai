"""Tests for grading entry gate functions."""
import pytest
from decimal import Decimal

from app.domain.fabio_ai.services.entry_gates.grading import (
    check_vwap_bias,
    check_imbalance_alignment,
    compute_grade_score,
)
from app.domain.trading.model.value_objects import OHLC, AMTResult, FootprintCandle, FootprintLevel
from app.domain.trading.model.enums import SetupType


class TestCheckVWAPBias:
    """Tests for check_vwap_bias() function."""

    def test_long_warning_below_vwap(self):
        """LONG direction triggers warning when price is below VWAP."""
        result = check_vwap_bias(
            direction="LONG", price=98.0, vwap=100.0,
            vwap_upper_2=105.0, vwap_lower_2=95.0
        )
        assert result["warning"] is True
        assert result["overextended"] is False

    def test_long_overextended_above_upper_band(self):
        """LONG direction triggers overextended when price >= VWAP upper 2 band."""
        result = check_vwap_bias(
            direction="LONG", price=105.0, vwap=100.0,
            vwap_upper_2=105.0, vwap_lower_2=95.0
        )
        assert result["warning"] is False
        assert result["overextended"] is True

    def test_long_no_warning_normal_position(self):
        """LONG with price above VWAP but below upper band has no flags."""
        result = check_vwap_bias(
            direction="LONG", price=102.0, vwap=100.0,
            vwap_upper_2=105.0, vwap_lower_2=95.0
        )
        assert result["warning"] is False
        assert result["overextended"] is False

    def test_short_warning_above_vwap(self):
        """SHORT direction triggers warning when price is above VWAP."""
        result = check_vwap_bias(
            direction="SHORT", price=102.0, vwap=100.0,
            vwap_upper_2=105.0, vwap_lower_2=95.0
        )
        assert result["warning"] is True
        assert result["overextended"] is False

    def test_short_overextended_below_lower_band(self):
        """SHORT direction triggers overextended when price <= VWAP lower 2 band."""
        result = check_vwap_bias(
            direction="SHORT", price=95.0, vwap=100.0,
            vwap_upper_2=105.0, vwap_lower_2=95.0
        )
        assert result["warning"] is False
        assert result["overextended"] is True

    def test_short_no_warning_normal_position(self):
        """SHORT with price below VWAP but above lower band has no flags."""
        result = check_vwap_bias(
            direction="SHORT", price=98.0, vwap=100.0,
            vwap_upper_2=105.0, vwap_lower_2=95.0
        )
        assert result["warning"] is False
        assert result["overextended"] is False

    def test_no_vwap_returns_no_flags(self):
        """Zero or negative VWAP returns no warning or overextended."""
        result = check_vwap_bias(
            direction="LONG", price=100.0, vwap=0.0,
            vwap_upper_2=105.0, vwap_lower_2=95.0
        )
        assert result["warning"] is False
        assert result["overextended"] is False

    def test_zero_upper_band_does_not_trigger_overextended(self):
        """Zero upper band does not trigger overextended even if price is high."""
        result = check_vwap_bias(
            direction="LONG", price=200.0, vwap=100.0,
            vwap_upper_2=0.0, vwap_lower_2=95.0
        )
        assert result["warning"] is False
        assert result["overextended"] is False


class TestCheckImbalanceAlignment:
    """Tests for check_imbalance_alignment() function."""

    def test_empty_imbalances_returns_zero(self):
        """Empty imbalance list returns 0."""
        assert check_imbalance_alignment("LONG", []) == 0

    def test_aligned_buy_imbalances_for_long(self):
        """BUY imbalances aligned with LONG direction return 1."""
        imbalances = [
            type("Level", (), {"direction": "BUY", "price": 100.0})(),
            type("Level", (), {"direction": "BUY", "price": 101.0})(),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == 1

    def test_aligned_sell_imbalances_for_short(self):
        """SELL imbalances aligned with SHORT direction return 1."""
        imbalances = [
            type("Level", (), {"direction": "SELL", "price": 100.0})(),
            type("Level", (), {"direction": "SELL", "price": 99.0})(),
        ]
        assert check_imbalance_alignment("SHORT", imbalances) == 1

    def test_opposing_imbalances_return_negative(self):
        """Opposing imbalances return -2."""
        imbalances = [
            type("Level", (), {"direction": "SELL", "price": 100.0})(),
            type("Level", (), {"direction": "SELL", "price": 99.0})(),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == -2

    def test_mixed_imbalances_majority_aligned(self):
        """Mixed imbalances with majority aligned return 1."""
        imbalances = [
            type("Level", (), {"direction": "BUY", "price": 100.0})(),
            type("Level", (), {"direction": "BUY", "price": 101.0})(),
            type("Level", (), {"direction": "SELL", "price": 99.0})(),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == 1

    def test_mixed_imbalances_majority_opposing(self):
        """Mixed imbalances with majority opposing return -2."""
        imbalances = [
            type("Level", (), {"direction": "SELL", "price": 100.0})(),
            type("Level", (), {"direction": "SELL", "price": 99.0})(),
            type("Level", (), {"direction": "BUY", "price": 101.0})(),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == -2

    def test_equal_aligned_and_opposing_returns_zero(self):
        """Equal aligned and opposing imbalances return 0."""
        imbalances = [
            type("Level", (), {"direction": "BUY", "price": 100.0})(),
            type("Level", (), {"direction": "SELL", "price": 99.0})(),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == 0


class TestComputeGradeScore:
    """Tests for compute_grade_score() function."""

    def _make_tick(self, close: float = 100.0) -> OHLC:
        return OHLC.create(
            time="2024-01-01T09:15:00",
            open=99.0, high=101.0, low=98.0,
            close=close, volume=1000.0
        )

    def _make_amt(self, **overrides) -> AMTResult:
        return AMTResult(**overrides)

    # --- CVD hard-kill tests ---

    def test_cvd_hard_kill_long_extreme_bearish(self):
        """LONG with extreme bearish CVD slope returns -10 (hard-kill)."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=-60.0)
        assert compute_grade_score("LONG", tick, amt) == -10

    def test_cvd_hard_kill_short_extreme_bullish(self):
        """SHORT with extreme bullish CVD slope returns -10 (hard-kill)."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=60.0)
        assert compute_grade_score("SHORT", tick, amt) == -10

    # --- CVD slope bonus tests ---

    def test_cvd_slope_bonus_long_aligned(self):
        """LONG with positive CVD slope gets +1 bonus."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.5)
        score = compute_grade_score("LONG", tick, amt)
        assert score >= 1

    def test_cvd_slope_bonus_short_aligned(self):
        """SHORT with negative CVD slope gets +1 bonus."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=-0.5)
        score = compute_grade_score("SHORT", tick, amt)
        assert score >= 1

    # --- CVD divergence penalty tests ---

    def test_cvd_divergence_penalty_long_bearish(self):
        """LONG with bearish CVD divergence gets -2 penalty."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.1, cvd_divergence="BEARISH_DIV")
        # Base score: 0 (no slope bonus, slope > -0.3), divergence -2 = -2
        score = compute_grade_score("LONG", tick, amt)
        assert score <= -1

    def test_cvd_divergence_penalty_short_bullish(self):
        """SHORT with bullish CVD divergence gets -2 penalty."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=-0.1, cvd_divergence="BULLISH_DIV")
        score = compute_grade_score("SHORT", tick, amt)
        assert score <= -1

    def test_no_cvd_divergence_gives_bonus(self):
        """No CVD divergence gives +1 bonus."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.1, cvd_divergence="")
        score = compute_grade_score("LONG", tick, amt)
        assert score >= 1

    # --- Strategy alignment bonus tests ---

    def test_strategy_alignment_mean_reversion(self):
        """MEAN_REVERSION strategy + MEAN_REVERSION setup gives +1 bonus."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.5)
        score = compute_grade_score(
            "LONG", tick, amt,
            setup_type=SetupType.MEAN_REVERSION,
            favor_strategy="MEAN_REVERSION"
        )
        # CVD slope +1, no divergence +1, strategy +1 = at least 3
        assert score >= 3

    # --- Profile shape bonus/penalty tests ---

    def test_profile_shape_bonus_b_shape_long(self):
        """b-shape profile + LONG direction gives +1 bonus."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.5)
        score = compute_grade_score("LONG", tick, amt, profile_shape="b-shape")
        # CVD slope +1, no divergence +1, shape +1 = at least 3
        assert score >= 3

    def test_profile_shape_bonus_p_shape_short(self):
        """P-shape profile + SHORT direction gives +1 bonus."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=-0.5)
        score = compute_grade_score("SHORT", tick, amt, profile_shape="P-shape")
        # CVD slope +1, no divergence +1, shape +1 = at least 3
        assert score >= 3

    def test_profile_shape_penalty_b_shape_short(self):
        """b-shape profile + SHORT direction gives -1 penalty."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=-0.1)
        # Compute score with shape vs without shape
        score_with_shape = compute_grade_score("SHORT", tick, amt, profile_shape="b-shape")
        score_without_shape = compute_grade_score("SHORT", tick, amt, profile_shape="")
        assert score_with_shape < score_without_shape

    def test_profile_shape_penalty_p_shape_long(self):
        """P-shape profile + LONG direction gives -1 penalty."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.1)
        score_with_shape = compute_grade_score("LONG", tick, amt, profile_shape="P-shape")
        score_without_shape = compute_grade_score("LONG", tick, amt, profile_shape="")
        assert score_with_shape < score_without_shape

    # --- VWAP overextended penalty tests ---

    def test_vwap_overextended_penalty_long(self):
        """LONG with price above VWAP upper 2 band gets -2 penalty."""
        tick = self._make_tick(close=110.0)
        amt = self._make_amt(
            cvd_slope=0.1,
            session_vwap=100.0,
            vwap_upper_2=105.0,
            vwap_lower_2=95.0
        )
        # CVD slope +1, no divergence +1, VWAP overextended -2 = 0
        score = compute_grade_score("LONG", tick, amt)
        assert score <= 1

    def test_vwap_warning_penalty_long(self):
        """LONG with price below VWAP gets -1 penalty."""
        tick = self._make_tick(close=98.0)
        amt = self._make_amt(
            cvd_slope=0.1,
            session_vwap=100.0,
            vwap_upper_2=105.0,
            vwap_lower_2=95.0
        )
        # CVD slope +1, no divergence +1, VWAP warning -1 = 1
        score = compute_grade_score("LONG", tick, amt)
        assert score <= 2

    # --- Footprint stacked imbalance scoring tests ---

    def test_footprint_stacked_imbalance_aligned(self):
        """Stacked imbalances aligned with direction add to score."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.5)
        # Create levels with direction attribute for imbalance alignment check
        buy_level = type("Level", (), {"price": 100.0, "bid": 10.0, "ask": 50.0, "delta": 40.0, "stacked": True, "direction": "BUY", "imbalance": False})()
        buy_level2 = type("Level", (), {"price": 101.0, "bid": 10.0, "ask": 50.0, "delta": 40.0, "stacked": True, "direction": "BUY", "imbalance": False})()
        footprint = FootprintCandle(
            time="2024-01-01T09:15:00",
            levels=(buy_level, buy_level2)
        )
        score = compute_grade_score("LONG", tick, amt, footprint_candle=footprint)
        # CVD slope +1, no divergence +1, imbalance aligned +1 = at least 3
        assert score >= 3

    def test_footprint_stacked_imbalance_mixed_delta_penalty(self):
        """Stacked imbalances with both buy and sell delta get -3 penalty."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.5)
        # Mixed: one BUY, one SELL direction
        buy_level = type("Level", (), {"price": 100.0, "bid": 10.0, "ask": 50.0, "delta": 40.0, "stacked": True, "direction": "BUY", "imbalance": False})()
        sell_level = type("Level", (), {"price": 101.0, "bid": 50.0, "ask": 10.0, "delta": -40.0, "stacked": True, "direction": "SELL", "imbalance": False})()
        footprint = FootprintCandle(
            time="2024-01-01T09:15:00",
            levels=(buy_level, sell_level)
        )
        # Has both buy (delta>0) and sell (delta<0) => -3 penalty
        score_with_mixed = compute_grade_score("LONG", tick, amt, footprint_candle=footprint)
        # Aligned: both BUY direction
        buy_level2 = type("Level", (), {"price": 101.0, "bid": 10.0, "ask": 50.0, "delta": 40.0, "stacked": True, "direction": "BUY", "imbalance": False})()
        footprint_aligned = FootprintCandle(
            time="2024-01-01T09:15:00",
            levels=(buy_level, buy_level2)
        )
        score_aligned = compute_grade_score("LONG", tick, amt, footprint_candle=footprint_aligned)
        assert score_with_mixed < score_aligned

    # --- NSE_MIDDAY session penalty tests ---

    def test_nse_midday_session_penalty(self):
        """NSE_MIDDAY session phase gets -1 penalty."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=0.1)
        score_midday = compute_grade_score("LONG", tick, amt, session_phase="NSE_MIDDAY")
        score_normal = compute_grade_score("LONG", tick, amt, session_phase="NSE_OPEN")
        assert score_midday < score_normal

    # --- Mixed high-score scenario ---

    def test_mixed_high_score_scenario(self):
        """Good CVD + good shape + good VWAP alignment = high score."""
        tick = self._make_tick(close=102.0)
        amt = self._make_amt(
            cvd_slope=0.5,
            cvd_divergence="",
            session_vwap=100.0,
            vwap_upper_2=110.0,
            vwap_lower_2=90.0
        )
        score = compute_grade_score(
            "LONG", tick, amt,
            setup_type=SetupType.MEAN_REVERSION,
            favor_strategy="MEAN_REVERSION",
            profile_shape="b-shape",
            session_phase="NSE_OPEN"
        )
        # CVD slope +1, no divergence +1, strategy +1, shape +1, VWAP ok = at least 4
        assert score >= 4

    def test_neutral_scenario_zero_cvd(self):
        """Zero CVD slope with no other factors gives minimal score."""
        tick = self._make_tick()
        amt = self._make_amt(
            cvd_slope=0.0,
            cvd_divergence="",
            session_vwap=100.0,
            vwap_upper_2=110.0,
            vwap_lower_2=90.0
        )
        score = compute_grade_score("LONG", tick, amt)
        # No slope bonus, no divergence +1, VWAP ok = 1
        assert score >= 1

    def test_cvd_slope_below_hard_block_threshold(self):
        """CVD slope just below hard block threshold does not hard-kill."""
        tick = self._make_tick()
        amt = self._make_amt(cvd_slope=-49.0)
        # -49 > -50, so no hard-kill
        score = compute_grade_score("LONG", tick, amt)
        assert score > -10
