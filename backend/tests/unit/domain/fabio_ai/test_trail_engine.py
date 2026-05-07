"""Tests for TrailEngine — ATR trailing, VWAP trail, imbalance tighten, CVD breakeven.

Verifies Fabio-compliant trailing stop logic:
- ATR trail arms at 1R profit, trails 20% behind peak
- VWAP trail moves SL to VWAP bands at 1.5R
- Imbalance tighten reduces SL distance by 30% on opposition
- CVD breakeven moves SL to entry on slope confirmation
"""

import pytest
from decimal import Decimal

from app.domain.fabio_ai.services.trail_engine import TrailEngine
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side, CushionState


@pytest.fixture
def long_position():
    """Create a test LONG position."""
    pos = Position(
        symbol="CRUDEOIL",
        side=Side.LONG,
        entry_price=Decimal("6500.0"),
        size=100,
        stop_loss=Decimal("6480.0"),  # 20 risk
        initial_stop=Decimal("6480.0"),
        take_profit=Decimal("6540.0"),
    )
    return pos


@pytest.fixture
def short_position():
    """Create a test SHORT position."""
    pos = Position(
        symbol="CRUDEOIL",
        side=Side.SHORT,
        entry_price=Decimal("6500.0"),
        size=100,
        stop_loss=Decimal("6520.0"),  # 20 risk
        initial_stop=Decimal("6520.0"),
        take_profit=Decimal("6460.0"),
    )
    return pos


@pytest.fixture
def trail_engine():
    """Create TrailEngine with default config."""
    return TrailEngine(
        atr_trail_activation_r=1.0,
        atr_trail_step_pct=0.20,
        tick_size=0.05,
        cvd_breakeven=True,
        cvd_breakeven_min_slope=0.5,
    )


class TestATRTrailingStop:
    """ATR trailing stop: arm at 1R, trail 20% behind peak."""

    def test_does_not_activate_before_partial_tp(self, long_position, trail_engine):
        """ATR trail should not activate until partial TP is taken."""
        long_position.partial_taken = False
        trail_engine.apply_atr_trail(long_position, 6550.0)  # 50 profit (2.5R)
        
        assert not long_position.atr_trail_active
        assert float(long_position.stop_loss) == 6480.0  # Unchanged

    def test_arms_at_1r_profit_after_partial(self, long_position, trail_engine):
        """Trail should arm when peak profit >= 1R after partial TP."""
        long_position.partial_taken = True
        # Price moves to 6520 (20 profit = 1R)
        trail_engine.apply_atr_trail(long_position, 6520.0)
        
        assert long_position.atr_trail_active is True
        assert long_position.cushion_state == CushionState.TRAILING

    def test_trails_20_percent_behind_peak(self, long_position, trail_engine):
        """Once armed, SL should trail at 80% of peak profit."""
        long_position.partial_taken = True
        
        # Move to 1R to arm
        trail_engine.apply_atr_trail(long_position, 6520.0)
        assert long_position.atr_trail_active
        
        # Now move to 2R profit (40 profit)
        trail_engine.apply_atr_trail(long_position, 6540.0)
        
        # Peak profit = 40, retain 80% = 32, SL = 6500 + 32 = 6532
        expected_sl = 6500.0 + 40.0 * 0.8
        assert float(long_position.stop_loss) == pytest.approx(expected_sl, abs=0.1)

    def test_only_tightens_not_loosens(self, long_position, trail_engine):
        """Trail should only move SL up (for LONG), never down."""
        long_position.partial_taken = True
        long_position.atr_trail_active = True
        long_position.stop_loss = Decimal("6510.0")
        
        # Price drops, trail should not move SL down
        trail_engine.apply_atr_trail(long_position, 6505.0)
        
        assert float(long_position.stop_loss) == 6510.0  # Unchanged

    def test_short_position_trails_correctly(self, short_position, trail_engine):
        """SHORT positions should trail SL down as profit increases."""
        short_position.partial_taken = True
        
        # Move to 1R profit (price drops to 6480)
        trail_engine.apply_atr_trail(short_position, 6480.0)
        
        assert short_position.atr_trail_active is True
        
        # Move to 2R profit (price drops to 6460)
        trail_engine.apply_atr_trail(short_position, 6460.0)
        
        # Peak profit = 40, retain 80% = 32, SL = 6500 - 32 = 6468
        expected_sl = 6500.0 - 40.0 * 0.8
        assert float(short_position.stop_loss) == pytest.approx(expected_sl, abs=0.1)

    def test_updates_peak_profit_continuously(self, long_position, trail_engine):
        """Peak profit should track highest unrealized profit."""
        long_position.partial_taken = True
        
        # Move to 1.5R
        trail_engine.apply_atr_trail(long_position, 6530.0)
        assert float(long_position.peak_profit) == 30.0
        
        # Move to 2R
        trail_engine.apply_atr_trail(long_position, 6540.0)
        assert float(long_position.peak_profit) == 40.0
        
        # Price drops to 1.5R - peak should stay at 40
        trail_engine.apply_atr_trail(long_position, 6530.0)
        assert float(long_position.peak_profit) == 40.0


