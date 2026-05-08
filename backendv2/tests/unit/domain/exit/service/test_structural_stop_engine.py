"""Tests for structural stop engine."""
from __future__ import annotations

import pytest

from app.domain.exit.model.exit_models import StopReason, StructuralStop
from app.domain.exit.service.structural_stop_engine import compute_structural_stop


class TestStructuralStopEngine:
    """Test compute_structural_stop for all setup types."""

    def test_failed_auction_uses_probe_extreme(self):
        """FAILED_AUCTION setup uses probe_extreme for stop placement."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="FAILED_AUCTION",
            probe_extreme=98.0,
            tick_size=0.05,
        )

        assert stop.price < 98.0  # one tick below probe extreme
        assert stop.reason == StopReason.PROBE_EXTREME.value
        assert "probe extreme" in stop.thesis.lower()

    def test_failed_auction_short(self):
        """FAILED_AUCTION SHORT stop is above probe extreme."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="SHORT",
            setup_type="FAILED_AUCTION",
            probe_extreme=102.0,
            tick_size=0.05,
        )

        assert stop.price > 102.0  # one tick above probe extreme
        assert stop.reason == StopReason.PROBE_EXTREME.value

    def test_trend_model_uses_lvn(self):
        """TREND_MODEL (AAA/MEAN_REVERSION) setup uses LVN levels."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(95.0, 97.0, 99.0),
            tick_size=0.05,
        )

        assert stop.price < 100.0
        assert stop.reason == StopReason.LVN.value
        assert "LVN" in stop.thesis

    def test_trend_model_short_uses_lvn(self):
        """TREND_MODEL SHORT stop uses LVN above entry."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="SHORT",
            setup_type="MEAN_REVERSION",
            lvns=(101.0, 103.0, 105.0),
            tick_size=0.05,
        )

        assert stop.price > 100.0
        assert stop.reason == StopReason.LVN.value

    def test_momentum_setup_uses_ib_va(self):
        """MOMENTUM setup uses IB/VA levels."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="MOMENTUM",
            ib_high=102.0,
            ib_low=97.0,
            vah=101.0,
            val=98.0,
            tick_size=0.05,
        )

        assert stop.price < 100.0
        assert stop.reason in (StopReason.IB_EXTREME.value, StopReason.VA_BOUNDARY.value)

    def test_momentum_short_uses_ib_high(self):
        """MOMENTUM SHORT stop is above entry using IB high or VAH."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="SHORT",
            setup_type="MOMENTUM",
            ib_high=103.0,
            ib_low=97.0,
            vah=102.0,
            val=98.0,
            tick_size=0.05,
        )

        assert stop.price > 100.0

    def test_default_setup_uses_nearest_level(self):
        """Default (unknown) setup uses nearest structural level."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="UNKNOWN",
            lvns=(95.0, 97.0),
            hvns=(96.0,),
            vah=99.0,
            val=98.0,
            ib_high=102.0,
            ib_low=97.5,
            tick_size=0.05,
        )

        assert stop.price < 100.0
        assert stop.reason == StopReason.FALLBACK.value

    def test_fallback_when_no_levels(self):
        """Fallback 1.5% stop when no structural levels available."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="",
            tick_size=0.05,
        )

        assert stop.price == pytest.approx(98.5, abs=0.1)
        assert stop.reason == StopReason.FALLBACK.value
        assert "1.5%" in stop.thesis

    def test_fallback_for_short(self):
        """Fallback stop for SHORT is above entry."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="SHORT",
            setup_type="",
            tick_size=0.05,
        )

        assert stop.price == pytest.approx(101.5, abs=0.1)

    def test_tick_rounding_applied(self):
        """Stop price is rounded to tick size."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(95.0,),
            tick_size=0.05,
        )

        # Price should be a multiple of tick_size (within floating point tolerance)
        remainder = stop.price % 0.05
        assert remainder < 0.01 or abs(remainder - 0.05) < 0.01

    def test_atr_cap_enforcement(self):
        """ATR cap limits stop distance to 2x ATR."""
        # LVN is far away (80), ATR is small (2) -> cap at 2*ATR = 4
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(80.0,),  # far away
            atr=2.0,
            tick_size=0.05,
        )

        assert stop.reason == StopReason.ATR_CAP.value
        assert stop.distance_from_entry <= 4.05  # 2*ATR + tick
        assert "ATR" in stop.thesis.upper() or "cap" in stop.thesis.lower()

    def test_invalid_entry_returns_zero_stop(self):
        """Zero or negative entry price returns fallback with zero stop."""
        stop = compute_structural_stop(
            entry_price=0.0,
            direction="LONG",
            setup_type="AAA",
        )

        assert stop.price == 0.0
        assert stop.reason == StopReason.FALLBACK.value
        assert "Invalid" in stop.thesis

    def test_distance_pct_computed(self):
        """distance_pct is correctly computed."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="",
            tick_size=0.05,
        )

        assert stop.distance_pct > 0
        assert stop.distance_pct == pytest.approx(
            abs(stop.price - 100.0) / 100.0, abs=0.001
        )

    def test_lvn_long_no_candidates_below_entry(self):
        """When all LVNs are above entry for LONG, fallback to 1.5% stop."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(105.0, 110.0),  # All above entry
            tick_size=0.05,
        )

        assert stop.reason == StopReason.FALLBACK.value
        assert stop.price == pytest.approx(98.5, abs=0.1)

    def test_lvn_short_no_candidates_above_entry(self):
        """When all LVNs are below entry for SHORT, fallback to 1.5% stop."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="SHORT",
            setup_type="AAA",
            lvns=(95.0, 90.0),  # All below entry
            tick_size=0.05,
        )

        assert stop.reason == StopReason.FALLBACK.value
        assert stop.price == pytest.approx(101.5, abs=0.1)

    def test_momentum_long_no_ib_low_no_val(self):
        """Momentum LONG with no IB low and no VAL falls back."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="MOMENTUM",
            ib_high=105.0,
            ib_low=0.0,
            vah=110.0,
            val=0.0,
            tick_size=0.05,
        )

        assert stop.reason == StopReason.FALLBACK.value

    def test_momentum_short_no_ib_high_no_vah(self):
        """Momentum SHORT with no IB high and no VAH falls back."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="SHORT",
            setup_type="MOMENTUM",
            ib_high=0.0,
            ib_low=95.0,
            vah=0.0,
            val=90.0,
            tick_size=0.05,
        )

        assert stop.reason == StopReason.FALLBACK.value

    def test_nearest_level_short_uses_vah_and_ib_high(self):
        """Default fallback for SHORT uses VAH and IB high levels."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="SHORT",
            setup_type="",
            lvns=(95.0,),
            hvns=(96.0,),
            vah=105.0,
            val=90.0,
            ib_high=103.0,
            ib_low=97.0,
            tick_size=0.05,
        )

        # Should use nearest level above entry (103.0 from ib_high)
        assert stop.price > 100.0

    def test_nearest_level_fallback_no_levels(self):
        """Default fallback with no levels uses 1.5% stop."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="",
            lvns=(),
            hvns=(),
            vah=0.0,
            val=0.0,
            ib_high=0.0,
            ib_low=0.0,
            tick_size=0.05,
        )

        assert stop.reason == StopReason.FALLBACK.value
        assert stop.price == pytest.approx(98.5, abs=0.1)

    def test_zero_tick_size_no_rounding(self):
        """Zero tick size returns price without rounding."""
        stop = compute_structural_stop(
            entry_price=100.0,
            direction="LONG",
            setup_type="",
            tick_size=0.0,
        )

        # Should still compute fallback, just no rounding
        assert stop.price > 0
