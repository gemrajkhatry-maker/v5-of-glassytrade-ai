"""Unit tests for Opening Type Classifier."""

from decimal import Decimal

import pytest

from app.domain.amt.service.opening_type_classifier import (
    classify_opening_type,
    get_setup_permissions,
)
from app.domain.trading.model.value_objects import OHLC


class TestOpeningTypeClassifier:
    """Tests for classify_opening_type() function."""

    def _make_candle(self, open, high, low, close, volume=1000):
        """Helper to create OHLC candles using the value object."""
        return OHLC.create(
            time="09:15",
            open=float(open),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=float(volume),
        )

    def test_open_drive_strong_bullish(self):
        """OPEN_DRIVE: Strong directional candles away from VA above."""
        # Open just above VAH with small gap, strong drive with high first-candle volume
        candles = [
            self._make_candle(101, 102, 100.5, 101.8, volume=3000),
            self._make_candle(101.8, 103, 101.5, 102.8, volume=1000),
            self._make_candle(102.8, 104, 102.5, 103.5, volume=1000),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=101.0,
            prior_vah=100.0,
            prior_val=90.0,
            prior_close=100.0,
        )

        assert result.opening_type == "OPEN_DRIVE"
        assert result.direction == "LONG"
        assert "MOMENTUM" in result.allowed_setups
        assert "MEAN_REVERSION" in result.blocked_setups

    def test_open_drive_strong_bearish(self):
        """OPEN_DRIVE: Strong directional candles away from VA below."""
        # Open just below VAL with small gap, strong drive down with high first-candle volume
        candles = [
            self._make_candle(89, 89.5, 88, 88.2, volume=3000),
            self._make_candle(88.2, 88.3, 87, 87.1, volume=1000),
            self._make_candle(87.1, 87.2, 86, 86.3, volume=1000),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=89.0,
            prior_vah=100.0,
            prior_val=90.0,
            prior_close=90.0,
        )

        assert result.opening_type == "OPEN_DRIVE"
        assert result.direction == "SHORT"

    def test_open_test_drive(self):
        """OPEN_TEST_DRIVE: Probe VA extreme then rejection and reversal."""
        # Open inside VA, probe above VAH, then reject and reverse downward
        candles = [
            self._make_candle(95, 101, 94, 99, volume=2000),
            self._make_candle(99, 100, 98, 97, volume=1500),
            self._make_candle(97, 98, 96, 95, volume=1200),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=95.0,
            prior_vah=100.0,
            prior_val=90.0,
            prior_close=95.0,
        )

        assert result.opening_type == "OPEN_TEST_DRIVE"
        assert result.direction == "SHORT"
        assert "FAILED_AUCTION" in result.allowed_setups

    def test_open_rejection_reverse(self):
        """OPEN_REJECTION_REVERSE: Gap outside VA with immediate rejection."""
        candles = [
            self._make_candle(105, 107, 104, 99, volume=3000),
            self._make_candle(99, 100, 98, 98.5, volume=2000),
            self._make_candle(98.5, 99, 97, 97.5, volume=1500),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=105.0,
            prior_vah=100.0,
            prior_val=90.0,
            prior_close=99.0,
        )

        assert result.opening_type == "OPEN_REJECTION_REVERSE"
        assert result.direction == "SHORT"
        assert "FAILED_AUCTION" in result.allowed_setups
        assert "MEAN_REVERSION" in result.allowed_setups
        assert "MOMENTUM" in result.blocked_setups

    def test_open_auction(self):
        """OPEN_AUCTION: Open inside prior VA, rotational price action."""
        candles = [
            self._make_candle(95, 96, 94, 95.5, volume=1000),
            self._make_candle(95.5, 96.5, 94.5, 95, volume=900),
            self._make_candle(95, 96, 94, 95.2, volume=800),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=95.0,
            prior_vah=100.0,
            prior_val=90.0,
            prior_close=95.0,
        )

        assert result.opening_type == "OPEN_AUCTION"
        assert result.direction == ""
        assert len(result.blocked_setups) == 0
        assert result.gate_overrides.get("allow_all_setups") is True

    def test_open_auction_oor(self):
        """OPEN_AUCTION_OOR: Gap outside VA, not filling, developing new value."""
        candles = [
            self._make_candle(120, 122, 119, 121, volume=1000),
            self._make_candle(121, 123, 120, 121.5, volume=900),
            self._make_candle(121.5, 122.5, 121, 121.8, volume=800),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=120.0,
            prior_vah=100.0,
            prior_val=90.0,
            prior_close=100.0,
        )

        assert result.opening_type == "OPEN_AUCTION_OOR"
        assert "MOMENTUM" in result.allowed_setups
        assert "FAILED_AUCTION" in result.allowed_setups
        assert "AAA" in result.blocked_setups

    def test_gap_fill(self):
        """GAP_FILL: Gap open that fills prior session close."""
        candles = [
            self._make_candle(105, 106, 99, 100, volume=3000),
            self._make_candle(100, 101, 99.5, 100.5, volume=2000),
            self._make_candle(100.5, 101, 100, 100.2, volume=1500),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=105.0,
            prior_vah=100.0,
            prior_val=90.0,
            prior_close=100.0,
        )

        assert result.opening_type == "GAP_FILL"
        assert "MEAN_REVERSION" in result.allowed_setups
        assert "MOMENTUM" in result.blocked_setups

    def test_insufficient_data_empty_candles(self):
        """Empty candles list returns UNKNOWN with all setups allowed."""
        result = classify_opening_type(
            candles=[],
            open_price=100.0,
            prior_vah=100.0,
            prior_val=90.0,
        )

        assert result.opening_type == "UNKNOWN"
        assert result.confidence == 0.0
        assert "AAA" in result.allowed_setups

    def test_insufficient_data_single_candle(self):
        """A single candle returns UNKNOWN since at least 2 are required."""
        candles = [
            self._make_candle(95, 96, 94, 95.5, volume=1000),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=95.0,
            prior_vah=100.0,
            prior_val=90.0,
        )

        assert result.opening_type == "UNKNOWN"
        assert result.confidence == 0.0

    def test_invalid_va_values(self):
        """Non-positive VA values return UNKNOWN."""
        candles = [
            self._make_candle(95, 96, 94, 95.5, volume=1000),
            self._make_candle(95.5, 96.5, 94.5, 95, volume=900),
        ]

        result = classify_opening_type(
            candles=candles,
            open_price=95.0,
            prior_vah=0,
            prior_val=90.0,
        )

        assert result.opening_type == "UNKNOWN"


