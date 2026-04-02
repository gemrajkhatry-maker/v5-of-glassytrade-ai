"""Tests for OpeningTypeClassifier — P0-3 implementation."""

from __future__ import annotations

import pytest
from dataclasses import dataclass

from app.domain.fabio_ai.services.opening_type_classifier import (
    classify_opening_type,
    get_setup_permissions,
    OpeningTypeResult,
)


@dataclass
class MockCandle:
    """Mock OHLC candle for testing."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class TestClassifyOpeningType:
    """Tests for opening type classification."""

    def test_insufficient_data(self):
        """Returns UNKNOWN with less than 2 candles."""
        result = classify_opening_type(
            candles=[MockCandle("09:15", 24800, 24850, 24750, 24820, 1000)],
            open_price=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
        )
        assert result.opening_type == "UNKNOWN"
        assert result.confidence == 0.0

    def test_no_prior_data(self):
        """Returns UNKNOWN when prior VA is invalid."""
        candles = [
            MockCandle("09:15", 24800, 24850, 24750, 24820, 1000),
            MockCandle("09:20", 24820, 24870, 24800, 24850, 1200),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24800.0,
            prior_vah=0.0,
            prior_val=0.0,
        )
        assert result.opening_type == "UNKNOWN"

    def test_open_auction_inside_va(self):
        """Rotational open inside prior VA = OPEN_AUCTION."""
        candles = [
            MockCandle("09:15", 24810, 24830, 24790, 24815, 800),
            MockCandle("09:20", 24815, 24840, 24800, 24825, 900),
            MockCandle("09:25", 24825, 24850, 24810, 24830, 850),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24810.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_close=24810.0,  # Same as open = no gap
        )
        assert result.opening_type == "OPEN_AUCTION"
        assert result.confidence > 0.5
        assert len(result.blocked_setups) == 0
        assert "AAA" in result.allowed_setups
        assert "MEAN_REVERSION" in result.allowed_setups

    def test_open_drive_bullish(self):
        """Strong directional open above VA with volume = OPEN_DRIVE."""
        candles = [
            MockCandle("09:15", 24920, 24980, 24910, 24970, 3000),
            MockCandle("09:20", 24970, 25020, 24960, 25010, 2800),
            MockCandle("09:25", 25010, 25050, 25000, 25040, 2500),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24920.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_close=24800.0,
        )
        assert result.opening_type in ("OPEN_DRIVE", "OPEN_AUCTION_OOR")
        assert result.direction == "LONG"
        assert "MOMENTUM" in result.allowed_setups

    def test_open_rejection_reverse_above(self):
        """Gap above VA, immediate rejection = OPEN_REJECTION_REVERSE."""
        candles = [
            MockCandle("09:15", 24950, 24980, 24880, 24890, 2500),
            MockCandle("09:20", 24890, 24910, 24850, 24860, 2200),
            MockCandle("09:25", 24860, 24880, 24830, 24840, 1800),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24950.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_close=24800.0,
        )
        assert result.opening_type == "OPEN_REJECTION_REVERSE"
        assert result.direction == "SHORT"
        assert "FAILED_AUCTION" in result.allowed_setups
        assert "MOMENTUM" in result.blocked_setups

    def test_open_rejection_reverse_below(self):
        """Gap below VA, immediate rejection = OPEN_REJECTION_REVERSE."""
        candles = [
            MockCandle("09:15", 24650, 24720, 24620, 24710, 2500),
            MockCandle("09:20", 24710, 24750, 24690, 24740, 2200),
            MockCandle("09:25", 24740, 24780, 24730, 24770, 1800),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24650.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_close=24800.0,
        )
        assert result.opening_type == "OPEN_REJECTION_REVERSE"
        assert result.direction == "LONG"

    def test_gap_fill(self):
        """Gap open that fills prior close = GAP_FILL."""
        candles = [
            MockCandle("09:15", 24920, 24940, 24780, 24810, 2000),
            MockCandle("09:20", 24810, 24830, 24790, 24800, 1800),
            MockCandle("09:25", 24800, 24820, 24780, 24795, 1500),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24920.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_close=24800.0,
        )
        # Gap above VA that gets filled — could be GAP_FILL or OPEN_TEST_DRIVE
        assert result.opening_type in (
            "GAP_FILL",
            "OPEN_TEST_DRIVE",
            "OPEN_REJECTION_REVERSE",
        )
        assert result.direction == "SHORT"

    def test_open_test_drive(self):
        """Probe VA extreme, reject, then reversal = OPEN_TEST_DRIVE."""
        candles = [
            MockCandle("09:15", 24800, 24820, 24680, 24700, 2000),
            MockCandle("09:20", 24700, 24750, 24690, 24740, 1800),
            MockCandle("09:25", 24740, 24780, 24730, 24770, 1600),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_close=24800.0,
        )
        assert result.opening_type in ("OPEN_TEST_DRIVE", "OPEN_REJECTION_REVERSE")
        assert result.direction == "LONG"

    def test_open_auction_oor(self):
        """Gap outside VA, developing new value = OPEN_AUCTION_OOR."""
        candles = [
            MockCandle("09:15", 24930, 24960, 24920, 24950, 1500),
            MockCandle("09:20", 24950, 24970, 24940, 24960, 1400),
            MockCandle("09:25", 24960, 24980, 24950, 24970, 1300),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24930.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_close=24800.0,
        )
        assert result.opening_type in ("OPEN_AUCTION_OOR", "OPEN_DRIVE")

    def test_thesis_generated(self):
        """All types generate human-readable thesis."""
        candles = [
            MockCandle("09:15", 24810, 24830, 24790, 24815, 800),
            MockCandle("09:20", 24815, 24840, 24800, 24825, 900),
        ]
        result = classify_opening_type(
            candles=candles,
            open_price=24810.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_close=24800.0,
        )
        assert len(result.thesis) > 20


class TestGetSetupPermissions:
    """Tests for setup permission lookup."""

    def test_open_drive_permissions(self):
        perms = get_setup_permissions("OPEN_DRIVE")
        assert "MOMENTUM" in perms["allowed"]
        assert "MEAN_REVERSION" in perms["blocked"]
        assert perms["mr_block_minutes"] == 60

    def test_open_auction_all_allowed(self):
        perms = get_setup_permissions("OPEN_AUCTION")
        assert len(perms["blocked"]) == 0
        assert "AAA" in perms["allowed"]
        assert "FAILED_AUCTION" in perms["allowed"]

    def test_open_rejection_reverse_permissions(self):
        perms = get_setup_permissions("OPEN_REJECTION_REVERSE")
        assert "FAILED_AUCTION" in perms["allowed"]
        assert "MOMENTUM" in perms["blocked"]

    def test_unknown_allows_all(self):
        perms = get_setup_permissions("UNKNOWN")
        assert len(perms["blocked"]) == 0
        assert len(perms["allowed"]) == 4

    def test_invalid_type_defaults(self):
        perms = get_setup_permissions("INVALID_TYPE")
        assert len(perms["blocked"]) == 0
        assert len(perms["allowed"]) == 4
