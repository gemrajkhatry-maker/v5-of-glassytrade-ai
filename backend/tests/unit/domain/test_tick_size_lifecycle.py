"""Tests for tick_size rounding utilities.

Verifies that:
  - SL/TP rounding utilities work correctly
"""

from __future__ import annotations

import pytest

from quant.contracts.tick_utils import (
    round_to_tick,
    round_down_to_tick,
    round_up_to_tick,
)


class TestTickUtilsRounding:
    """Test tick_size rounding utilities."""

    def test_round_to_tick_nse(self):
        """NSE tick size 0.05 — prices should round to nearest 0.05."""
        assert round_to_tick(100.07, 0.05) == pytest.approx(100.05, abs=1e-9)
        assert round_to_tick(100.08, 0.05) == pytest.approx(100.10, abs=1e-9)
        assert round_to_tick(100.03, 0.05) == pytest.approx(100.05, abs=1e-9)
        assert round_to_tick(100.00, 0.05) == pytest.approx(100.00, abs=1e-9)

    def test_round_to_tick_mcx(self):
        """MCX tick size 1.0 — prices should round to nearest integer."""
        assert round_to_tick(6003.3, 1.0) == pytest.approx(6003.0, abs=1e-9)
        assert round_to_tick(6003.7, 1.0) == pytest.approx(6004.0, abs=1e-9)
        assert round_to_tick(6003.5, 1.0) == pytest.approx(6004.0, abs=1e-9)

    def test_round_down_to_tick(self):
        """For LONG SL — round down to nearest tick."""
        assert round_down_to_tick(6003.7, 1.0) == pytest.approx(6003.0, abs=1e-9)
        assert round_down_to_tick(100.08, 0.05) == pytest.approx(100.05, abs=1e-9)

    def test_round_up_to_tick(self):
        """For LONG TP — round up to nearest tick."""
        assert round_up_to_tick(6003.3, 1.0) == pytest.approx(6004.0, abs=1e-9)
        assert round_up_to_tick(100.07, 0.05) == pytest.approx(100.10, abs=1e-9)

    def test_round_natgas_tick(self):
        """NATURALGAS tick size 0.1 — prices should round to nearest 0.1."""
        assert round_to_tick(272.35, 0.1) == pytest.approx(272.4, abs=1e-9)
        assert round_to_tick(272.25, 0.1) == pytest.approx(272.2, abs=1e-9)
        assert round_down_to_tick(272.35, 0.1) == pytest.approx(272.3, abs=1e-9)
        assert round_up_to_tick(272.35, 0.1) == pytest.approx(272.4, abs=1e-9)

    def test_zero_tick_size_returns_price(self):
        """Tick size 0 should return price unchanged."""
        assert round_to_tick(100.0, 0) == 100.0
        assert round_down_to_tick(100.0, 0) == 100.0
        assert round_up_to_tick(100.0, 0) == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
