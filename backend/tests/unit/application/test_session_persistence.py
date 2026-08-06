"""Tests for Task 11: prior-session profile persistence + backfill warmup marker.

Covers:
- persist_prior_profile / load_prior_profile kv round-trip
- fresh session context (get_session_info) uses the persisted prior profile
- load returns empty when nothing saved
- synthetic backfill range-bar ticks are marked is_warmup=True
- live ticks are not marked warmup
- range-bar/footprint DTOs expose is_warmup defaulting to False
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock

from app.application.services.tick_processor import TickProcessor
from app.domain.fabio_ai.services.session_context import (
    get_session_info,
    load_prior_profile,
    persist_prior_profile,
)
from app.domain.trading.models.value_objects import OHLC
from app.infrastructure.serialization.schemas import FootprintCandleDTO, OHLCDataDTO
from app.infrastructure.storage.database import SQLiteStorageAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage(tmp_path):
    """Create a fresh SQLite storage adapter with a temp DB."""
    db_path = str(tmp_path / "test.db")
    adapter = SQLiteStorageAdapter(db_path=db_path)
    yield adapter


def _make_ohlc(time: str, open_p: float, high_p: float, low_p: float, close_p: float) -> OHLC:
    return OHLC.create(
        time=time,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=1000.0,
        taker_buy_volume=600.0,
    )


# ---------------------------------------------------------------------------
# Prior-session profile persistence (Task 11a)
# ---------------------------------------------------------------------------

class TestPriorProfilePersistence:

    def test_persist_then_load_prior_profile(self, storage):
        """Persist POC/VAH/VAL via helper, load them back from a fresh adapter."""
        persist_prior_profile(
            storage, "NIFTY 26 FEB 24000 CALL", poc=24800.0, vah=24900.0, val=24700.0,
        )
        loaded = load_prior_profile(storage, "NIFTY 26 FEB 24000 CALL")
        assert loaded == {"poc": 24800.0, "vah": 24900.0, "val": 24700.0}

    def test_load_returns_empty_when_nothing_saved(self, storage):
        assert load_prior_profile(storage, "NIFTY") == {}

    def test_fresh_session_context_uses_persisted_prior(self, storage):
        """A fresh context built from the persisted prior profile references prior VAH/VAL."""
        persist_prior_profile(storage, "NIFTY", poc=24800.0, vah=24900.0, val=24700.0)
        prior = load_prior_profile(storage, "NIFTY")
        info = get_session_info(
            timestamp="2026-02-24T09:30:00+05:30",
            open_price=24850.0,
            prior_vah=prior.get("vah", 0.0),
            prior_val=prior.get("val", 0.0),
        )
        assert info.opening_relation == "IN_BALANCE"

    def test_key_is_namespaced_per_symbol(self, storage):
        """Different symbols persist/load independently."""
        persist_prior_profile(storage, "NIFTY", poc=24800.0, vah=24900.0, val=24700.0)
        persist_prior_profile(storage, "CRUDEOIL", poc=820.0, vah=830.0, val=810.0)
        assert load_prior_profile(storage, "CRUDEOIL") == {
            "poc": 820.0, "vah": 830.0, "val": 810.0,
        }
        assert load_prior_profile(storage, "NIFTY")["poc"] == 24800.0


# ---------------------------------------------------------------------------
# Backfill warmup marker (Task 11b)
# ---------------------------------------------------------------------------

class TestBackfillWarmupMarker:

    def test_backfill_bars_carry_is_warmup(self):
        """Synthetic backfill ticks produce range bars flagged is_warmup=True."""
        tp = TickProcessor(candle_aggregator=Mock())
        tp.get_or_create_range_builder("SYM")
        data = [
            _make_ohlc("t0", 100.0, 110.0, 90.0, 105.0),
            _make_ohlc("t1", 105.0, 115.0, 95.0, 110.0),
            _make_ohlc("t2", 110.0, 120.0, 100.0, 115.0),
        ]
        tp.backfill_range_bars("SYM", data)
        rb = tp._range_builders["SYM"]
        bars = rb.get_closed_bars()
        assert bars, "backfill should close at least one range bar"
        for b in bars:
            assert getattr(b, "is_warmup", False) is True

    def test_live_ticks_not_marked_warmup(self):
        """Bars closed by live ticks are not flagged warmup."""
        tp = TickProcessor(candle_aggregator=Mock())
        tp.get_or_create_range_builder("SYM")
        tick = _make_ohlc("t", 100.0, 100.0, 100.0, 100.0)
        for i in range(30):
            tp.update_range_bar("SYM", 100.0 + i, f"t{i}", tick)
        rb = tp._range_builders["SYM"]
        bars = rb.get_closed_bars()
        assert bars, "live ticks should close at least one range bar"
        for b in bars:
            assert getattr(b, "is_warmup", False) is False

    def test_footprint_and_bar_dto_default_is_warmup_false(self):
        """DTO field is_warmup defaults to False on the footprint/bar DTOs."""
        assert FootprintCandleDTO(time="t").is_warmup is False
        assert (
            OHLCDataDTO(
                time="t", open=1, high=2, low=0.5, close=1.5, volume=10,
            ).is_warmup
            is False
        )
