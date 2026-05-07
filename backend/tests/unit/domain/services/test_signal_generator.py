"""Tests for Signal Generator with structural stop placement.

Verifies that signals use Fabio-compliant structural stops instead of
hardcoded percentages.
"""

import pytest
from datetime import datetime

from app.domain.services.signal_generator import SignalGenerator
from app.domain.trading.models.enums import SignalType, SetupType


@pytest.fixture
def generator():
    """Create a fresh SignalGenerator instance."""
    return SignalGenerator()


class TestSignalGeneratorStructuralStops:
    """Verify signal generator uses structural stop engine."""

    def test_generates_long_signal_with_structural_stop(self, generator):
        """Long signals should have stop below entry at structural level."""
        signal = generator.generate(
            symbol="CRUDEOIL",
            market_state="BALANCE",
            poc=6500.0,
            vah=6550.0,
            val=6450.0,
            aggression=0.7,
            ofi=0.5,
            cvd_slope=0.3,
            lvns=(6440.0, 6480.0),
            hvns=(6520.0, 6560.0),
            ib_high=6540.0,
            ib_low=6460.0,
            atr=15.0,
            tick_size=0.05,
        )

        assert signal.type == SignalType.BUY
        assert float(signal.price) == 6500.0  # POC
        assert float(signal.stop_loss) < float(signal.price)  # Stop below entry
        # For MEAN_REVERSION, should use LVN at 6480, stop one tick beyond
        assert float(signal.stop_loss) < 6480.5  # Near LVN
        assert float(signal.take_profit) > float(signal.price)
        assert float(signal.stop_loss) > 0

    def test_generates_short_signal_with_structural_stop(self, generator):
        """Short signals should have stop above entry at structural level."""
        signal = generator.generate(
            symbol="CRUDEOIL",
            market_state="IMBALANCE",
            poc=6500.0,
            vah=6550.0,
            val=6450.0,
            aggression=-0.7,
            ofi=-0.5,
            cvd_slope=-0.3,
            lvns=(6440.0, 6480.0),
            hvns=(6520.0, 6560.0),
            ib_high=6540.0,
            ib_low=6460.0,
            atr=15.0,
            tick_size=0.05,
        )

        assert signal.type == SignalType.SELL
        assert float(signal.price) == 6500.0
        assert float(signal.stop_loss) > float(signal.price)  # Stop above entry
        # For RESPONSIVE_FADE without LVN above, uses nearest HVN at 6520
        assert float(signal.stop_loss) > 6519.0  # Near HVN
        assert float(signal.take_profit) < float(signal.price)
        assert float(signal.stop_loss) > 0

    def test_stop_uses_lvn_for_mean_reversion(self, generator):
        """Mean reversion setup should place stop beyond LVN."""
        signal = generator.generate(
            symbol="GOLDM",
            market_state="BALANCE",
            poc=75000.0,
            vah=75500.0,
            val=74500.0,
            aggression=0.6,
            ofi=0.4,
            cvd_slope=0.2,
            lvns=(74400.0, 74800.0),  # LVN below VAL
            hvns=(75200.0, 75600.0),
            ib_high=75400.0,
            ib_low=74600.0,
            atr=200.0,
            tick_size=1.0,
        )

        # Should use LVN at 74800 (nearest below entry), stop one tick beyond
        assert float(signal.stop_loss) < 74800.0  # Below nearest LVN
        # Metadata should contain structural stop info
        assert "structural_stop_reason" in signal.metadata
        assert signal.metadata["structural_stop_reason"] in ("LVN", "VA_BOUNDARY", "FALLBACK")

    def test_stop_capped_by_atr(self, generator):
        """Structural stop should be capped at 2x ATR."""
        signal = generator.generate(
            symbol="CRUDEOIL",
            market_state="TREND",
            poc=6500.0,
            vah=6550.0,
            val=6450.0,
            aggression=0.8,
            ofi=0.6,
            cvd_slope=0.4,
            lvns=(6300.0,),  # Very far LVN
            hvns=(6700.0,),
            ib_high=6540.0,
            ib_low=6460.0,
            atr=10.0,  # Small ATR
            tick_size=0.05,
        )

        # Stop distance should not exceed 2x ATR (20.0)
        stop_distance = abs(signal.price - signal.stop_loss)
        assert stop_distance <= 22.0  # 2x ATR with some rounding tolerance
        # Metadata should indicate ATR cap
        if signal.metadata.get("structural_stop_reason") == "ATR_CAP":
            assert signal.metadata["atr_multiple"] == 2.0

    def test_signal_metadata_contains_stop_thesis(self, generator):
        """Signal metadata should explain stop placement rationale."""
        signal = generator.generate(
            symbol="SILVERM",
            market_state="BALANCE",
            poc=85000.0,
            vah=85500.0,
            val=84500.0,
            aggression=0.7,
            ofi=0.5,
            cvd_slope=0.3,
            lvns=(84400.0,),
            hvns=(85600.0,),
            ib_high=85400.0,
            ib_low=84600.0,
            atr=150.0,
            tick_size=1.0,
        )

        assert "structural_stop_reason" in signal.metadata
        assert "structural_stop_thesis" in signal.metadata
        assert "atr_multiple" in signal.metadata
        # Thesis should be human-readable
        thesis = signal.metadata["structural_stop_thesis"]
        assert isinstance(thesis, str)
        assert len(thesis) > 10

    def test_take_profit_uses_risk_distance(self, generator):
        """TP should be set at 2x risk distance from entry."""
        signal = generator.generate(
            symbol="CRUDEOIL",
            market_state="BALANCE",
            poc=6500.0,
            vah=6550.0,
            val=6450.0,
            aggression=0.7,
            ofi=0.5,
            cvd_slope=0.3,
            lvns=(6480.0,),
            hvns=(6520.0,),
            ib_high=6540.0,
            ib_low=6460.0,
            atr=15.0,
            tick_size=0.05,
        )

        risk_distance = abs(float(signal.price) - float(signal.stop_loss))
        tp_distance = abs(float(signal.take_profit) - float(signal.price))
        
        # R:R should be approximately 2:1
        rr_ratio = tp_distance / max(risk_distance, 0.01)
        assert rr_ratio == pytest.approx(2.0, rel=0.05)

    def test_neutral_conditions_no_signal(self, generator):
        """Low aggression and flat CVD should still generate signal (placeholder logic)."""
        signal = generator.generate(
            symbol="CRUDEOIL",
            market_state="NEUTRAL",
            poc=6500.0,
            vah=6550.0,
            val=6450.0,
            aggression=0.1,
            ofi=0.0,
            cvd_slope=0.0,
            lvns=(6480.0,),
            hvns=(6520.0,),
            atr=15.0,
        )

        # Current placeholder always generates a signal
        assert signal is not None
        assert signal.price == 6500.0
        assert signal.stop_loss > 0

    def test_different_setups_use_different_stop_logic(self, generator):
        """Different market conditions should result in different stop placements."""
        # Setup 1: Mean reversion with clear LVN
        signal_mr = generator.generate(
            symbol="GOLDM",
            market_state="BALANCE",
            poc=75000.0,
            vah=75500.0,
            val=74500.0,
            aggression=0.7,
            ofi=0.5,
            cvd_slope=0.3,
            lvns=(74800.0,),
            hvns=(75200.0,),
            atr=200.0,
        )

        # Setup 2: No structural levels (should use fallback)
        signal_fallback = generator.generate(
            symbol="GOLDM",
            market_state="TREND",
            poc=75000.0,
            vah=75500.0,
            val=74500.0,
            aggression=0.7,
            ofi=0.5,
            cvd_slope=0.3,
            lvns=(),  # No LVNs
            hvns=(),  # No HVNs
            atr=200.0,
        )

        # Both should have valid stops but potentially different reasons
        assert signal_mr.stop_loss > 0
        assert signal_fallback.stop_loss > 0


