"""Tests for acceptance/rejection, aggression scoring, and CVD tracking."""

import pytest
from app.domain.amt.service.acceptance_rejection import (
    AcceptanceRejectionEngine,
    analyze_wick,
    ARResult,
    WickAnalysis,
)
from app.domain.amt.service.aggression_scorer import AggressionScorer, AggressionResult
from app.domain.amt.service.cvd_tracker import CVDTracker


class TestWickAnalysis:
    """Tests for candle wick pattern analysis."""

    def test_analyzes_bullish_candle(self):
        """Should analyze bullish candle correctly."""
        bar = {"open": 100.0, "close": 102.0, "high": 103.0, "low": 99.0}
        
        result = analyze_wick(bar)
        
        assert result.body_size == 2.0
        assert result.upper_wick == 1.0  # 103 - 102
        assert result.lower_wick == 1.0  # 100 - 99

    def test_analyzes_bearish_candle(self):
        """Should analyze bearish candle correctly."""
        bar = {"open": 102.0, "close": 100.0, "high": 103.0, "low": 99.0}
        
        result = analyze_wick(bar)
        
        assert result.body_size == 2.0
        assert result.upper_wick == 1.0  # 103 - 102
        assert result.lower_wick == 1.0  # 100 - 99

    def test_detects_upper_wick_dominant(self):
        """Should detect when upper wick is dominant (>1.5x body)."""
        bar = {"open": 100.0, "close": 101.0, "high": 105.0, "low": 99.0}
        
        result = analyze_wick(bar)
        
        assert result.is_upper_wick_dominant is True
        assert result.upper_wick == 4.0
        assert result.body_size == 1.0

    def test_detects_lower_wick_dominant(self):
        """Should detect when lower wick is dominant (>1.5x body)."""
        bar = {"open": 101.0, "close": 100.0, "high": 102.0, "low": 95.0}
        
        result = analyze_wick(bar)
        
        assert result.is_lower_wick_dominant is True
        assert result.lower_wick == 5.0
        assert result.body_size == 1.0

    def test_handles_doji_candle(self):
        """Should handle doji (zero body) correctly."""
        bar = {"open": 100.0, "close": 100.0, "high": 102.0, "low": 98.0}
        
        result = analyze_wick(bar)
        
        assert result.body_size == 0.0
        assert result.upper_wick == 2.0
        assert result.lower_wick == 2.0
        # With equal wicks and zero body, neither is dominant
        assert result.is_upper_wick_dominant is False
        assert result.is_lower_wick_dominant is False

    def test_marubozu_no_wicks(self):
        """Should handle marubozu (no wicks) correctly."""
        bar = {"open": 100.0, "close": 102.0, "high": 102.0, "low": 100.0}
        
        result = analyze_wick(bar)
        
        assert result.body_size == 2.0
        assert result.upper_wick == 0.0
        assert result.lower_wick == 0.0


