"""
Unit tests for partition exit manager.
"""

import pytest
from src.trade_management.partition_exit_manager import (
    PartitionExitManager,
    ManagedPosition,
)


class TestPartitionExitManager:
    """Test partition exit logic."""

    def test_p1_exit_weak_momentum(self):
        """Test P1 exit with weak momentum."""
        manager = PartitionExitManager()
        position = ManagedPosition(
            entry_price=100.0,
            initial_stop=99.0,
            target=102.0,
            direction="LONG",
            lots=100,
        )
        # Price at 33% of R (100.34 to avoid floating point issues)
        signals = manager.check_exits(position, 100.34, cvd_slope=1.0)
        assert len(signals) == 1
        assert signals[0].exit_type == "PARTITION_1"
        assert signals[0].exit_pct == 0.30

    def test_p1_skipped_strong_momentum(self):
        """Test P1 skipped with strong momentum."""
        manager = PartitionExitManager()
        position = ManagedPosition(
            entry_price=100.0,
            initial_stop=99.0,
            target=102.0,
            direction="LONG",
            lots=100,
        )
        # Price at 33% of R with strong CVD
        signals = manager.check_exits(position, 100.33, cvd_slope=3.0)
        assert len(signals) == 0  # P1 skipped

    def test_p2_exit_at_target(self):
        """Test P2 exit at target."""
        manager = PartitionExitManager()
        position = ManagedPosition(
            entry_price=100.0,
            initial_stop=99.0,
            target=102.0,
            direction="LONG",
            lots=100,
        )
        signals = manager.check_exits(position, 102.0, cvd_slope=1.0)
        assert any(s.exit_type == "PARTITION_2" for s in signals)

    def test_breakeven_trigger(self):
        """Test break-even trigger at 35% of R."""
        manager = PartitionExitManager()
        position = ManagedPosition(
            entry_price=100.0,
            initial_stop=99.0,
            target=102.0,
            direction="LONG",
            lots=100,
        )
        # Price at 35% of R (100.36 to avoid floating point issues)
        signals = manager.check_exits(position, 100.36, cvd_slope=1.0)
        assert any(s.exit_type == "BREAK_EVEN" for s in signals)

    def test_counter_aggression_exit(self):
        """Test counter-aggression exit."""
        manager = PartitionExitManager()
        position = ManagedPosition(
            entry_price=100.0,
            initial_stop=99.0,
            target=102.0,
            direction="LONG",
            lots=100,
            counter_aggression_count=2,
        )
        signals = manager.check_exits(position, 101.0, cvd_slope=1.0)
        assert any(s.exit_type == "COUNTER_AGGRESSION" for s in signals)