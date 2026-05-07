"""Tests for AbsorptionValidator."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.domain.fabio_ai.services.absorption_validator import (
    AbsorptionValidationResult,
    AbsorptionValidator,
)


def _make_ohlc(high: float, low: float, close: float = 0.0,
               time: datetime = None) -> SimpleNamespace:
    """Create a minimal OHLC value object."""
    return SimpleNamespace(
        time=time or datetime.now(),
        high=high,
        low=low,
        close=close,
    )


class TestAbsorptionValidator:
    """Test AbsorptionValidator displacement confirmation."""

    def test_record_absorption_tracks_event(self):
        """record_absorption() stores absorption event in pending list."""
        validator = AbsorptionValidator()
        candle = _make_ohlc(high=100.5, low=99.5, close=100.0)

        validator.record_absorption(candle, direction="LONG")

        assert len(validator._pending_absorptions) == 1
        item = validator._pending_absorptions[0]
        assert item["high"] == 100.5
        assert item["low"] == 99.5
        assert item["direction"] == "LONG"
        assert item["candles_waited"] == 0

    def test_validate_displacement_confirms_long(self):
        """validate_displacement() confirms displacement beyond absorption high for LONG."""
        validator = AbsorptionValidator()
        abs_candle = _make_ohlc(high=100.5, low=99.5)
        validator.record_absorption(abs_candle, direction="LONG")

        # Next candle breaks above absorption high
        disp_candle = _make_ohlc(high=101.0, low=100.0)
        results = validator.validate_displacement(disp_candle)

        assert len(results) == 1
        assert results[0].valid is True
        assert results[0].displacement_confirmed is True
        assert results[0].direction == "LONG"

    def test_validate_displacement_confirms_short(self):
        """validate_displacement() confirms displacement below absorption low for SHORT."""
        validator = AbsorptionValidator()
        abs_candle = _make_ohlc(high=100.5, low=99.5)
        validator.record_absorption(abs_candle, direction="SHORT")

        # Next candle breaks below absorption low
        disp_candle = _make_ohlc(high=100.0, low=99.0)
        results = validator.validate_displacement(disp_candle)

        assert len(results) == 1
        assert results[0].valid is True
        assert results[0].displacement_confirmed is True
        assert results[0].direction == "SHORT"

    def test_timeout_without_displacement(self):
        """Absorption expires after displacement_candles candles without displacement."""
        validator = AbsorptionValidator(displacement_candles=2)
        abs_candle = _make_ohlc(high=100.5, low=99.5)
        validator.record_absorption(abs_candle, direction="LONG")

        # First candle: no displacement (high stays below absorption high)
        candle1 = _make_ohlc(high=100.0, low=99.0)
        results1 = validator.validate_displacement(candle1)
        assert len(results1) == 0  # still pending, not expired yet

        # Second candle: still no displacement -> expires
        candle2 = _make_ohlc(high=100.0, low=99.0)
        results2 = validator.validate_displacement(candle2)

        assert len(results2) == 1
        assert results2[0].valid is False
        assert results2[0].displacement_confirmed is False
        assert "No displacement" in results2[0].reason

    def test_reset_clears_state(self):
        """reset() clears all pending absorptions."""
        validator = AbsorptionValidator()
        validator.record_absorption(_make_ohlc(high=100.5, low=99.5), "LONG")
        validator.record_absorption(_make_ohlc(high=99.0, low=98.0), "SHORT")

        validator.reset()

        assert len(validator._pending_absorptions) == 0

    def test_multiple_absorptions_tracked(self):
        """record_absorption() tracks multiple events simultaneously."""
        validator = AbsorptionValidator()
        validator.record_absorption(_make_ohlc(high=100.5, low=99.5), "LONG")
        validator.record_absorption(_make_ohlc(high=99.0, low=98.0), "SHORT")

        assert len(validator._pending_absorptions) == 2

    def test_displacement_result_reason(self):
        """Confirmed absorption includes descriptive reason."""
        validator = AbsorptionValidator()
        validator.record_absorption(_make_ohlc(high=100.5, low=99.5), "LONG")

        disp_candle = _make_ohlc(high=101.0, low=100.0)
        results = validator.validate_displacement(disp_candle)

        assert len(results) == 1
        assert "Absorption confirmed" in results[0].reason
        assert "LONG" in results[0].reason

    def test_pending_cleared_after_confirmation(self):
        """Confirmed absorption is removed from pending list."""
        validator = AbsorptionValidator()
        validator.record_absorption(_make_ohlc(high=100.5, low=99.5), "LONG")

        disp_candle = _make_ohlc(high=101.0, low=100.0)
        validator.validate_displacement(disp_candle)

        assert len(validator._pending_absorptions) == 0