class TestVWAPTrailingStop:
    """VWAP trail: move SL to VWAP bands at 1.5R profit."""

    def test_does_not_activate_before_1_5r(self, long_position, trail_engine):
        """VWAP trail should not activate before 1.5R profit."""
        trail_engine.apply_vwap_trail(
            long_position,
            current_price=6515.0,  # 15 profit = 0.75R
            vwap=6490.0,
            vwap_upper_1=6500.0,
            vwap_lower_1=6480.0,
            vwap_upper_2=6510.0,
            vwap_lower_2=6470.0,
        )
        
        assert float(long_position.stop_loss) == 6480.0  # Unchanged

    def test_moves_sl_to_vwap_band_at_1_5r(self, long_position, trail_engine):
        """At 1.5R, SL should move to nearest VWAP band above entry."""
        trail_engine.apply_vwap_trail(
            long_position,
            current_price=6530.0,  # 30 profit = 1.5R
            vwap=6495.0,
            vwap_upper_1=6505.0,
            vwap_lower_1=6485.0,
            vwap_upper_2=6515.0,
            vwap_lower_2=6475.0,
        )
        
        # Should move SL to vwap_upper_1 (6505) or similar
        assert float(long_position.stop_loss) > 6480.0  # Moved up
        assert float(long_position.stop_loss) < 6530.0  # Below current price

    def test_tightens_at_2_sigma_overextension(self, long_position, trail_engine):
        """At 2 sigma overextension, SL should tighten to 50% of distance."""
        long_position.stop_loss = Decimal("6510.0")
        
        trail_engine.apply_vwap_trail(
            long_position,
            current_price=6550.0,  # Well above vwap_upper_2
            vwap=6495.0,
            vwap_upper_1=6505.0,
            vwap_lower_1=6485.0,
            vwap_upper_2=6520.0,  # Price >= this triggers tighten
            vwap_lower_2=6470.0,
        )
        
        # Should have tightened
        assert float(long_position.stop_loss) > 6510.0


