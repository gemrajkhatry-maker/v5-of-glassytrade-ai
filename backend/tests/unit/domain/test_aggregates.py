"""Unit tests for Portfolio aggregate root."""

import pytest
from app.domain.trading.models.enums import Side, Source, PositionStatus, SignalType, SetupType
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.value_objects import OHLC


def _make_tick(close: float = 100, **overrides) -> OHLC:
    defaults = dict(
        time="2026-01-01T00:00:00Z", open=close, high=close * 1.01,
        low=close * 0.99, close=close, volume=1000, vwap=close, delta=0,
    )
    defaults.update(overrides)
    return OHLC(**defaults)


def _make_signal(price=100, sl=95, tp=110, source=Source.AMT, sig_type=SignalType.BUY) -> Signal:
    return Signal(
        type=sig_type, price=price, reason="test",
        stop_loss=sl, take_profit=tp, timestamp="2026-01-01T00:00:00Z",
        setup=SetupType.TREND_MODEL, source=source,
    )


class TestPortfolioCreate:
    def test_default(self):
        p = Portfolio.create_default()
        from app.domain.trading.models.aggregates import INITIAL_CAPITAL
        assert p.balance == INITIAL_CAPITAL
        assert p.equity == INITIAL_CAPITAL
        assert p.leverage == 10
        assert p.positions == []
        assert p.closed_trades == []


class TestPortfolioOpenPosition:
    def test_open_success(self):
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=95, tp=110)
        pos = p.open_position(sig, "BTCUSDT")
        assert pos is not None
        assert len(p.positions) == 1
        assert pos.is_open

    def test_no_duplicate_source(self):
        p = Portfolio.create_default()
        sig1 = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        p.open_position(sig1, "BTCUSDT")
        sig2 = _make_signal(price=101, sl=96, tp=111, source=Source.AMT)
        pos2 = p.open_position(sig2, "BTCUSDT")
        assert pos2 is None
        assert len(p.positions) == 1

    def test_different_sources_ok(self):
        p = Portfolio.create_default()
        sig1 = _make_signal(source=Source.AMT)
        sig2 = _make_signal(source=Source.PREDICTION)
        p.open_position(sig1, "BTCUSDT")
        pos2 = p.open_position(sig2, "BTCUSDT")
        assert pos2 is not None
        assert len(p.positions) == 2

    def test_zero_risk_rejected(self):
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=100, tp=110)  # SL == price
        pos = p.open_position(sig, "BTCUSDT")
        assert pos is None

    def test_position_sizing(self):
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=95, tp=110)
        pos = p.open_position(sig, "BTCUSDT")
        # No metadata → confidence="Medium" → risk=0.35%
        # risk_amount = 1M * 0.0035 = 3.5K; risk_per_unit = 5; size = 700
        assert pos.size == pytest.approx(700, rel=0.01)


class TestPortfolioProcessTick:
    def test_updates_pnl(self):
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=90, tp=120)
        p.open_position(sig, "BTCUSDT")

        tick = _make_tick(close=105)
        closed = p.process_tick(tick)
        assert closed == []
        assert p.positions[0].pnl > 0

    def test_closes_on_stop_loss(self):
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=95, tp=120)
        p.open_position(sig, "BTCUSDT")

        tick = _make_tick(close=94)
        closed = p.process_tick(tick)
        assert len(closed) == 1
        assert closed[0].close_reason == "Stop Loss"
        assert len(p.positions) == 0

    def test_closes_on_take_profit(self):
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=90, tp=110)
        p.open_position(sig, "BTCUSDT")

        tick = _make_tick(close=110)
        closed = p.process_tick(tick)
        assert len(closed) == 1
        assert "Take Profit" in closed[0].close_reason

    def test_balance_updates_on_close(self):
        p = Portfolio.create_default()
        initial_balance = p.balance
        sig = _make_signal(price=100, sl=90, tp=110)
        p.open_position(sig, "BTCUSDT")

        tick = _make_tick(close=110)
        p.process_tick(tick)
        assert p.balance > initial_balance

    def test_portfolio_does_not_move_breakeven(self):
        """Break-even logic is centralized in TradeManager, not Portfolio."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=90, tp=120)
        p.open_position(sig, "BTCUSDT")

        # Strong positive delta — Portfolio should NOT move SL
        tick = _make_tick(close=105, delta=600, volume=1000)
        p.process_tick(tick)
        assert p.positions[0].stop_loss == 90  # unchanged, TradeManager handles BE


class TestPortfolioStats:
    def test_stats_no_trades(self):
        p = Portfolio.create_default()
        stats = p.get_stats(Source.AMT)
        assert stats.total_trades == 0

    def test_stats_with_trades(self):
        p = Portfolio.create_default()
        # Simulate closed trades
        pos1 = Position(
            id="1", symbol="BTCUSDT", side=Side.LONG, source=Source.AMT,
            entry_price=100, size=1, stop_loss=95, take_profit=110,
            pnl=10, entry_time="t", status=PositionStatus.CLOSED,
        )
        pos2 = Position(
            id="2", symbol="BTCUSDT", side=Side.LONG, source=Source.AMT,
            entry_price=100, size=1, stop_loss=95, take_profit=110,
            pnl=-5, entry_time="t", status=PositionStatus.CLOSED,
        )
        p.closed_trades = [pos1, pos2]

        stats = p.get_stats(Source.AMT)
        assert stats.total_trades == 2
        assert stats.wins == 1
        assert stats.losses == 1
        assert stats.win_rate == 50.0
        assert stats.net_profit == 5.0

    def test_stats_filters_by_source(self):
        p = Portfolio.create_default()
        pos_amt = Position(
            id="1", symbol="S", side=Side.LONG, source=Source.AMT,
            entry_price=100, size=1, stop_loss=95, take_profit=110,
            pnl=10, entry_time="t", status=PositionStatus.CLOSED,
        )
        pos_pred = Position(
            id="2", symbol="S", side=Side.LONG, source=Source.PREDICTION,
            entry_price=100, size=1, stop_loss=95, take_profit=110,
            pnl=-5, entry_time="t", status=PositionStatus.CLOSED,
        )
        p.closed_trades = [pos_amt, pos_pred]

        amt_stats = p.get_stats(Source.AMT)
        assert amt_stats.total_trades == 1
        assert amt_stats.net_profit == 10

        pred_stats = p.get_stats(Source.PREDICTION)
        assert pred_stats.total_trades == 1
        assert pred_stats.net_profit == -5