class TestSetupPermissions:
    """Tests for get_setup_permissions() function."""

    def test_open_drive_permissions(self):
        """OPEN_DRIVE allows MOMENTUM only, blocks MEAN_REVERSION and AAA."""
        perms = get_setup_permissions("OPEN_DRIVE")
        assert perms["allowed"] == ("MOMENTUM",)
        assert "MEAN_REVERSION" in perms["blocked"]
        assert "AAA" in perms["blocked"]
        assert perms["mr_block_minutes"] == 60

    def test_open_test_drive_permissions(self):
        """OPEN_TEST_DRIVE allows FAILED_AUCTION, MEAN_REVERSION, AAA."""
        perms = get_setup_permissions("OPEN_TEST_DRIVE")
        assert "FAILED_AUCTION" in perms["allowed"]
        assert "MEAN_REVERSION" in perms["allowed"]
        assert "AAA" in perms["allowed"]
        assert "MOMENTUM" in perms["blocked"]

    def test_open_rejection_reverse_permissions(self):
        """OPEN_REJECTION_REVERSE allows FAILED_AUCTION, MEAN_REVERSION."""
        perms = get_setup_permissions("OPEN_REJECTION_REVERSE")
        assert "FAILED_AUCTION" in perms["allowed"]
        assert "MEAN_REVERSION" in perms["allowed"]
        assert "MOMENTUM" in perms["blocked"]

    def test_open_auction_permissions(self):
        """OPEN_AUCTION allows all setups with no blocks."""
        perms = get_setup_permissions("OPEN_AUCTION")
        assert len(perms["allowed"]) == 4
        assert len(perms["blocked"]) == 0

    def test_open_auction_oor_permissions(self):
        """OPEN_AUCTION_OOR allows MOMENTUM and FAILED_AUCTION, blocks AAA."""
        perms = get_setup_permissions("OPEN_AUCTION_OOR")
        assert "MOMENTUM" in perms["allowed"]
        assert "FAILED_AUCTION" in perms["allowed"]
        assert "AAA" in perms["blocked"]

    def test_gap_fill_permissions(self):
        """GAP_FILL allows MEAN_REVERSION and AAA, blocks MOMENTUM."""
        perms = get_setup_permissions("GAP_FILL")
        assert "MEAN_REVERSION" in perms["allowed"]
        assert "AAA" in perms["allowed"]
        assert "MOMENTUM" in perms["blocked"]
        assert perms["mr_block_minutes"] == 45

    def test_unknown_permissions(self):
        """UNKNOWN type allows all setups as default."""
        perms = get_setup_permissions("UNKNOWN")
        assert len(perms["allowed"]) == 4
        assert len(perms["blocked"]) == 0

    def test_unrecognized_type_defaults_to_unknown(self):
        """An unrecognized opening type returns UNKNOWN permissions."""
        perms = get_setup_permissions("NONEXISTENT_TYPE")
        assert len(perms["allowed"]) == 4
        assert len(perms["blocked"]) == 0