class TestImbalanceTighten:
    """Imbalance tighten: reduce SL distance by 30% on stacked opposition."""

    def test_tightens_on_opposing_imbalance_long(self, long_position, trail_engine):
        """LONG position should tighten SL when SELL imbalance appears."""
        long_position.stop_loss = Decimal("6480.0")
        
        imbalances = [
            type('Imbalance', (), {'direction': 'SELL'})(),  # Opposing
        ]
        
        result = trail_engine.apply_imbalance_tighten(
            long_position, imbalances, current_price=6510.0
        )
        
        assert result is True
        # Distance was 30 (6510 - 6480), tighten by 30% = 9, new SL = 6489
        expected_sl = 6480.0 + 9.0
        assert float(long_position.stop_loss) == pytest.approx(expected_sl, abs=0.1)

    def test_tightens_on_opposing_imbalance_short(self, short_position, trail_engine):
        """SHORT position should tighten SL when BUY imbalance appears."""
        short_position.stop_loss = Decimal("6520.0")
        
        imbalances = [
            type('Imbalance', (), {'direction': 'BUY'})(),  # Opposing
        ]
        
        result = trail_engine.apply_imbalance_tighten(
            short_position, imbalances, current_price=6490.0
        )
        
        assert result is True
        # Distance was 30 (6520 - 6490), tighten by 30% = 9, new SL = 6511
        expected_sl = 6520.0 - 9.0
        assert float(short_position.stop_loss) == pytest.approx(expected_sl, abs=0.1)

    def test_no_tighten_on_supporting_imbalance(self, long_position, trail_engine):
        """No tighten when imbalance supports position direction."""
        long_position.stop_loss = Decimal("6480.0")
        
        imbalances = [
            type('Imbalance', (), {'direction': 'BUY'})(),  # Supporting LONG
        ]
        
        result = trail_engine.apply_imbalance_tighten(
            long_position, imbalances, current_price=6510.0
        )
        
        assert result is False
        assert float(long_position.stop_loss) == 6480.0  # Unchanged

    def test_no_tighten_without_imbalances(self, long_position, trail_engine):
        """No tighten when no imbalances present."""
        long_position.stop_loss = Decimal("6480.0")
        
        result = trail_engine.apply_imbalance_tighten(
            long_position, [], current_price=6510.0
        )
        
        assert result is False
        assert float(long_position.stop_loss) == 6480.0


class TestCVDBreakeven:
    """CVD breakeven: move SL to entry on slope confirmation."""

    def test_moves_to_breakeven_on_positive_slope_long(self, long_position, trail_engine):
        """LONG position should move to BE when CVD slope >= threshold."""
        long_position.breakeven_set = False
        
        result = trail_engine.apply_cvd_breakeven(long_position, cvd_slope=0.6)
        
        assert result is True
        assert long_position.breakeven_set is True
        assert float(long_position.stop_loss) == 6500.0  # Entry price
        assert long_position.cushion_state == CushionState.CUSHIONED

    def test_moves_to_breakeven_on_negative_slope_short(self, short_position, trail_engine):
        """SHORT position should move to BE when CVD slope <= -threshold."""
        short_position.breakeven_set = False
        
        result = trail_engine.apply_cvd_breakeven(short_position, cvd_slope=-0.6)
        
        assert result is True
        assert short_position.breakeven_set is True
        assert float(short_position.stop_loss) == 6500.0  # Entry price

    def test_no_breakeven_on_weak_slope(self, long_position, trail_engine):
        """No BE when CVD slope is below threshold."""
        long_position.breakeven_set = False
        
        result = trail_engine.apply_cvd_breakeven(long_position, cvd_slope=0.3)
        
        assert result is False
        assert long_position.breakeven_set is False
        assert float(long_position.stop_loss) == 6480.0  # Unchanged

    def test_no_breakeven_if_already_set(self, long_position, trail_engine):
        """No duplicate BE if already set."""
        long_position.breakeven_set = True
        long_position.stop_loss = Decimal("6500.0")
        
        result = trail_engine.apply_cvd_breakeven(long_position, cvd_slope=0.6)
        
        assert result is False
        assert float(long_position.stop_loss) == 6500.0  # Unchanged

    def test_breakeven_disabled_when_config_false(self, long_position):
        """No BE when CVD breakeven is disabled in config."""
        engine = TrailEngine(cvd_breakeven=False)
        long_position.breakeven_set = False
        
        result = engine.apply_cvd_breakeven(long_position, cvd_slope=0.6)
        
        assert result is False
        assert long_position.breakeven_set is False


