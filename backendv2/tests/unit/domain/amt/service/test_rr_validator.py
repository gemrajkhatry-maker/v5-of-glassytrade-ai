"""Tests for RRValidator — Dynamic R:R validation using live Ask price."""

from __future__ import annotations

import pytest

from app.domain.amt.service.rr_validator import RRValidator


class TestValidRR:
    """Tests for valid R:R (>= 1.5)."""

    def test_long_valid_rr(self):
        """LONG with R:R >= 1.5 is valid."""
        validator = RRValidator(min_rr=1.5)
        result = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=6050.0, take_profit=6200.0,
            live_ask=6102.0, is_long=True,
        )
        # Risk = 6102 - 6050 = 52, Reward = 6200 - 6102 = 98
        # R:R = 98/52 = 1.88 >= 1.5
        assert result.valid is True
        assert result.rr_ratio == pytest.approx(98.0 / 52.0, rel=0.01)

    def test_short_valid_rr(self):
        """SHORT with R:R >= 1.5 is valid."""
        validator = RRValidator(min_rr=1.5)
        result = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=6200.0, take_profit=6000.0,
            live_ask=6098.0, is_long=False,
        )
        # Risk = 6200 - 6098 = 102, Reward = 6098 - 6000 = 98
        # R:R = 98/102 = 0.96 < 1.5 — invalid
        # Adjust: make reward larger
        result2 = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=6150.0, take_profit=5950.0,
            live_ask=6098.0, is_long=False,
        )
        # Risk = 6150 - 6098 = 52, Reward = 6098 - 5950 = 148
        # R:R = 148/52 = 2.85 >= 1.5
        assert result2.valid is True


class TestInvalidRR:
    """Tests for invalid R:R (< 1.5)."""

    def test_long_invalid_rr(self):
        """LONG with R:R < 1.5 is invalid."""
        validator = RRValidator(min_rr=1.5)
        result = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=6090.0, take_profit=6110.0,
            live_ask=6102.0, is_long=True,
        )
        # Risk = 6102 - 6090 = 12, Reward = 6110 - 6102 = 8
        # R:R = 8/12 = 0.67 < 1.5
        assert result.valid is False
        assert result.rr_ratio == pytest.approx(8.0 / 12.0, rel=0.01)

    def test_at_threshold_is_valid(self):
        """R:R exactly at threshold is valid."""
        validator = RRValidator(min_rr=1.5)
        # Risk = 100, Reward = 150 => R:R = 1.5
        result = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=6000.0, take_profit=6250.0,
            live_ask=6100.0, is_long=True,
        )
        assert result.valid is True
        assert result.rr_ratio == pytest.approx(1.5, rel=0.01)


class TestZeroRisk:
    """Tests for zero risk (entry == stop loss)."""

    def test_zero_risk_returns_invalid(self):
        """When live_ask == stop_loss for LONG, risk is zero => invalid."""
        validator = RRValidator(min_rr=1.5)
        result = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=6100.0, take_profit=6200.0,
            live_ask=6100.0, is_long=True,
        )
        assert result.valid is False
        assert result.live_risk <= 0

    def test_ask_beyond_stop_loss(self):
        """When live_ask < stop_loss for LONG, risk is negative => invalid."""
        validator = RRValidator(min_rr=1.5)
        result = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=6150.0, take_profit=6200.0,
            live_ask=6100.0, is_long=True,
        )
        assert result.valid is False
        assert "beyond stop loss" in result.reason.lower() or result.live_risk <= 0


class TestInvalidPrices:
    """Tests for invalid price inputs."""

    def test_zero_prices_returns_invalid(self):
        """Zero or negative prices return invalid."""
        validator = RRValidator()
        result = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=0.0, take_profit=6200.0,
            live_ask=6100.0, is_long=True,
        )
        assert result.valid is False
        assert result.rr_ratio == 0.0

    def test_negative_live_ask_returns_invalid(self):
        """Negative live Ask returns invalid."""
        validator = RRValidator()
        result = validator.validate_live_ask(
            entry_ltp=6100.0, stop_loss=6050.0, take_profit=6200.0,
            live_ask=-1.0, is_long=True,
        )
        assert result.valid is False
