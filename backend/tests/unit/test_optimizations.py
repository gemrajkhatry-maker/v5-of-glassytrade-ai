"""Optimization Tests — candle cap, delta compression, LLM semaphore.

Validates the performance optimizations added to the trading system.
"""



# ---------------------------------------------------------------------------
# 1. _compute_delta function (WebSocket delta compression)
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

