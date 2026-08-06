"""Tests for Task 11: prior-session profile persistence + DTO warmup default.

Covers:
- persist_prior_profile / load_prior_profile kv round-trip
- fresh session context (get_session_info) uses the persisted prior profile
- load returns empty when nothing saved
- footprint/OHLC DTOs expose is_warmup defaulting to False
"""

from __future__ import annotations

import pytest

from app.domain.fabio_ai.services.session_context import (
    get_session_info,
    load_prior_profile,
    persist_prior_profile,
)
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
# DTO warmup default (Task 11b)
# ---------------------------------------------------------------------------

class TestDTOWarmupDefault:

    def test_footprint_and_bar_dto_default_is_warmup_false(self):
        """DTO field is_warmup defaults to False on the footprint/bar DTOs."""
        assert FootprintCandleDTO(time="t").is_warmup is False
        assert (
            OHLCDataDTO(
                time="t", open=1, high=2, low=0.5, close=1.5, volume=10,
            ).is_warmup
            is False
        )
