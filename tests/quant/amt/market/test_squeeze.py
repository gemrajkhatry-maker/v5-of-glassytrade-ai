"""Tests for Momentum Squeeze Detector per Fabio's Rule #10."""

from __future__ import annotations

import pytest

from quant.amt.market.squeeze import (
    MomentumSqueezeDetector,
    SqueezeState,
)


class TestMomentumSqueezeDetector:
    """Tests for compression breakout logic."""

    def setup_method(self):
        self.detector = MomentumSqueezeDetector()

    def test_no_squeeze_initially(self):
        """Detector starts with no squeeze."""
        state = self.detector._state
        assert state.in_squeeze is False
        assert state.compression_bars == 0

    def test_expansion_phase_resets_compression(self):
        """Wide range bars reset squeeze detection."""
        # First, establish expansion range
        for _ in range(5):
            self.detector.update(
                current_high=105.0,
                current_low=95.0,
                current_close=100.0,
                volume=10000.0,
                avg_volume=5000.0,
                current_atr=5.0,
                bar_number=1,
            )

        # Compression phase - narrow range with volume/atr decline
        state = self.detector.update(
            current_high=100.0,
            current_low=99.5,
            current_close=99.75,
            volume=2000.0,  # Low volume
            avg_volume=5000.0,
            current_atr=3.0,  # Low ATR
            bar_number=6,
        )
        # Range is 0.5 points vs expansion of 10 = 5% - should trigger squeeze
        assert state.in_squeeze is True

    def test_squeeze_requires_volume_decline(self):
        """Volume must decline for squeeze detection."""
        # Set expansion
        self.detector._high_of_expansion = 110.0
        self.detector._low_of_expansion = 90.0

        state = self.detector.update(
            current_high=100.0,
            current_low=99.0,
            current_close=99.5,
            volume=10000.0,  # High volume - no squeeze
            avg_volume=5000.0,
            current_atr=2.0,
            bar_number=1,
        )
        assert state.in_squeeze is False

    def test_squeeze_requires_atr_decline(self):
        """ATR must decline for squeeze detection."""
        self.detector._high_of_expansion = 110.0
        self.detector._low_of_expansion = 90.0
        self.detector._state.prior_atr = 5.0

        state = self.detector.update(
            current_high=100.0,
            current_low=99.0,
            current_close=99.5,
            volume=2000.0,  # Low volume
            avg_volume=5000.0,
            current_atr=4.0,  # ATR not declined enough (< 30%)
            bar_number=1,
        )
        assert state.in_squeeze is False

    def test_squeeze_detected_when_conditions_met(self):
        """All three conditions trigger squeeze."""
        self.detector._high_of_expansion = 110.0
        self.detector._low_of_expansion = 90.0
        self.detector._state.prior_atr = 5.0

        state = self.detector.update(
            current_high=100.0,
            current_low=99.0,
            current_close=99.5,
            volume=1000.0,  # Low volume (< 50% avg)
            avg_volume=5000.0,
            current_atr=3.0,  # ATR down 40% (< 70% threshold)
            bar_number=1,
        )
        assert state.in_squeeze is True
        assert state.compression_bars == 1

    def test_breakout_detected_on_expansion(self):
        """Breakout triggers when range expands with volume."""
        # Establish squeeze
        self.detector._high_of_expansion = 100.0
        self.detector._low_of_expansion = 95.0
        self.detector._state.in_squeeze = True
        self.detector._state.compression_bars = 3

        result = self.detector.check_breakout(
            current_high=105.0,
            current_low=95.0,
            volume=8000.0,
            avg_volume=5000.0,
        )
        assert result is not None
        assert result["breakout"] is True
        assert result["direction"] == "LONG"
        assert result["squeeze_duration"] == 3

    def test_breakout_requires_volume_confirmation(self):
        """Breakout without volume confirmation doesn't trigger."""
        self.detector._high_of_expansion = 100.0
        self.detector._low_of_expansion = 95.0
        self.detector._state.in_squeeze = True

        result = self.detector.check_breakout(
            current_high=105.0,
            current_low=95.0,
            volume=3000.0,  # Low volume
            avg_volume=5000.0,
        )
        assert result is None

    def test_reset_clears_state(self):
        """Reset clears all squeeze state."""
        self.detector._state.in_squeeze = True
        self.detector._state.compression_bars = 5
        self.detector._high_of_expansion = 110.0

        self.detector.reset()

        assert self.detector._state.in_squeeze is False
        assert self.detector._state.compression_bars == 0
        assert self.detector._high_of_expansion == 0.0