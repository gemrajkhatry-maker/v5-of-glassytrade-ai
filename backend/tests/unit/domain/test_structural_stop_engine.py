"""Tests for StructuralStopEngine — P1-6 implementation."""

from __future__ import annotations

import pytest

from app.domain.fabio_ai.services.structural_stop_engine import (
    compute_structural_stop,
    StopReason,
    StructuralStop,
)


class TestStructuralStopEngine:
    """Tests for structural stop loss computation."""

    def test_failed_auction_long_stop(self):
        """FAILED_AUCTION LONG: SL below probe extreme."""
        stop = compute_structural_stop(
            entry_price=24680.0,
            direction="LONG",
            setup_type="FAILED_AUCTION",
            probe_extreme=24650.0,
            tick_size=5.0,
        )
        assert stop.reason == StopReason.PROBE_EXTREME.value
        assert stop.price < 24680.0  # Below entry
        assert stop.price < 24650.0  # Below probe extreme
        assert stop.distance_pct > 0

    def test_failed_auction_short_stop(self):
        """FAILED_AUCTION SHORT: SL above probe extreme."""
        stop = compute_structural_stop(
            entry_price=24920.0,
            direction="SHORT",
            setup_type="FAILED_AUCTION",
            probe_extreme=24950.0,
            tick_size=5.0,
        )
        assert stop.reason == StopReason.PROBE_EXTREME.value
        assert stop.price > 24920.0  # Above entry
        assert stop.price > 24950.0  # Above probe extreme

    def test_aaa_long_stop_from_lvn(self):
        """AAA LONG: SL below nearest LVN."""
        stop = compute_structural_stop(
            entry_price=24800.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(24750.0, 24700.0, 24650.0),
            tick_size=5.0,
        )
        assert stop.reason == StopReason.LVN.value
        assert stop.price < 24750.0  # Below nearest LVN
        assert stop.price < 24800.0  # Below entry

    def test_mean_reversion_long_stop_from_lvn(self):
        """MEAN_REVERSION LONG: SL below nearest LVN."""
        stop = compute_structural_stop(
            entry_price=24780.0,
            direction="LONG",
            setup_type="MEAN_REVERSION",
            lvns=(24750.0, 24700.0),
            tick_size=5.0,
        )
        assert stop.reason == StopReason.LVN.value
        assert stop.price < 24750.0

    def test_momentum_long_stop_from_ib(self):
        """MOMENTUM LONG: SL below IB low."""
        stop = compute_structural_stop(
            entry_price=24850.0,
            direction="LONG",
            setup_type="MOMENTUM",
            ib_high=24880.0,
            ib_low=24780.0,
            tick_size=5.0,
        )
        assert stop.reason == StopReason.IB_EXTREME.value
        assert stop.price < 24780.0  # Below IB low
        assert stop.price < 24850.0  # Below entry

    def test_momentum_short_stop_from_ib(self):
        """MOMENTUM SHORT: SL above IB high."""
        stop = compute_structural_stop(
            entry_price=24750.0,
            direction="SHORT",
            setup_type="MOMENTUM",
            ib_high=24820.0,
            ib_low=24780.0,
            tick_size=5.0,
        )
        assert stop.reason == StopReason.IB_EXTREME.value
        assert stop.price > 24820.0  # Above IB high
        assert stop.price > 24750.0  # Above entry

    def test_atr_cap_applied(self):
        """ATR cap prevents runaway risk."""
        stop = compute_structural_stop(
            entry_price=24800.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(24500.0,),  # Very far LVN
            atr=50.0,  # 2x ATR = 100
            tick_size=5.0,
        )
        # Without cap: SL would be at 24495 (305 points away)
        # With cap: SL at most 100 points away (2x ATR)
        assert stop.reason == StopReason.ATR_CAP.value
        assert stop.distance_from_entry <= 100.0  # 2x ATR
        assert stop.atr_multiple == 2.0

    def test_fallback_stop_when_no_levels(self):
        """Fallback when no structural levels available."""
        stop = compute_structural_stop(
            entry_price=24800.0,
            direction="LONG",
            setup_type="UNKNOWN",
            tick_size=5.0,
        )
        assert stop.reason == StopReason.FALLBACK.value
        assert stop.price < 24800.0
        assert stop.distance_pct > 0

    def test_invalid_entry_price(self):
        """Invalid entry price returns zero stop."""
        stop = compute_structural_stop(
            entry_price=0.0,
            direction="LONG",
        )
        assert stop.price == 0.0
        assert stop.distance_from_entry == 0.0

    def test_stop_rounded_to_tick(self):
        """SL is rounded to tick boundary."""
        stop = compute_structural_stop(
            entry_price=24803.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(24751.0,),
            tick_size=5.0,
        )
        # Should be rounded to tick boundary
        assert stop.price % 5.0 == 0.0

    def test_thesis_generated(self):
        """All stops have human-readable thesis."""
        stop = compute_structural_stop(
            entry_price=24800.0,
            direction="LONG",
            setup_type="FAILED_AUCTION",
            probe_extreme=24650.0,
            tick_size=5.0,
        )
        assert len(stop.thesis) > 20
        assert "Failed Auction" in stop.thesis

    def test_no_lvn_below_uses_fallback(self):
        """No LVN below entry → fallback for LONG."""
        stop = compute_structural_stop(
            entry_price=24800.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(24850.0, 24900.0),  # All above entry
            tick_size=5.0,
        )
        assert stop.reason == StopReason.FALLBACK.value
        assert stop.price < 24800.0

    def test_no_lvn_above_uses_fallback(self):
        """No LVN above entry → fallback for SHORT."""
        stop = compute_structural_stop(
            entry_price=24800.0,
            direction="SHORT",
            setup_type="AAA",
            lvns=(24750.0, 24700.0),  # All below entry
            tick_size=5.0,
        )
        assert stop.reason == StopReason.FALLBACK.value
        assert stop.price > 24800.0

    def test_nearest_lvn_selected(self):
        """Nearest LVN is selected, not farthest."""
        stop = compute_structural_stop(
            entry_price=24800.0,
            direction="LONG",
            setup_type="AAA",
            lvns=(24750.0, 24700.0, 24600.0),
            tick_size=5.0,
        )
        # Should use 24750 (nearest below), not 24600
        assert stop.price > 24600.0  # Above farthest LVN
        assert stop.price < 24750.0  # Below nearest LVN

    def test_momentum_uses_va_when_no_ib(self):
        """MOMENTUM uses VA boundary when IB not available."""
        stop = compute_structural_stop(
            entry_price=24850.0,
            direction="LONG",
            setup_type="MOMENTUM",
            vah=24900.0,
            val=24780.0,
            tick_size=5.0,
        )
        assert stop.reason == StopReason.VA_BOUNDARY.value
        assert stop.price < 24780.0  # Below VAL
