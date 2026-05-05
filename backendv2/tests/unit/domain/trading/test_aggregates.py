"""Unit tests for Portfolio aggregate."""

import pytest
from decimal import Decimal
from app.domain.trading.model.aggregates import Portfolio, PortfolioConfig
from app.domain.trading.model.entities import Position, Signal
from app.domain.trading.model.enums import Side, SignalType, Source, SetupType, PositionStatus
from app.domain.trading.model.value_objects import OHLC, StrategyStats


class TestPortfolioCreation:
    """Tests for portfolio creation."""

    def test_create_default(self):
        p = Portfolio.create_default()
        assert p.balance == Decimal("1000000")
        assert p.equity == Decimal("1000000")
        assert p.leverage == 1
        assert len(p.positions) == 0

    def test_create_custom(self):
        p = Portfolio(balance=Decimal("500000"), leverage=2)
        assert p.balance == Decimal("500000")
        assert p.leverage == 2


class TestPortfolioPositionQueries:
    """Tests for position query methods."""

    def test_has_open_positions_empty(self):
        p = Portfolio.create_default()
        assert p.has_open_positions() is False

    def test_has_open_positions_with_open(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        p.positions.append(pos)
        assert p.has_open_positions() is True

    def test_has_open_positions_all_closed(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        pos.status = PositionStatus.CLOSED
        p.positions.append(pos)
        assert p.has_open_positions() is False

    def test_open_position_ids(self):
        p = Portfolio.create_default()
        pos1 = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        pos2 = Position.open("ETHUSDT", Side.SHORT, 3000, 0.1, 3100, 2800)
        p.positions = [pos1, pos2]
        ids = p.open_position_ids()
        assert pos1.id in ids
        assert pos2.id in ids

    def test_has_open_position_for_source(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        pos.source = Source.AMT
        p.positions.append(pos)
        assert p.has_open_position_for_source(Source.AMT) is True
        assert p.has_open_position_for_source(Source.LLM) is False

    def test_has_straddle_conflict(self):
        p = Portfolio.create_default()
        pos = Position.open("NIFTY", Side.LONG, 19500, 50, 19400, 19700)
        pos.metadata = {"strike": 19500}
        p.positions.append(pos)
        assert p.has_straddle_conflict("NIFTY", 19500) is True
        assert p.has_straddle_conflict("NIFTY", 19600) is False
        assert p.has_straddle_conflict("BANKNIFTY", 19500) is False


class TestPortfolioProcessTick:
    """Tests for tick processing."""

    def test_process_tick_updates_pnl(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        p.positions.append(pos)
        tick = OHLC.create("2026-01-01T00:00:00", 50000, 50500, 49900, 50200, 1000)
        closed = p.process_tick(tick)
        assert len(closed) == 0
        assert pos.pnl != Decimal("0")

    def test_process_tick_triggers_stop_loss(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        p.positions.append(pos)
        tick = OHLC.create("2026-01-01T00:00:00", 50000, 50100, 48900, 48950, 1000)
        closed = p.process_tick(tick)
        assert len(closed) == 1
        assert closed[0].status == PositionStatus.CLOSED

    def test_process_tick_triggers_take_profit(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        p.positions.append(pos)
        tick = OHLC.create("2026-01-01T00:00:00", 50000, 52100, 50000, 52050, 1000)
        closed = p.process_tick(tick)
        assert len(closed) == 1
        assert closed[0].status == PositionStatus.CLOSED


class TestPortfolioOpenPosition:
    """Tests for opening positions."""

    def test_open_position_basic(self):
        p = Portfolio.create_default()
        signal = Signal.create(
            SignalType.BUY, 50000, "test", 49000, 52000,
            "2026-01-01T00:00:00", SetupType.TREND_MODEL, Source.AMT,
        )
        pos = p.open_position(signal, "BTCUSDT")
        assert pos is not None
        assert pos.symbol == "BTCUSDT"
        assert pos.side == Side.LONG
        assert pos.is_open

    def test_open_position_duplicate_source_blocked(self):
        p = Portfolio.create_default()
        signal1 = Signal.create(
            SignalType.BUY, 50000, "test1", 49000, 52000,
            "2026-01-01T00:00:00", SetupType.TREND_MODEL, Source.AMT,
        )
        signal2 = Signal.create(
            SignalType.BUY, 50100, "test2", 49100, 52100,
            "2026-01-01T00:01:00", SetupType.TREND_MODEL, Source.AMT,
        )
        p.open_position(signal1, "BTCUSDT")
        pos2 = p.open_position(signal2, "ETHUSDT")
        assert pos2 is None  # blocked: same source already has open position

    def test_open_position_straddle_blocked(self):
        p = Portfolio.create_default()
        signal1 = Signal.create(
            SignalType.BUY, 19500, "test", 19400, 19700,
            "2026-01-01T00:00:00", SetupType.TREND_MODEL, Source.AMT,
            metadata={"strike": 19500},
        )
        signal2 = Signal.create(
            SignalType.SELL, 19500, "test", 19600, 19300,
            "2026-01-01T00:01:00", SetupType.TREND_MODEL, Source.AMT,
            metadata={"strike": 19500},
        )
        p.open_position(signal1, "NIFTY")
        pos2 = p.open_position(signal2, "NIFTY")
        assert pos2 is None  # blocked: straddle conflict


class TestPortfolioClosePosition:
    """Tests for closing positions."""

    def test_close_position(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        p.positions.append(pos)
        # Simulate price moving up before close
        tick = OHLC.create("2026-01-01T00:00:00", 50000, 51000, 50000, 51000, 1000)
        p.process_tick(tick)
        initial_balance = p.balance
        closed = p.close_position(pos.id, 51000, "MANUAL")
        assert closed is not None
        assert closed.status == PositionStatus.CLOSED
        # Exit price includes slippage (0.15% for sell/exit)
        assert closed.exit_price < Decimal("51000")
        # Balance should reflect PnL minus commission
        assert p.balance != initial_balance

    def test_close_nonexistent_position(self):
        p = Portfolio.create_default()
        result = p.close_position("nonexistent", 51000)
        assert result is None


class TestPortfolioPartialClose:
    """Tests for partial position close."""

    def test_partial_close(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.1, 49000, 52000)
        p.positions.append(pos)
        initial_balance = p.balance
        pnl = p.partial_close_position(pos.id, 0.5, 51000, "PARTIAL_TP")
        assert pnl > 0
        assert pos.size == Decimal("0.05")  # half of 0.1
        assert p.balance > initial_balance

    def test_partial_close_full_size_marks_closed(self):
        p = Portfolio.create_default()
        pos = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        p.positions.append(pos)
        pnl = p.partial_close_position(pos.id, 1.0, 51000, "FULL")
        assert pos.status == PositionStatus.CLOSED


class TestPortfolioStats:
    """Tests for strategy statistics."""

    def test_get_stats_empty(self):
        p = Portfolio.create_default()
        stats = p.get_stats(Source.AMT)
        assert stats.total_trades == 0
        assert stats.win_rate == 0.0

    def test_get_stats_with_trades(self):
        p = Portfolio.create_default()
        pos1 = Position.open("BTCUSDT", Side.LONG, 50000, 0.01, 49000, 52000)
        pos1.pnl = Decimal("100")
        pos1.status = PositionStatus.CLOSED
        pos1.source = Source.AMT
        pos2 = Position.open("ETHUSDT", Side.SHORT, 3000, 0.1, 3100, 2800)
        pos2.pnl = Decimal("-50")
        pos2.status = PositionStatus.CLOSED
        pos2.source = Source.AMT
        p.closed_trades = [pos1, pos2]
        stats = p.get_stats(Source.AMT)
        assert stats.total_trades == 2
        assert stats.wins == 1
        assert stats.losses == 1
        assert stats.win_rate == 50.0
