"""Tests for spec §11 tick-inside profit target shielding in SignalBuilder.

When take-profit sits at a major structural level (NPOC, prior POC, VAH/VAL),
it should be placed 1-2 ticks inside (toward entry) to fill before slippage
cascades at the exact structural level.
"""

import pytest

from quant.decision.signal_builder import SignalBuilder


class TestTpShield:
    """_shield_tp: spec §11 tick-inside profit target shield."""

    def test_long_shielded_below_level(self):
        """LONG TP at structural level is moved 2 ticks below (toward entry)."""
        # Entry at 100, structural level at 110, tick=0.05
        # Shielded TP = 110 - 2*0.05 = 109.90
        shielded = SignalBuilder._shield_tp(
            tp=110.0, entry=100.0, direction="LONG", tick=0.05, shield_ticks=2
        )
        assert shielded == pytest.approx(109.90)

    def test_short_shielded_above_level(self):
        """SHORT TP at structural level is moved 2 ticks above (toward entry)."""
        # Entry at 100, structural level at 90, tick=0.05
        # Shielded TP = 90 + 2*0.05 = 90.10
        shielded = SignalBuilder._shield_tp(
            tp=90.0, entry=100.0, direction="SHORT", tick=0.05, shield_ticks=2
        )
        assert shielded == pytest.approx(90.10)

    def test_shield_preserves_signal_direction_long(self):
        """Shield never moves TP below entry (would invert LONG)."""
        # Entry at 100, level at 100.05 (only 1 tick above entry)
        # Shielded would be 100.05 - 2*0.05 = 99.95 < entry → return original
        shielded = SignalBuilder._shield_tp(
            tp=100.05, entry=100.0, direction="LONG", tick=0.05, shield_ticks=2
        )
        assert shielded == pytest.approx(100.05)  # unmodified

    def test_shield_preserves_signal_direction_short(self):
        """Shield never moves TP above entry (would invert SHORT)."""
        # Entry at 100, level at 99.95 (only 1 tick below entry)
        # Shielded would be 99.95 + 2*0.05 = 100.05 > entry → return original
        shielded = SignalBuilder._shield_tp(
            tp=99.95, entry=100.0, direction="SHORT", tick=0.05, shield_ticks=2
        )
        assert shielded == pytest.approx(99.95)  # unmodified

    def test_custom_shield_ticks(self):
        """Shield respects custom tick count."""
        # 1 tick shield
        shielded = SignalBuilder._shield_tp(
            tp=110.0, entry=100.0, direction="LONG", tick=0.05, shield_ticks=1
        )
        assert shielded == pytest.approx(109.95)

    def test_zero_tick_no_shield(self):
        """Zero tick returns TP unmodified (prevent division issues)."""
        shielded = SignalBuilder._shield_tp(
            tp=110.0, entry=100.0, direction="LONG", tick=0.0, shield_ticks=2
        )
        assert shielded == pytest.approx(110.0)

    def test_zero_tp_returns_zero(self):
        """Zero TP returns 0 (no structural target)."""
        shielded = SignalBuilder._shield_tp(
            tp=0.0, entry=100.0, direction="LONG", tick=0.05, shield_ticks=2
        )
        assert shielded == 0.0

    def test_negative_tick_safe(self):
        """Negative tick doesn't crash."""
        shielded = SignalBuilder._shield_tp(
            tp=110.0, entry=100.0, direction="LONG", tick=-0.05, shield_ticks=2
        )
        # tick <= 0 → returns tp unmodified
        assert shielded == pytest.approx(110.0)

    def test_large_tick_inches_inside(self):
        """With a large tick (e.g. CRUDEOIL tick=1.0), shield is meaningful."""
        # Entry at 5000, level at 5100, tick=1.0, shield 2 ticks
        shielded = SignalBuilder._shield_tp(
            tp=5100.0, entry=5000.0, direction="LONG", tick=1.0, shield_ticks=2
        )
        assert shielded == pytest.approx(5098.0)
