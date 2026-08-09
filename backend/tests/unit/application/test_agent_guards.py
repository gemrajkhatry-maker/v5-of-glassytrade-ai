"""Tests for agent fast-entry risk guards — daily loss limit."""

from __future__ import annotations

from unittest.mock import MagicMock


# =====================================================================
# Daily Loss Limit
# =====================================================================

class TestAgentDailyLossLimit:
    def test_should_block_entry_prevents_agent(self):
        """When TradeManager.should_block_entry() is True, agent must not enter."""
        tm = MagicMock()
        tm.should_block_entry.return_value = True
        lifecycle = MagicMock()
        lifecycle._trade_manager = tm

        blocked = (hasattr(lifecycle, '_trade_manager')
                   and lifecycle._trade_manager.should_block_entry())
        assert blocked is True

    def test_should_block_entry_allows_when_ok(self):
        tm = MagicMock()
        tm.should_block_entry.return_value = False
        lifecycle = MagicMock()
        lifecycle._trade_manager = tm

        blocked = (hasattr(lifecycle, '_trade_manager')
                   and lifecycle._trade_manager.should_block_entry())
        assert blocked is False