class TestCVDKillSignal:
    """CVD kill signal: exit or move to BE on divergence."""

    def test_scratch_long_on_bearish_div_after_partial(self, long_position, trail_engine):
        """LONG should scratch on BEARISH_DIV after partial TP."""
        long_position.partial_taken = True
        
        signal = trail_engine.apply_cvd_kill_signal(
            long_position, cvd_divergence="BEARISH_DIV", current_price=6510.0
        )
        
        assert signal is not None
        assert signal.reason == "SCRATCH"
        assert long_position.cushion_state == CushionState.CLOSED

    def test_move_to_be_long_on_bearish_div_before_partial(self, long_position, trail_engine):
        """LONG should move to BE (not exit) on BEARISH_DIV before partial."""
        long_position.partial_taken = False
        
        signal = trail_engine.apply_cvd_kill_signal(
            long_position, cvd_divergence="BEARISH_DIV", current_price=6510.0
        )
        
        assert signal is None  # Not a full exit
        assert float(long_position.stop_loss) == 6500.0  # Moved to BE

    def test_scratch_short_on_bullish_div_after_partial(self, short_position, trail_engine):
        """SHORT should scratch on BULLISH_DIV after partial TP."""
        short_position.partial_taken = True
        
        signal = trail_engine.apply_cvd_kill_signal(
            short_position, cvd_divergence="BULLISH_DIV", current_price=6490.0
        )
        
        assert signal is not None
        assert signal.reason == "SCRATCH"

    def test_no_signal_without_divergence(self, long_position, trail_engine):
        """No signal when there's no divergence."""
        signal = trail_engine.apply_cvd_kill_signal(
            long_position, cvd_divergence="", current_price=6510.0
        )
        
        assert signal is None


class TestStopLossAdjustment:
    """Manual SL adjustment: only tighten, never loosen."""

    def test_allows_tighten_up_for_long(self, long_position, trail_engine):
        """LONG can tighten SL up (higher)."""
        result = trail_engine.adjust_stop_loss(long_position, 6490.0)
        
        assert result is True
        assert float(long_position.stop_loss) == 6490.0

    def test_rejects_loosen_for_long(self, long_position, trail_engine):
        """LONG cannot loosen SL down (lower)."""
        long_position.stop_loss = Decimal("6490.0")
        
        result = trail_engine.adjust_stop_loss(long_position, 6480.0)
        
        assert result is False
        assert float(long_position.stop_loss) == 6490.0  # Unchanged

    def test_allows_tighten_down_for_short(self, short_position, trail_engine):
        """SHORT can tighten SL down (lower)."""
        result = trail_engine.adjust_stop_loss(short_position, 6510.0)
        
        assert result is True
        assert float(short_position.stop_loss) == 6510.0

    def test_rejects_loosen_for_short(self, short_position, trail_engine):
        """SHORT cannot loosen SL up (higher)."""
        short_position.stop_loss = Decimal("6510.0")
        
        result = trail_engine.adjust_stop_loss(short_position, 6520.0)
        
        assert result is False
        assert float(short_position.stop_loss) == 6510.0  # Unchanged

    def test_respects_breakeven_protection_long(self, long_position, trail_engine):
        """Cannot move SL below entry when breakeven is set."""
        long_position.breakeven_set = True
        long_position.stop_loss = Decimal("6500.0")
        
        result = trail_engine.adjust_stop_loss(long_position, 6490.0)
        
        assert result is False
        assert float(long_position.stop_loss) == 6500.0

    def test_rounds_to_tick_size(self, long_position):
        """SL should be rounded to tick size."""
        engine = TrailEngine(tick_size=0.05)
        
        result = engine.adjust_stop_loss(long_position, 6485.123)
        
        assert result is True
        # Should be rounded
        stop_mod = float(long_position.stop_loss) % 0.05
        assert stop_mod < 0.001 or abs(stop_mod - 0.05) < 0.001
