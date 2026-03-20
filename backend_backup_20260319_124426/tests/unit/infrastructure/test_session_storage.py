"""Tests for Prior Session Data Flow (Tasks 14-15).

Covers:
- save_session_profile / get_previous_session_profile round-trip
- load returns None when empty
- load returns most recent by date
- classify_gap() from session_context
- opening_inventory_bias() from session_context
- AMT analyzer handles empty prior data gracefully
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.domain.fabio_ai.services.session_context import (
    classify_gap,
    opening_inventory_bias,
)
from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer
from app.domain.trading.models.value_objects import OHLC


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage(tmp_path):
    """Create a fresh SQLite storage adapter with a temp DB."""
    db_path = str(tmp_path / "test.db")
    adapter = SQLiteStorageAdapter(db_path=db_path)
    yield adapter


# ---------------------------------------------------------------------------
# Storage round-trip tests
# ---------------------------------------------------------------------------

class TestSessionStorage:

    def test_save_and_load_session_profile(self, storage):
        """Save a profile dict, load it back, verify fields match."""
        profile = {
            "symbol": "NIFTY",
            "market": "NSE",
            "session_date": "2026-02-24",
            "poc": 24800.0,
            "vah": 24900.0,
            "val": 24700.0,
            "profile_shape": "P",
            "total_volume": 150000.0,
        }
        storage.save_session_profile(profile)
        loaded = storage.get_previous_session_profile("NIFTY", "NSE")

        assert loaded is not None
        assert loaded["poc"] == 24800.0
        assert loaded["vah"] == 24900.0
        assert loaded["val"] == 24700.0
        assert loaded["profile_shape"] == "P"
        assert loaded["session_date"] == "2026-02-24"

    def test_load_returns_none_when_empty(self, storage):
        """No saved profiles -> None."""
        result = storage.get_previous_session_profile("NIFTY", "NSE")
        assert result is None

    def test_load_returns_most_recent(self, storage):
        """Save 2 profiles with different dates, load returns newest."""
        storage.save_session_profile({
            "symbol": "NIFTY",
            "market": "NSE",
            "session_date": "2026-02-23",
            "poc": 24700.0,
            "vah": 24800.0,
            "val": 24600.0,
            "profile_shape": "b",
            "total_volume": 100000.0,
        })
        storage.save_session_profile({
            "symbol": "NIFTY",
            "market": "NSE",
            "session_date": "2026-02-24",
            "poc": 24900.0,
            "vah": 25000.0,
            "val": 24800.0,
            "profile_shape": "D",
            "total_volume": 200000.0,
        })

        loaded = storage.get_previous_session_profile("NIFTY", "NSE")
        assert loaded is not None
        assert loaded["session_date"] == "2026-02-24"
        assert loaded["poc"] == 24900.0

    def test_save_and_query_position_events(self, storage):
        storage.save_position_event({
            "position_id": "P1",
            "symbol": "NIFTY",
            "event_type": "OPENED",
            "event_time": "2026-02-24T09:30:00Z",
            "entry_price": 250.0,
        })
        storage.save_position_event({
            "position_id": "P1",
            "symbol": "NIFTY",
            "event_type": "CLOSED",
            "event_time": "2026-02-24T09:45:00Z",
            "exit_price": 270.0,
        })

        events = storage.query_position_events(position_id="P1")

        assert len(events) == 2
        assert events[0]["event_type"] == "OPENED"
        assert events[0]["event_id"]
        assert events[0]["entry_price"] == 250.0
        assert events[1]["event_type"] == "CLOSED"
        assert events[1]["event_id"]
        assert events[1]["exit_price"] == 270.0


# ---------------------------------------------------------------------------
# Gap classification tests
# ---------------------------------------------------------------------------

class TestClassifyGap:

    def test_gap_type_small(self):
        """Gap < 15% of prior range -> SMALL."""
        # prior range = 200, gap = 20 (10% of range)
        result = classify_gap(open_price=24820.0, prior_close=24800.0, prior_range=200.0)
        assert result == "SMALL"

    def test_gap_type_medium(self):
        """Gap 15-50% of prior range -> MEDIUM."""
        # prior range = 200, gap = 60 (30% of range)
        result = classify_gap(open_price=24860.0, prior_close=24800.0, prior_range=200.0)
        assert result == "MEDIUM"

    def test_gap_type_large(self):
        """Gap >= 50% of prior range -> LARGE."""
        # prior range = 200, gap = 120 (60% of range)
        result = classify_gap(open_price=24920.0, prior_close=24800.0, prior_range=200.0)
        assert result == "LARGE"

    def test_no_gap(self):
        """Negligible gap -> empty string."""
        result = classify_gap(open_price=24800.5, prior_close=24800.0, prior_range=200.0)
        assert result == ""

    def test_invalid_inputs(self):
        """Zero prior close/range -> empty string."""
        assert classify_gap(24800.0, 0, 200.0) == ""
        assert classify_gap(24800.0, 24800.0, 0) == ""


# ---------------------------------------------------------------------------
# Opening inventory bias tests
# ---------------------------------------------------------------------------

class TestOpeningInventoryBias:

    def test_opening_bias_long(self):
        """Open above prior VAH -> LONG_BIAS."""
        result = opening_inventory_bias(25100.0, prior_vah=25000.0, prior_val=24800.0)
        assert result == "LONG_BIAS"

    def test_opening_bias_short(self):
        """Open below prior VAL -> SHORT_BIAS."""
        result = opening_inventory_bias(24700.0, prior_vah=25000.0, prior_val=24800.0)
        assert result == "SHORT_BIAS"

    def test_opening_bias_neutral(self):
        """Open within value area -> NEUTRAL."""
        result = opening_inventory_bias(24900.0, prior_vah=25000.0, prior_val=24800.0)
        assert result == "NEUTRAL"

    def test_invalid_prior_data(self):
        """Zero prior VAH/VAL -> empty string."""
        assert opening_inventory_bias(24900.0, 0.0, 0.0) == ""


# ---------------------------------------------------------------------------
# AMT Analyzer graceful degradation
# ---------------------------------------------------------------------------

class TestAMTNoPriorData:

    def test_no_prior_data_no_crash(self):
        """AMT analyzer handles empty prior data gracefully."""
        analyzer = AMTAnalyzer()
        candles = [
            OHLC(time="2026-02-25T10:00:00", open=100, high=105, low=95, close=102, volume=1000),
            OHLC(time="2026-02-25T10:05:00", open=102, high=106, low=100, close=104, volume=1200),
            OHLC(time="2026-02-25T10:10:00", open=104, high=108, low=101, close=106, volume=1100),
            OHLC(time="2026-02-25T10:15:00", open=106, high=110, low=103, close=108, volume=900),
            OHLC(time="2026-02-25T10:20:00", open=108, high=112, low=105, close=110, volume=1300),
        ]
        # No prior data (defaults) - should not crash
        result = analyzer.analyze(candles)
        assert result.prior_poc == 0.0
        assert result.prior_vah == 0.0
        assert result.prior_val == 0.0
        assert result.gap_type == ""
        assert result.opening_bias == ""

    def test_with_prior_data_populates_fields(self):
        """AMT analyzer populates prior fields when prior data is provided."""
        analyzer = AMTAnalyzer()
        candles = [
            OHLC(time="2026-02-25T10:00:00", open=115, high=120, low=110, close=118, volume=1000),
            OHLC(time="2026-02-25T10:05:00", open=118, high=122, low=114, close=120, volume=1200),
            OHLC(time="2026-02-25T10:10:00", open=120, high=125, low=116, close=122, volume=1100),
            OHLC(time="2026-02-25T10:15:00", open=122, high=126, low=118, close=124, volume=900),
            OHLC(time="2026-02-25T10:20:00", open=124, high=128, low=120, close=126, volume=1300),
        ]
        result = analyzer.analyze(
            candles,
            prior_poc=100.0,
            prior_vah=105.0,
            prior_val=95.0,
        )
        assert result.prior_poc == 100.0
        assert result.prior_vah == 105.0
        assert result.prior_val == 95.0
        # Open=115, prior_vah=105 -> LONG_BIAS
        assert result.opening_bias == "LONG_BIAS"
        # Gap type should be computed (non-empty since open far from prior_poc)
        assert result.gap_type != ""
