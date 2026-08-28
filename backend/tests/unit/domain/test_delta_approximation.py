"""Tests for the dhan_adapter _delta_proxy candle delta approximation."""

from __future__ import annotations

from app.infrastructure.adapters.dhan_adapter import _delta_proxy


class TestDhanDeltaProxy:
    """Tests for the dhan_adapter _delta_proxy function."""

    def test_strong_bullish(self):
        delta = _delta_proxy(100, 110, 100, 109, 1000)
        assert delta > 0

    def test_strong_bearish(self):
        # Bearish: open=110, close=101 (close < open)
        delta = _delta_proxy(110, 110, 100, 101, 1000)
        assert delta < 0

    def test_doji_reduced(self):
        delta = _delta_proxy(100, 110, 100, 100.1, 1000)
        strong = _delta_proxy(100, 110, 100, 109, 1000)
        assert abs(delta) < abs(strong)
