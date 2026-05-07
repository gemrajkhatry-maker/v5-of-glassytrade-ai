"""Tests for AcceptanceRejectionEngine — Acceptance vs rejection detection."""

from __future__ import annotations

from app.domain.amt.service.acceptance_rejection import (
    AcceptanceRejectionEngine,
    analyze_wick,
    detect_acceptance_rejection,
)


def _make_bar(open_price, high, low, close, volume=1000, time=""):
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume, "time": time}


class TestAcceptanceAbove:
    """Tests for acceptance above VA."""

    def test_acceptance_above_vah_with_time(self):
        """Price closes above VAH for enough bars => acceptance above."""
        engine = AcceptanceRejectionEngine(time_threshold=120.0)
        vah, val = 105.0, 95.0
        # 3 bars close above VAH (120/60 = 2 bars needed)
        for i in range(3):
            engine.update(_make_bar(106.0, 107.0, 105.5, 106.0), vah, val, 1000)
        result = engine.update(_make_bar(106.0, 107.0, 105.5, 106.0), vah, val, 1000)
        assert result.accepted_above is True

    def test_no_acceptance_below_vah(self):
        """Price below VAH does not trigger acceptance above."""
        engine = AcceptanceRejectionEngine(time_threshold=120.0)
        vah, val = 105.0, 95.0
        for i in range(5):
            engine.update(_make_bar(104.0, 104.5, 103.0, 104.0), vah, val, 1000)
        result = engine.update(_make_bar(104.0, 104.5, 103.0, 104.0), vah, val, 1000)
        assert result.accepted_above is False


class TestAcceptanceBelow:
    """Tests for acceptance below VA."""

    def test_acceptance_below_val_with_time(self):
        """Price closes below VAL for enough bars => acceptance below."""
        engine = AcceptanceRejectionEngine(time_threshold=120.0)
        vah, val = 105.0, 95.0
        # 3 bars close below VAL
        for i in range(3):
            engine.update(_make_bar(94.0, 94.5, 93.0, 94.0), vah, val, 1000)
        result = engine.update(_make_bar(94.0, 94.5, 93.0, 94.0), vah, val, 1000)
        assert result.accepted_below is True


class TestRejectionAtHigh:
    """Tests for rejection at high."""

    def test_rejection_at_vah_with_upper_wick(self):
        """Price tests above VAH with dominant upper wick => rejection."""
        engine = AcceptanceRejectionEngine()
        vah, val = 105.0, 95.0
        # Bar with high > VAH and large upper wick
        bar = _make_bar(open_price=104.0, high=107.0, low=103.0, close=104.5)
        result = engine.update(bar, vah, val, 1000)
        assert result.rejected_at_high is True


class TestRejectionAtLow:
    """Tests for rejection at low."""

    def test_rejection_at_val_with_lower_wick(self):
        """Price tests below VAL with dominant lower wick => rejection."""
        engine = AcceptanceRejectionEngine()
        vah, val = 105.0, 95.0
        # Bar with low < VAL and large lower wick
        bar = _make_bar(open_price=96.0, high=97.0, low=93.0, close=95.5)
        result = engine.update(bar, vah, val, 1000)
        assert result.rejected_at_low is True


class TestLiquiditySweep:
    """Tests for liquidity sweep detection."""

    def test_sweep_high_detected(self):
        """Rejection at high sets liquidity_sweep to SWEEP_HIGH."""
        engine = AcceptanceRejectionEngine()
        vah, val = 105.0, 95.0
        bar = _make_bar(open_price=104.0, high=108.0, low=103.0, close=104.5)
        result = engine.update(bar, vah, val, 1000)
        assert result.liquidity_sweep == "SWEEP_HIGH"

    def test_sweep_low_detected(self):
        """Rejection at low sets liquidity_sweep to SWEEP_LOW."""
        engine = AcceptanceRejectionEngine()
        vah, val = 105.0, 95.0
        bar = _make_bar(open_price=96.0, high=97.0, low=92.0, close=95.5)
        result = engine.update(bar, vah, val, 1000)
        assert result.liquidity_sweep == "SWEEP_LOW"


class TestWickAnalysis:
    """Tests for candle wick pattern analysis."""

    def test_upper_wick_dominant(self):
        """Bar with large upper wick relative to body."""
        bar = _make_bar(open_price=100.0, high=110.0, low=99.0, close=101.0)
        wick = analyze_wick(bar)
        assert wick.is_upper_wick_dominant is True
        assert wick.upper_wick == 9.0  # 110 - max(100, 101)

    def test_lower_wick_dominant(self):
        """Bar with large lower wick relative to body."""
        bar = _make_bar(open_price=100.0, high=101.0, low=90.0, close=99.0)
        wick = analyze_wick(bar)
        assert wick.is_lower_wick_dominant is True
        assert wick.lower_wick == 9.0  # min(100, 99) - 90

    def test_no_dominant_wick(self):
        """Balanced bar with no dominant wick."""
        # Body=10, upper_wick=2, lower_wick=2. Neither > 10*1.5=15.
        bar = _make_bar(open_price=100.0, high=112.0, low=88.0, close=110.0)
        wick = analyze_wick(bar)
        # upper_wick = 112-110 = 2, lower_wick = 100-88 = 12, body = 10
        # 2 > 15? No. 12 > 15? No.
        assert wick.is_upper_wick_dominant is False
        assert wick.is_lower_wick_dominant is False


class TestStandaloneFunction:
    """Tests for detect_acceptance_rejection standalone function."""

    def test_acceptance_above_via_standalone(self):
        """3+ bars closing above VAH detected by standalone function."""
        bars = [_make_bar(106.0, 107.0, 105.5, 106.0) for _ in range(10)]
        # Mock IB result
        class MockIB:
            high = 105.0
            low = 95.0
        result = detect_acceptance_rejection(bars, MockIB(), [])
        assert result.accepted_above is True

    def test_no_patterns_with_empty_bars(self):
        """Empty bars returns default ARResult."""
        class MockIB:
            high = 105.0
            low = 95.0
        result = detect_acceptance_rejection([], MockIB(), [])
        assert result.accepted_above is False
        assert result.accepted_below is False
        assert result.rejected_at_high is False
        assert result.rejected_at_low is False