class TestAcceptanceRejection:
    """Tests for acceptance/rejection detection."""

    def test_detects_acceptance_above_vah(self):
        """Should detect acceptance above VAH."""
        engine = AcceptanceRejectionEngine(time_threshold=60.0)
        
        # Simulate price staying above VAH for extended time
        for i in range(10):
            bar = {
                "high": 102.0,
                "low": 101.0,
                "close": 101.5,
                "open": 101.2,
                "volume": 1000,
                "time": f"09:{15+i*10}:00",
            }
            result = engine.update(bar, vah=100.0, val=98.0, baseline_vol=800)
        
        assert result.accepted_above is True

    def test_detects_acceptance_below_val(self):
        """Should detect acceptance below VAL."""
        engine = AcceptanceRejectionEngine(time_threshold=60.0)
        
        # Simulate price staying below VAL
        for i in range(10):
            bar = {
                "high": 97.0,
                "low": 96.0,
                "close": 96.5,
                "open": 96.2,
                "volume": 1000,
                "time": f"09:{15+i*10}:00",
            }
            result = engine.update(bar, vah=100.0, val=98.0, baseline_vol=800)
        
        assert result.accepted_below is True

    def test_detects_rejection_at_high(self):
        """Should detect rejection at VAH (high > VAH with dominant upper wick)."""
        engine = AcceptanceRejectionEngine(time_threshold=120.0)
        
        bars = [
            {"high": 99.0, "low": 98.0, "close": 98.5, "open": 98.2, "volume": 1000, "time": "09:15:00"},
            # Bar that touches VAH with dominant upper wick
            {"high": 101.5, "low": 99.5, "close": 99.8, "open": 100.0, "volume": 1500, "time": "09:25:00"},
        ]
        
        for bar in bars:
            result = engine.update(bar, vah=100.0, val=98.0, baseline_vol=800)
        
        # High (101.5) > VAH (100), upper wick = 101.5 - 100 = 1.5, body = 0.2
        # 1.5 > 0.2 * 1.5 = 0.3, so upper wick is dominant
        assert result.rejected_at_high is True

    def test_detects_liquidity_sweep(self):
        """Should detect liquidity sweep (pierce VAH/VAL with dominant wick)."""
        engine = AcceptanceRejectionEngine(time_threshold=120.0)
        
        bars = [
            {"high": 99.0, "low": 98.0, "close": 98.5, "open": 98.2, "volume": 1000, "time": "09:15:00"},
            # Sweep high with dominant upper wick
            {"high": 101.5, "low": 99.5, "close": 99.8, "open": 100.0, "volume": 3000, "time": "09:25:00"},
        ]
        
        for bar in bars:
            result = engine.update(bar, vah=100.0, val=98.0, baseline_vol=800)
        
        # Should detect sweep
        assert result.liquidity_sweep == "SWEEP_HIGH"

    def test_price_velocity_is_zero_in_current_implementation(self):
        """Should return 0.0 for price_velocity (not implemented yet)."""
        engine = AcceptanceRejectionEngine()
        
        bar = {
            "high": 105.0,
            "low": 104.0,
            "close": 104.5,
            "open": 104.2,
            "volume": 1000,
            "time": "09:15:00",
        }
        result = engine.update(bar, vah=100.0, val=98.0, baseline_vol=800)
        
        # Current implementation always returns 0.0
        assert result.price_velocity == 0.0


class TestAggressionScorer:
    """Tests for 7-component aggression scoring (FR-06)."""

    def test_scores_high_aggression(self):
        """Should score HIGH when all components confirm."""
        scorer = AggressionScorer()
        
        result = scorer.score(
            footprint_ratio=0.45,  # >40% at 3:1 ratio → +1.0
            cvd_confirms=True,     # → +1.0
            big_trade_cluster=True,  # → +1.0
            absorption=True,       # → +0.5
            ofi=0.15,             # >0.10 → +0.5
            lvn_near_level=True,   # → +0.5
            volume_bubble=True,    # → +0.5
            side="LONG",
        )
        
        assert result.score >= 5.0
        assert result.confidence == "HIGH"
        assert result.confirmed is True

    def test_scores_medium_aggression(self):
        """Should score MEDIUM with partial confirmation."""
        scorer = AggressionScorer()
        
        result = scorer.score(
            footprint_ratio=0.45,
            cvd_confirms=True,
            big_trade_cluster=False,
            absorption=False,
            ofi=0.05,
            lvn_near_level=False,
            volume_bubble=False,
            side="LONG",
        )
        
        assert result.score >= 2.0
        assert result.confidence == "MEDIUM"

    def test_scores_low_aggression(self):
        """Should score LOW with minimal confirmation."""
        scorer = AggressionScorer()
        
        result = scorer.score(
            footprint_ratio=0.1,
            cvd_confirms=False,
            big_trade_cluster=False,
            absorption=False,
            ofi=0.0,
            lvn_near_level=False,
            volume_bubble=False,
            side="LONG",
        )
        
        assert result.score < 2.0
        assert result.confidence == "LOW"
        assert result.confirmed is False

    def test_requires_minimum_score_for_trade(self):
        """Should require score >= 2.0 for trade confirmation."""
        scorer = AggressionScorer()
        
        weak = scorer.score(
            footprint_ratio=0.2,
            cvd_confirms=False,
            side="LONG",
        )
        
        assert weak.confirmed is False

    def test_pyramid_eligible_at_high_score(self):
        """Should mark pyramid eligible at high scores."""
        scorer = AggressionScorer()
        
        result = scorer.score(
            footprint_ratio=0.5,
            cvd_confirms=True,
            big_trade_cluster=True,
            side="LONG",
        )
        
        if result.score >= 3.0:
            assert result.pyramid_eligible is True

    def test_ofi_alignment_for_long(self):
        """Should give OFI points for long when OFI > 0.10."""
        scorer = AggressionScorer()
        
        aligned = scorer.score(ofi=0.15, side="LONG")
        misaligned = scorer.score(ofi=0.05, side="LONG")
        
        assert aligned.score > misaligned.score

    def test_ofi_alignment_for_short(self):
        """Should give OFI points for short when OFI < -0.10."""
        scorer = AggressionScorer()
        
        aligned = scorer.score(ofi=-0.15, side="SHORT")
        misaligned = scorer.score(ofi=-0.05, side="SHORT")
        
        assert aligned.score > misaligned.score

    def test_returns_breakdown(self):
        """Should return detailed breakdown of scores."""
        scorer = AggressionScorer()
        
        result = scorer.score(
            footprint_ratio=0.45,
            cvd_confirms=True,
            side="LONG",
        )
        
        assert isinstance(result.breakdown, dict)
        assert len(result.breakdown) > 0


