"""Tests for tick_size integration in TP/SL lifecycle.

Verifies that:
  - SL/TP rounding utilities work correctly
  - adjust_stop_loss rounds to tick boundaries
  - Partition breakeven SL is applied
"""

from __future__ import annotations

import pytest
from decimal import Decimal

from app.domain.services.tick_utils import (
    round_to_tick,
    round_down_to_tick,
    round_up_to_tick,
)
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side, Source


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


class TestExitEngineTickSize:
    """Test ExitEngine uses tick_size in adjust_stop_loss."""

    def test_adjust_stop_loss_rounds_to_tick(self):
        """adjust_stop_loss should round new SL to tick boundary."""
        from app.domain.fabio_ai.services.exit_engine import (
            ExitEngine,
            TradeManagerConfig,
        )

        config = TradeManagerConfig(tick_size=1.0)
        engine = ExitEngine(config=config)

        # Create a Position entity
        pos = Position(
            id="t1",
            symbol="CRUDEOIL",
            side=Side.LONG,
            source=Source.AMT,
            entry_price=Decimal("6000.0"),
            size=Decimal("100"),
            stop_loss=Decimal("5990.0"),
            take_profit=Decimal("6100.0"),
            initial_stop=Decimal("5990.0"),
        )

        # Try to set SL to 6003.7 — should round to 6004.0
        result = engine.adjust_stop_loss(pos, 6003.7)
        assert result is True
        assert float(pos.stop_loss) == pytest.approx(6004.0, abs=1e-9)

    def test_adjust_stop_loss_nse_tick(self):
        """NSE tick size 0.05 — SL should round to nearest 0.05."""
        from app.domain.fabio_ai.services.exit_engine import (
            ExitEngine,
            TradeManagerConfig,
        )

        config = TradeManagerConfig(tick_size=0.05)
        engine = ExitEngine(config=config)

        pos = Position(
            id="t2",
            symbol="NIFTY",
            side=Side.LONG,
            source=Source.AMT,
            entry_price=Decimal("22700.0"),
            size=Decimal("75"),
            stop_loss=Decimal("22650.0"),
            take_profit=Decimal("22900.0"),
            initial_stop=Decimal("22650.0"),
        )

        result = engine.adjust_stop_loss(pos, 22750.07)
        assert result is True
        assert float(pos.stop_loss) == pytest.approx(22750.05, abs=1e-9)


class TestPartitionBreakeven:
    """Test partition exit manager breakeven logic."""

    def test_breakeven_triggers_at_1r(self):
        """Breakeven should trigger at 1.0R toward target (Fabio spec)."""
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

        # At 1.0R = 10 points toward target
        price_at_be = entry + risk * 1.0

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

    def test_p1_triggers_at_1r(self):
        """P1 should trigger at 1.0R (Fabio spec)."""
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

        # At 1.0R with BALANCED market
        price_at_p1 = entry + risk * 1.0

        signals = pem.check_exits(
            entry_price=entry,
            initial_stop=sl,
            take_profit=tp,
            current_price=price_at_p1,
            is_long=True,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
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
