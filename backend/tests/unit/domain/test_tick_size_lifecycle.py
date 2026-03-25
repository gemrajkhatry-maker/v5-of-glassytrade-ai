"""Tests for tick_size integration in TP/SL lifecycle.

Verifies that:
  - SL/TP rounding utilities work correctly
  - adjust_stop_loss rounds to tick boundaries
  - Partition breakeven SL is applied
"""

from __future__ import annotations

import pytest
from app.domain.services.tick_utils import (
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


class TestTradeManagerTickSize:
    """Test TradeManager uses tick_size in adjust_stop_loss."""

    def test_adjust_stop_loss_rounds_to_tick(self):
        """adjust_stop_loss should round new SL to tick boundary."""
        from app.domain.fabio_ai.services.trade_manager import (
            TradeManager,
            TradeManagerConfig,
        )

        config = TradeManagerConfig(tick_size=1.0)
        mgr = TradeManager(config=config)
        mgr.register_position("t1", "CRUDEOIL", "LONG", 6000.0, 5990.0, 6100.0)

        # Try to set SL to 6003.7 — should round to 6004.0
        result = mgr.adjust_stop_loss("t1", 6003.7)
        assert result is True

        mp = mgr._positions.get("t1")
        assert mp is not None
        assert mp.stop_loss == pytest.approx(6004.0, abs=1e-9)

    def test_adjust_stop_loss_nse_tick(self):
        """NSE tick size 0.05 — SL should round to nearest 0.05."""
        from app.domain.fabio_ai.services.trade_manager import (
            TradeManager,
            TradeManagerConfig,
        )

        config = TradeManagerConfig(tick_size=0.05)
        mgr = TradeManager(config=config)
        mgr.register_position("t2", "NIFTY", "LONG", 22700.0, 22650.0, 22900.0)

        result = mgr.adjust_stop_loss("t2", 22750.07)
        assert result is True

        mp = mgr._positions.get("t2")
        assert mp is not None
        assert mp.stop_loss == pytest.approx(22750.05, abs=1e-9)


class TestPartitionBreakeven:
    """Test partition exit manager breakeven logic."""

    def test_breakeven_triggers_at_35_percent_r(self):
        """Breakeven should trigger at 35% of R toward target."""
        from app.domain.fabio_ai.services.partition_exit_manager import (
            PartitionExitManager,
            PartitionState,
        )

        pem = PartitionExitManager()
        state = PartitionState()

        entry = 6000.0
        sl = 5990.0
        tp = 6100.0
        risk = abs(entry - sl)

        # At 35% of R = 3.5 points toward target
        price_at_be = entry + risk * 0.35

        pem.check_exits(
            entry_price=entry,
            initial_stop=sl,
            take_profit=tp,
            current_price=price_at_be,
            is_long=True,
            cvd_slope=0.0,
            state=state,
        )

        assert state.breakeven_set is True
        assert state.trail_sl == pytest.approx(entry, abs=1e-9)

    def test_p1_triggers_at_33_percent_r(self):
        """P1 should trigger at 33% of R with weak CVD."""
        from app.domain.fabio_ai.services.partition_exit_manager import (
            PartitionExitManager,
            PartitionState,
        )

        pem = PartitionExitManager()
        state = PartitionState()

        entry = 6000.0
        sl = 5990.0
        tp = 6100.0
        risk = abs(entry - sl)

        # At 33% R with weak CVD
        price_at_p1 = entry + risk * 0.33

        signals = pem.check_exits(
            entry_price=entry,
            initial_stop=sl,
            take_profit=tp,
            current_price=price_at_p1,
            is_long=True,
            cvd_slope=0.5,  # weak
            state=state,
        )

        assert state.p1_taken is True
        assert any(s.exit_type == "PARTITION_1" for s in signals)

    def test_p2_triggers_at_target(self):
        """P2 should trigger when price reaches target."""
        from app.domain.fabio_ai.services.partition_exit_manager import (
            PartitionExitManager,
            PartitionState,
        )

        pem = PartitionExitManager()
        state = PartitionState()

        entry = 6000.0
        sl = 5990.0
        tp = 6100.0

        signals = pem.check_exits(
            entry_price=entry,
            initial_stop=sl,
            take_profit=tp,
            current_price=6100.0,
            is_long=True,
            cvd_slope=1.0,
            state=state,
        )

        assert state.p2_taken is True
        assert any(s.exit_type == "PARTITION_2" for s in signals)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