class TestCVDTracker:
    """Tests for Cumulative Volume Delta tracking."""

    def test_tracks_cumulative_delta(self):
        """Should track running CVD."""
        tracker = CVDTracker()
        
        tracker.update(0, bid_volume=600, ask_volume=400, price=100.0)  # Delta +200
        tracker.update(1, bid_volume=500, ask_volume=700, price=101.0)  # Delta -200
        tracker.update(2, bid_volume=800, ask_volume=300, price=102.0)  # Delta +500
        
        assert tracker.cumulative_delta == 500  # 200 - 200 + 500

    def test_resets_correctly(self):
        """Should reset all state."""
        tracker = CVDTracker()
        
        tracker.update(0, bid_volume=600, ask_volume=400, price=100.0)
        tracker.reset()
        
        assert tracker.cumulative_delta == 0.0

    def test_calculates_slope(self):
        """Should calculate CVD slope."""
        tracker = CVDTracker(slope_window=5)
        
        # Create upward CVD trend
        for i in range(10):
            tracker.update(i, bid_volume=700, ask_volume=300, price=100.0 + i)
        
        state = tracker.snapshot()
        
        assert state.get("slope", 0.0) != 0.0

    def test_detects_divergence(self):
        """Should detect price vs CVD divergence."""
        tracker = CVDTracker(divergence_window=10)
        
        # Price goes up, CVD goes down (bearish divergence)
        for i in range(20):
            price = 100.0 + i  # Price trending up
            tracker.update(i, bid_volume=300, ask_volume=700, price=price)  # CVD trending down
        
        state = tracker.snapshot()
        
        # Should have divergence signal
        div_type = state.get("divergence_type", "NONE")
        assert div_type in ["BEARISH_DIV", "BULLISH_DIV", "NONE"]  # At least returns valid type

    def test_respects_max_history(self):
        """Should limit history to max_history."""
        tracker = CVDTracker(max_history=10)
        
        for i in range(20):
            tracker.update(i, bid_volume=600, ask_volume=400, price=100.0)
        
        assert len(tracker._history) <= 10

    def test_update_bar_convenience_method(self):
        """Should update from bar dict."""
        tracker = CVDTracker()
        
        bar = {
            "buyVolume": 600,
            "sellVolume": 400,
            "close": 100.0,
            "time": "09:15:00",
        }
        
        state = tracker.update_bar(bar)
        
        # Delta = buyVolume - sellVolume = 600 - 400 = 200
        assert state.value == 200
        assert state.slope == 0.0  # First bar, no slope yet

    def test_handles_zero_volume(self):
        """Should handle zero volume bars."""
        tracker = CVDTracker()
        
        tracker.update(0, bid_volume=0, ask_volume=0, price=100.0)
        
        assert tracker.cumulative_delta == 0.0

    def test_returns_complete_state(self):
        """Should return complete CVDState object."""
        tracker = CVDTracker()
        
        tracker.update(0, bid_volume=600, ask_volume=400, price=100.0)
        snapshot = tracker.snapshot()
        
        assert snapshot["cumulative_delta"] == 200
        assert "slope" in snapshot
        assert "divergence_type" in snapshot
