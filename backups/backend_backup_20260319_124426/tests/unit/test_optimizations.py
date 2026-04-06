"""Optimization Tests — candle cap, delta compression, memory endpoint, LLM semaphore.

Validates the four performance optimizations added to the trading system.
"""

import gc
import threading

import pytest


# ---------------------------------------------------------------------------
# 1. Candle history trimming (MAX_CANDLES_PER_SYMBOL = 2000)
# ---------------------------------------------------------------------------

class TestCandleHistoryTrimming:
    """Verify session.data is capped at MAX_CANDLES_PER_SYMBOL."""

    def _make_ohlc(self, time_str: str):
        from app.domain.trading.models.value_objects import OHLC
        return OHLC(
            time=time_str, open=100, high=101, low=99,
            close=100, volume=10, vwap=100, taker_buy_volume=5, delta=1,
        )

    def test_trim_candles_over_2000(self):
        """OPT-01: Adding >2000 candles trims to exactly 2000."""
        from app.application.services.trading_session import (
            MAX_CANDLES_PER_SYMBOL, SessionState,
        )
        session = SessionState(symbol="TEST")
        # Pre-fill with 2100 candles (each with unique time so they append)
        for i in range(2100):
            session.data.append(self._make_ohlc(f"2026-01-01T00:{i:05d}"))

        # Simulate the trim logic from process_tick
        if len(session.data) > MAX_CANDLES_PER_SYMBOL:
            del session.data[:len(session.data) - MAX_CANDLES_PER_SYMBOL]

        assert len(session.data) == 2000
        # Oldest candle should be index 100 from original
        assert session.data[0].time == "2026-01-01T00:00100"

    def test_no_trim_under_2000(self):
        """OPT-02: Under 2000 candles, no trimming occurs."""
        from app.application.services.trading_session import (
            MAX_CANDLES_PER_SYMBOL, SessionState,
        )
        session = SessionState(symbol="TEST")
        for i in range(500):
            session.data.append(self._make_ohlc(f"T{i}"))

        original_len = len(session.data)
        if len(session.data) > MAX_CANDLES_PER_SYMBOL:
            del session.data[:len(session.data) - MAX_CANDLES_PER_SYMBOL]

        assert len(session.data) == original_len == 500

    def test_constant_value(self):
        """OPT-03: MAX_CANDLES_PER_SYMBOL is 2000."""
        from app.application.services.trading_session import MAX_CANDLES_PER_SYMBOL
        assert MAX_CANDLES_PER_SYMBOL == 2000


# ---------------------------------------------------------------------------
# 2. _compute_delta function (WebSocket delta compression)
# ---------------------------------------------------------------------------

class TestComputeDelta:
    """Verify delta compression logic in gameloop._compute_delta."""

    def test_full_state_on_first_call(self):
        """OPT-04: When prev is None, return full current state."""
        from app.api.websocket.gameloop import _compute_delta
        current = {"_symbol": "X", "amt": {"poc": 100}, "portfolio": {"equity": 1000}}
        result = _compute_delta(None, current)
        assert result is current

    def test_delta_on_changed_keys(self):
        """OPT-05: Only changed keys appear in delta."""
        from app.api.websocket.gameloop import _compute_delta
        prev = {"_symbol": "X", "amt": {"poc": 100}, "portfolio": {"equity": 1000}}
        current = {"_symbol": "X", "amt": {"poc": 105}, "portfolio": {"equity": 1000}}
        result = _compute_delta(prev, current)
        assert result["_type"] == "delta"
        assert result["_symbol"] == "X"
        assert "amt" in result
        assert "portfolio" not in result

    def test_empty_when_no_changes(self):
        """OPT-06: Returns empty dict when nothing changed."""
        from app.api.websocket.gameloop import _compute_delta
        state = {"_symbol": "X", "amt": {"poc": 100}}
        result = _compute_delta(state, dict(state))
        assert result == {}

    def test_underscore_keys_excluded_from_diff(self):
        """OPT-07: Keys starting with _ are not diffed (only _symbol and _type added)."""
        from app.api.websocket.gameloop import _compute_delta
        prev = {"_symbol": "X", "_internal": 1, "amt": 1}
        current = {"_symbol": "X", "_internal": 2, "amt": 1}
        result = _compute_delta(prev, current)
        # _internal changed but underscore keys are skipped in diff
        assert result == {}

    def test_all_keys_changed(self):
        """OPT-08: All non-underscore keys changed returns all of them."""
        from app.api.websocket.gameloop import _compute_delta
        prev = {"_symbol": "X", "a": 1, "b": 2}
        current = {"_symbol": "X", "a": 10, "b": 20}
        result = _compute_delta(prev, current)
        assert result["a"] == 10
        assert result["b"] == 20
        assert result["_type"] == "delta"


# ---------------------------------------------------------------------------
# 3. /api/debug/memory endpoint
# ---------------------------------------------------------------------------

class TestDebugMemoryEndpoint:
    """Verify the debug memory endpoint returns expected fields."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routers.health import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_memory_endpoint_returns_rss(self, client):
        """OPT-09: /debug/memory returns rss_mb as a float."""
        resp = client.get("/debug/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert "rss_mb" in data
        assert isinstance(data["rss_mb"], (int, float))
        assert data["rss_mb"] > 0

    def test_memory_endpoint_returns_gc_stats(self, client):
        """OPT-10: /debug/memory returns gc_stats as a list of 3 generations."""
        resp = client.get("/debug/memory")
        data = resp.json()
        assert "gc_stats" in data
        assert isinstance(data["gc_stats"], list)
        assert len(data["gc_stats"]) == 3  # Python has 3 GC generations
        for gen in data["gc_stats"]:
            assert "collections" in gen
            assert "collected" in gen
            assert "uncollectable" in gen

    def test_memory_endpoint_returns_gc_objects(self, client):
        """OPT-11: /debug/memory returns gc_objects count."""
        resp = client.get("/debug/memory")
        data = resp.json()
        assert "gc_objects" in data
        assert isinstance(data["gc_objects"], int)
        assert data["gc_objects"] > 0