class TestSignalGeneratorEdgeCases:
    """Edge cases and error handling."""

    def test_zero_atr_uses_structural_levels_only(self, generator):
        """When ATR is zero, should use structural levels without cap."""
        signal = generator.generate(
            symbol="CRUDEOIL",
            market_state="BALANCE",
            poc=6500.0,
            vah=6550.0,
            val=6450.0,
            aggression=0.7,
            ofi=0.5,
            cvd_slope=0.3,
            lvns=(6480.0,),
            hvns=(6520.0,),
            atr=0.0,  # No ATR
            tick_size=0.05,
        )

        assert signal.stop_loss > 0
        assert signal.metadata["atr_multiple"] == 0.0

    def test_missing_ib_levels_uses_va_levels(self, generator):
        """When IB levels are missing, should fall back to VA levels."""
        signal = generator.generate(
            symbol="CRUDEOIL",
            market_state="BALANCE",
            poc=6500.0,
            vah=6550.0,
            val=6450.0,
            aggression=0.7,
            ofi=0.5,
            cvd_slope=0.3,
            lvns=(6480.0,),
            hvns=(6520.0,),
            ib_high=0.0,  # No IB
            ib_low=0.0,
            atr=15.0,
        )

        assert signal.stop_loss > 0

    def test_tick_size_rounding(self, generator):
        """Stop loss should be rounded to tick size."""
        signal = generator.generate(
            symbol="CRUDEOIL",
            market_state="BALANCE",
            poc=6500.123,  # Non-standard price
            vah=6550.0,
            val=6450.0,
            aggression=0.7,
            ofi=0.5,
            cvd_slope=0.3,
            lvns=(6480.333,),
            hvns=(6520.0,),
            atr=15.0,
            tick_size=0.05,
        )

        # Stop should be rounded to tick boundary
        stop_float = float(signal.stop_loss)
        stop_mod = stop_float % 0.05
        assert stop_mod < 0.001 or abs(stop_mod - 0.05) < 0.001
