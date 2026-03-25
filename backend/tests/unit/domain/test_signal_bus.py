"""Tests for SignalBus and PortfolioCoordinator — Phase 1 parallel engine."""

import asyncio
import pytest
from unittest.mock import MagicMock

from app.domain.services.signal_bus import SignalBus, BusSignal
from app.application.services.portfolio_coordinator import (
    PortfolioCoordinator,
    RejectionResult,
)


class TestSignalBus:
    def test_initial_empty(self):
        bus = SignalBus()
        assert bus.is_empty
        assert bus.size == 0

    @pytest.mark.asyncio
    async def test_put_and_get(self):
        bus = SignalBus()
        signal = MagicMock()
        bs = BusSignal(signal=signal, symbol="NIFTY")
        result = await bus.put(bs)
        assert result is True
        assert bus.size == 1

        got = bus.get_nowait()
        assert got is not None
        assert got.symbol == "NIFTY"

    @pytest.mark.asyncio
    async def test_backpressure(self):
        bus = SignalBus(maxsize=1)
        signal = MagicMock()
        bs = BusSignal(signal=signal, symbol="NIFTY")
        await bus.put(bs)
        result = await bus.put(bs)  # second should fail
        assert result is False

    def test_stats(self):
        bus = SignalBus()
        stats = bus.get_stats()
        assert "produced" in stats
        assert "consumed" in stats
        assert "rejected" in stats


class TestPortfolioCoordinator:
    def _make_signal(
        self, symbol="NIFTY", direction="LONG", entry_price=100.0, size=25.0
    ):
        signal = MagicMock()
        signal.symbol = symbol
        signal.direction = direction
        signal.entry_price = entry_price
        signal.size = size
        return signal

    def _make_portfolio(self, open_positions=None):
        portfolio = MagicMock()
        portfolio.open_positions = open_positions or {}
        portfolio.get_stats.return_value = MagicMock(realized_pnl=0)
        return portfolio

    def test_max_positions_rejects(self):
        bus = SignalBus()
        portfolio = self._make_portfolio(
            {
                "a": MagicMock(),
                "b": MagicMock(),
                "c": MagicMock(),
                "d": MagicMock(),
                "e": MagicMock(),
            }
        )
        broker = MagicMock()
        coord = PortfolioCoordinator(
            signal_bus=bus,
            portfolio=portfolio,
            broker=broker,
            max_positions=5,
        )
        signal = self._make_signal()
        result = coord._check_rules(signal)
        assert result.rejected is True
        assert result.rule == "MAX_POSITIONS"

    def test_correlation_guard_rejects(self):
        bus = SignalBus()
        existing = MagicMock()
        existing.symbol = "NIFTY 30 MAR 23300 CALL"
        existing.side = "BUY"
        existing.entry_price = 100.0
        existing.size = 25.0
        portfolio = self._make_portfolio({"a": existing})
        broker = MagicMock()
        coord = PortfolioCoordinator(
            signal_bus=bus,
            portfolio=portfolio,
            broker=broker,
            correlation_guard=True,
        )
        signal = self._make_signal(
            symbol="BANKNIFTY 30 MAR 53000 CALL", direction="LONG"
        )
        result = coord._check_rules(signal)
        assert result.rejected is True
        assert result.rule == "CORRELATION_GUARD"

    def test_correlation_guard_different_direction_passes(self):
        bus = SignalBus()
        existing = MagicMock()
        existing.symbol = "NIFTY 30 MAR 23300 CALL"
        existing.side = "BUY"  # LONG
        existing.entry_price = 100.0
        existing.size = 25.0
        portfolio = self._make_portfolio({"a": existing})
        broker = MagicMock()
        coord = PortfolioCoordinator(
            signal_bus=bus,
            portfolio=portfolio,
            broker=broker,
            correlation_guard=True,
        )
        signal = self._make_signal(
            symbol="BANKNIFTY 30 MAR 53000 PUT", direction="SHORT"
        )
        result = coord._check_rules(signal)
        assert result.rejected is False  # different direction — OK

    def test_portfolio_notional_rejects(self):
        bus = SignalBus()
        existing = MagicMock()
        existing.symbol = "NIFTY CALL"
        existing.side = "BUY"
        existing.entry_price = 24000.0
        existing.size = 25.0
        portfolio = self._make_portfolio({"a": existing})
        broker = MagicMock()
        coord = PortfolioCoordinator(
            signal_bus=bus,
            portfolio=portfolio,
            broker=broker,
            capital=100000.0,  # small capital
            max_portfolio_notional_pct=0.50,
        )
        signal = self._make_signal(entry_price=1000.0, size=25.0)
        result = coord._check_rules(signal)
        assert result.rejected is True
        assert result.rule == "PORTFOLIO_NOTIONAL"

    def test_clean_signal_passes_all_rules(self):
        bus = SignalBus()
        portfolio = self._make_portfolio({})
        broker = MagicMock()
        coord = PortfolioCoordinator(
            signal_bus=bus,
            portfolio=portfolio,
            broker=broker,
            capital=5000000.0,
        )
        signal = self._make_signal()
        result = coord._check_rules(signal)
        assert result.rejected is False

    def test_disabled_correlation_guard_passes(self):
        bus = SignalBus()
        existing = MagicMock()
        existing.symbol = "NIFTY 30 MAR 23300 CALL"
        existing.side = "BUY"
        existing.entry_price = 100.0
        existing.size = 25.0
        portfolio = self._make_portfolio({"a": existing})
        broker = MagicMock()
        coord = PortfolioCoordinator(
            signal_bus=bus,
            portfolio=portfolio,
            broker=broker,
            correlation_guard=False,  # disabled
        )
        signal = self._make_signal(
            symbol="BANKNIFTY 30 MAR 53000 CALL", direction="LONG"
        )
        result = coord._check_rules(signal)
        assert result.rejected is False
