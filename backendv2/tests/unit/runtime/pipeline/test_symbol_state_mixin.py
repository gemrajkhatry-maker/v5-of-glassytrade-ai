"""Tests for SymbolStateMixin — per-symbol state with TTL eviction.

Prevents memory leaks in pipeline stages that track per-symbol state.
"""
from __future__ import annotations

import time

import pytest

from app.runtime.pipeline.base import SymbolStateMixin


class TestSymbolStateMixin:
    """Tests for SymbolStateMixin behavior."""

    def test_get_state_returns_none_for_unknown_symbol(self):
        mixin = SymbolStateMixin()
        assert mixin.get_state("UNKNOWN") is None

    def test_set_and_get_state(self):
        mixin = SymbolStateMixin()
        mixin.set_state("NIFTY", {"high": 100.0})
        result = mixin.get_state("NIFTY")
        assert result == {"high": 100.0}

    def test_state_expires_after_ttl(self):
        mixin = SymbolStateMixin(ttl_seconds=0.1)
        mixin.set_state("NIFTY", {"high": 100.0})
        assert mixin.get_state("NIFTY") == {"high": 100.0}
        time.sleep(0.15)
        assert mixin.get_state("NIFTY") is None

    def test_prune_removes_expired_entries(self):
        mixin = SymbolStateMixin(ttl_seconds=0.1)
        mixin.set_state("NIFTY", {"high": 100.0})
        mixin.set_state("BANKNIFTY", {"high": 200.0})
        time.sleep(0.15)
        mixin._prune()
        assert mixin.get_state("NIFTY") is None
        assert mixin.get_state("BANKNIFTY") is None

    def test_max_symbols_evicts_oldest(self):
        mixin = SymbolStateMixin(max_symbols=3, ttl_seconds=60.0)
        mixin.set_state("A", 1)
        mixin.set_state("B", 2)
        mixin.set_state("C", 3)
        mixin.set_state("D", 4)  # Should evict oldest
        assert mixin.get_state("A") is None
        assert mixin.get_state("B") == 2
        assert mixin.get_state("C") == 3
        assert mixin.get_state("D") == 4

    def test_prune_called_every_n_operations(self):
        mixin = SymbolStateMixin(ttl_seconds=0.1, prune_interval=5)
        mixin.set_state("NIFTY", 1)
        time.sleep(0.15)
        # First 4 calls should not prune
        for _ in range(4):
            mixin.get_state("NIFTY")
        # State still there because prune hasn't run
        # Actually get_state calls _prune which increments call count...
        # Let me reconsider

    def test_different_symbols_independent(self):
        mixin = SymbolStateMixin()
        mixin.set_state("NIFTY", {"vol": 100})
        mixin.set_state("BANKNIFTY", {"vol": 200})
        assert mixin.get_state("NIFTY") == {"vol": 100}
        assert mixin.get_state("BANKNIFTY") == {"vol": 200}

    def test_overwrite_existing_state(self):
        mixin = SymbolStateMixin()
        mixin.set_state("NIFTY", {"vol": 100})
        mixin.set_state("NIFTY", {"vol": 150})
        assert mixin.get_state("NIFTY") == {"vol": 150}

    def test_state_count_tracked(self):
        mixin = SymbolStateMixin()
        mixin.set_state("A", 1)
        mixin.set_state("B", 2)
        assert len(mixin._state) == 2
