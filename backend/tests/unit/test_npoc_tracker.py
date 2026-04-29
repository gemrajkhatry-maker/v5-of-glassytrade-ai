"""Unit tests for NPOC Tracker — Naked POC tracking service."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call

from app.domain.ports.npoc import INPOC, NPOCRecord, NPOCResult
from app.domain.fabio_ai.services.npoc_tracker import NPOCTracker


class MockStorage:
    """Mock storage port for testing NPOCTracker."""

    def __init__(self):
        self.saved_npocs: list[tuple[str, str, float]] = []
        self.filled_npocs: list[tuple[str, str, str]] = []
        self._active_records: list[dict] = []

    def save_npoc(self, underlying: str, session_date: str, poc_price: float) -> None:
        self.saved_npocs.append((underlying, session_date, poc_price))

    def mark_npoc_filled(self, underlying: str, session_date: str, filled_at: str) -> None:
        self.filled_npocs.append((underlying, session_date, filled_at))

    def get_active_npocs(self, underlying: str) -> list[dict]:
        return [r for r in self._active_records if r["underlying"] == underlying]


class TestNPOCRecord:
    """Test NPOCRecord dataclass."""

    def test_frozen_dataclass(self):
        record = NPOCRecord(
            price=24500.0,
            session_date="2026-03-19",
            underlying="NIFTY",
            is_filled=False,
            filled_at=None,
        )
        assert record.price == 24500.0
        assert record.session_date == "2026-03-19"
        assert record.underlying == "NIFTY"
        assert record.is_filled is False
        assert record.filled_at is None

        # Frozen — should raise on mutation
        with pytest.raises(AttributeError):
            record.price = 24600.0  # type: ignore[misc]


class TestNPOCResult:
    """Test NPOCResult dataclass."""

    def test_empty_result(self):
        result = NPOCResult(
            nearest_above=None,
            nearest_below=None,
            all_active=(),
        )
        assert result.nearest_above is None
        assert result.nearest_below is None
        assert len(result.all_active) == 0

    def test_with_values(self):
        above = NPOCRecord(24600.0, "2026-03-19", "NIFTY", False)
        below = NPOCRecord(24400.0, "2026-03-18", "NIFTY", False)
        result = NPOCResult(
            nearest_above=above,
            nearest_below=below,
            all_active=(above, below),
        )
        assert result.nearest_above.price == 24600.0
        assert result.nearest_below.price == 24400.0
        assert len(result.all_active) == 2


class TestNPOCTracker:
    """Test NPOCTracker domain service."""

    def setup_method(self):
        self.storage = MockStorage()
        self.tracker = NPOCTracker(storage_port=self.storage)

    # ------------------------------------------------------------------
    # add_session_poc
    # ------------------------------------------------------------------

    def test_add_session_poc_creates_record(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)

        # Check in-memory cache
        npocs = self.tracker.active_npocs.get("NIFTY", [])
        assert len(npocs) == 1
        assert npocs[0].price == 24500.0
        assert npocs[0].session_date == "2026-03-19"
        assert npocs[0].is_filled is False

        # Check storage was called
        assert len(self.storage.saved_npocs) == 1
        assert self.storage.saved_npocs[0] == ("NIFTY", "2026-03-19", 24500.0)

    def test_add_multiple_sessions(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-17", 24400.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-18", 24550.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)

        npocs = self.tracker.active_npocs.get("NIFTY", [])
        assert len(npocs) == 3
        assert len(self.storage.saved_npocs) == 3

    def test_add_duplicate_session_skipped(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24600.0)  # Same date

        npocs = self.tracker.active_npocs.get("NIFTY", [])
        assert len(npocs) == 1
        assert npocs[0].price == 24500.0  # Original price preserved

    def test_add_different_underlyings(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)
        self.tracker.add_session_poc("BANKNIFTY", "2026-03-19", 51000.0)

        assert len(self.tracker.active_npocs["NIFTY"]) == 1
        assert len(self.tracker.active_npocs["BANKNIFTY"]) == 1

    # ------------------------------------------------------------------
    # check_and_fill
    # ------------------------------------------------------------------

    def test_check_and_fill_fills_within_zone(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)
        tick_size = 0.05
        zone = tick_size * 2  # 0.10

        # Price exactly at NPOC
        filled = self.tracker.check_and_fill("NIFTY", 24500.0, tick_size)
        assert "2026-03-19" in filled
        assert len(self.tracker.active_npocs.get("NIFTY", [])) == 0

    def test_check_and_fill_fills_within_2_ticks(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)
        tick_size = 0.05

        # Price 1 tick above
        filled = self.tracker.check_and_fill("NIFTY", 24500.05, tick_size)
        assert "2026-03-19" in filled

    def test_check_and_fill_fills_at_boundary(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)
        tick_size = 0.05
        zone = tick_size * 2  # 0.10

        # Price exactly 2 ticks away
        filled = self.tracker.check_and_fill("NIFTY", 24500.10, tick_size)
        assert "2026-03-19" in filled

    def test_check_and_fill_does_not_fill_outside_zone(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)
        tick_size = 0.05
        zone = tick_size * 2  # 0.10

        # Price 3 ticks away — should NOT fill
        filled = self.tracker.check_and_fill("NIFTY", 24500.15, tick_size)
        assert len(filled) == 0
        assert len(self.tracker.active_npocs.get("NIFTY", [])) == 1

    def test_check_and_fill_multiple_npocs(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-17", 24400.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-18", 24500.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24600.0)
        tick_size = 0.05

        # Price near 24500 — should fill only that one
        filled = self.tracker.check_and_fill("NIFTY", 24500.05, tick_size)
        assert "2026-03-18" in filled
        assert len(filled) == 1
        assert len(self.tracker.active_npocs.get("NIFTY", [])) == 2

    def test_check_and_fill_storage_called(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)
        self.tracker.check_and_fill("NIFTY", 24500.0, 0.05)

        assert len(self.storage.filled_npocs) == 1
        assert self.storage.filled_npocs[0][0] == "NIFTY"
        assert self.storage.filled_npocs[0][1] == "2026-03-19"

    def test_check_and_fill_empty_underlying(self):
        filled = self.tracker.check_and_fill("UNKNOWN", 24500.0, 0.05)
        assert len(filled) == 0

    # ------------------------------------------------------------------
    # get_active_npocs
    # ------------------------------------------------------------------

    def test_get_active_npocs_returns_nearest_above_and_below(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-17", 24300.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-18", 24400.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24600.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-20", 24700.0)

        result = self.tracker.get_active_npocs("NIFTY", 24500.0)

        assert result.nearest_above is not None
        assert result.nearest_above.price == 24600.0
        assert result.nearest_below is not None
        assert result.nearest_below.price == 24400.0

    def test_get_active_npocs_only_above(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24600.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-20", 24700.0)

        result = self.tracker.get_active_npocs("NIFTY", 24500.0)

        assert result.nearest_above is not None
        assert result.nearest_above.price == 24600.0
        assert result.nearest_below is None

    def test_get_active_npocs_only_below(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24400.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-20", 24300.0)

        result = self.tracker.get_active_npocs("NIFTY", 24500.0)

        assert result.nearest_above is None
        assert result.nearest_below is not None
        assert result.nearest_below.price == 24400.0

    def test_get_active_npocs_empty(self):
        result = self.tracker.get_active_npocs("NIFTY", 24500.0)

        assert result.nearest_above is None
        assert result.nearest_below is None
        assert len(result.all_active) == 0

    def test_get_active_npocs_excludes_filled(self):
        self.tracker.add_session_poc("NIFTY", "2026-03-18", 24400.0)
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24600.0)

        # Fill the one below
        self.tracker.check_and_fill("NIFTY", 24400.0, 0.05)

        result = self.tracker.get_active_npocs("NIFTY", 24500.0)

        assert result.nearest_below is None  # Filled, so excluded
        assert result.nearest_above is not None
        assert result.nearest_above.price == 24600.0

    def test_get_active_npocs_lookback_limit(self):
        # Add 10 NPOCs
        for i in range(10):
            self.tracker.add_session_poc("NIFTY", f"2026-03-{10+i:02d}", 24000.0 + i * 100)

        result = self.tracker.get_active_npocs("NIFTY", 24500.0, lookback_days=3)

        # Should only return 3 most recent
        assert len(result.all_active) == 3

    # ------------------------------------------------------------------
    # load_from_storage
    # ------------------------------------------------------------------

    def test_load_from_storage(self):
        self.storage._active_records = [
            {"poc_price": 24400.0, "session_date": "2026-03-18", "underlying": "NIFTY", "is_filled": 0, "filled_at": None},
            {"poc_price": 24600.0, "session_date": "2026-03-19", "underlying": "NIFTY", "is_filled": 0, "filled_at": None},
        ]

        self.tracker.load_from_storage("NIFTY")

        npocs = self.tracker.active_npocs.get("NIFTY", [])
        assert len(npocs) == 2
        assert npocs[0].price == 24400.0
        assert npocs[1].price == 24600.0

    def test_load_from_storage_empty(self):
        self.tracker.load_from_storage("NIFTY")
        assert len(self.tracker.active_npocs.get("NIFTY", [])) == 0

    # ------------------------------------------------------------------
    # Integration: full lifecycle
    # ------------------------------------------------------------------

    def test_full_lifecycle(self):
        """Test: add POCs -> check fills -> get targets -> verify persistence."""
        # Session 1: Add NPOC
        self.tracker.add_session_poc("NIFTY", "2026-03-17", 24300.0)

        # Session 2: Add another NPOC
        self.tracker.add_session_poc("NIFTY", "2026-03-18", 24400.0)

        # Session 3: Price moves — fill 24400
        filled = self.tracker.check_and_fill("NIFTY", 24400.0, 0.05)
        assert "2026-03-18" in filled

        # Get targets for new trade
        result = self.tracker.get_active_npocs("NIFTY", 24350.0)
        assert result.nearest_above is None  # 24400 was filled
        assert result.nearest_below is not None
        assert result.nearest_below.price == 24300.0

        # Session 4: Add new NPOC
        self.tracker.add_session_poc("NIFTY", "2026-03-19", 24500.0)

        # Get targets again
        result = self.tracker.get_active_npocs("NIFTY", 24350.0)
        assert result.nearest_above is not None
        assert result.nearest_above.price == 24500.0
        assert result.nearest_below is not None
        assert result.nearest_below.price == 24300.0

    # ------------------------------------------------------------------
    # INPOC interface compliance
    # ------------------------------------------------------------------

    def test_implements_npoc_port(self):
        assert isinstance(self.tracker, INPOC)

    def test_interface_methods_exist(self):
        assert hasattr(self.tracker, "add_session_poc")
        assert hasattr(self.tracker, "check_and_fill")
        assert hasattr(self.tracker, "get_active_npocs")
        assert hasattr(self.tracker, "load_from_storage")
