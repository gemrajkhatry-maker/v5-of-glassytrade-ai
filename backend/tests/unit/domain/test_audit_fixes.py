from decimal import Decimal
"""Tests for production audit fixes — commission, slippage, SL watchdog, async persistence."""

import asyncio
import queue
import threading
import time as _time

import pytest

from app.domain.trading.models.enums import Side, Source, PositionStatus, SignalType, SetupType
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.aggregates import (
    Portfolio, COMMISSION_PER_LOT, SLIPPAGE_PCT, DEFAULT_LOT_SIZE,
)
from app.domain.trading.models.value_objects import OHLC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick(close: float = 100, **overrides) -> OHLC:
    defaults = dict(
        time="2026-01-01T00:00:00Z", open=close, high=close * 1.01,
        low=close * 0.99, close=close, volume=1000, vwap=close, delta=0,
    )
    defaults.update(overrides)
    return OHLC(**defaults)


def _make_signal(
    price=100, sl=95, tp=110, source=Source.AMT,
    sig_type=SignalType.BUY, lot_size=0
) -> Signal:
    meta = {}
    if lot_size:
        meta["option_lot_size"] = lot_size
    return Signal(
        type=sig_type, price=price, reason="test",
        stop_loss=sl, take_profit=tp, timestamp="2026-01-01T00:00:00Z",
        setup=SetupType.TREND_MODEL, source=source,
        metadata=meta if meta else None,
    )


# =====================================================================
# 1. COMMISSION MODEL TESTS
# =====================================================================

class TestCommissionModel:
    """Validates that round-trip commissions are deducted from P&L."""

    def test_commission_deducted_on_sl_close(self):
        """When SL triggers, commission must be subtracted from gross P&L."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=95, tp=120, lot_size=50)
        pos = p.open_position(sig, "NIFTY_CE")
        assert pos is not None

        initial_balance = p.balance
        tick = _make_tick(close=94)  # triggers SL
        closed = p.process_tick(tick)
        assert len(closed) == 1

        # Gross P&L is negative, commision makes it worse
        gross_pnl = (closed[0].exit_price - pos.entry_price) * pos.size
        assert closed[0].pnl < gross_pnl  # commission was subtracted

    def test_commission_deducted_on_tp_close(self):
        """TP close should also include commission, reducing net profit."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=90, tp=110, lot_size=25)
        pos = p.open_position(sig, "NIFTY_CE")
        assert pos is not None

        tick = _make_tick(close=111)  # triggers TP
        closed = p.process_tick(tick)
        assert len(closed) == 1

        # Net P&L should be less than gross due to commission
        exit_price = closed[0].exit_price
        gross = (exit_price - pos.entry_price) * pos.size
        assert closed[0].pnl < gross

    def test_commission_calculation_lot_based(self):
        """Commission uses lot-based calculation when option_lot_size is set."""
        p = Portfolio.create_default()
        # 100 units with lot_size=25 = 4 lots
        commission = p._compute_commission(100, {"option_lot_size": 25})
        assert commission == 4 * COMMISSION_PER_LOT

    def test_commission_calculation_no_lot_size(self):
        """Without lot_size, charges a single flat commission per trade."""
        p = Portfolio.create_default()
        commission = p._compute_commission(10, None)
        assert commission == 1 * COMMISSION_PER_LOT  # flat fee, not per-unit

    def test_commission_minimum_one_lot(self):
        """Should always charge at least 1 lot of commission."""
        p = Portfolio.create_default()
        commission = p._compute_commission(0.5, {"option_lot_size": 25})
        assert commission == 1 * COMMISSION_PER_LOT

    def test_close_position_includes_commission(self):
        """Manual close via close_position() includes commission."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=90, tp=120)
        pos = p.open_position(sig, "SYM")
        assert pos is not None

        closed = p.close_position(pos.id, 105.0, "TEST_EXIT")
        assert closed is not None
        # Commission should reduce P&L below gross
        gross = (closed.exit_price - pos.entry_price) * pos.size
        assert closed.pnl < gross


# =====================================================================
# 2. SLIPPAGE MODEL TESTS
# =====================================================================

class TestSlippageModel:
    """Validates slippage is applied correctly to fill prices."""

    def test_long_entry_slippage_adverse(self):
        """LONG entry should fill slightly higher (adverse)."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=95, tp=110)
        pos = p.open_position(sig, "SYM")
        assert pos is not None
        assert pos.entry_price > 100.0  # slipped up for LONG

    def test_short_entry_slippage_adverse(self):
        """SHORT entry should fill slightly lower (adverse)."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=105, tp=90, sig_type=SignalType.SELL)
        pos = p.open_position(sig, "SYM")
        assert pos is not None
        assert pos.entry_price < 100.0  # slipped down for SHORT

    def test_long_exit_slippage_adverse(self):
        """LONG exit should fill slightly lower (adverse)."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=90, tp=120)
        pos = p.open_position(sig, "SYM")
        assert pos is not None

        tick = _make_tick(close=121)  # triggers TP
        closed = p.process_tick(tick)
        assert len(closed) == 1
        # Exit price should be slightly below market (slippage)
        assert closed[0].exit_price < 121.0

    def test_slippage_amount_is_percentage(self):
        """Slippage should be exactly SLIPPAGE_PCT of the price."""
        price = 1000.0
        slipped = Portfolio._apply_slippage(price, Side.LONG, is_entry=True)
        assert float(slipped) == pytest.approx(float(price) * (1 + float(SLIPPAGE_PCT)), rel=1e-10)

    def test_slippage_both_sides_symmetric(self):
        """LONG entry slippage up = SHORT entry slippage down (by same pct)."""
        price = Decimal("1000.0")
        long_entry = Portfolio._apply_slippage(price, Side.LONG, is_entry=True)
        short_entry = Portfolio._apply_slippage(price, Side.SHORT, is_entry=True)
        assert abs(float(long_entry - price) - float(price - short_entry)) < 0.001


# =====================================================================
# 3. EVENT IMMUTABILITY TEST
# =====================================================================

class TestEventImmutability:
    """Validates TickReceived.data is a defensive copy."""

    def test_tick_received_data_is_tuple(self):
        """TickReceived.data should be a tuple (immutable), not a list."""
        from app.domain.trading.events import TickReceived
        tick = _make_tick(close=100)
        original_list = [tick, tick, tick]
        event = TickReceived(symbol="SYM", tick=tick, data=tuple(original_list))

        # Mutating original_list should not affect event
        original_list.pop()
        assert len(event.data) == 3  # still 3

    def test_frozen_event_cannot_be_mutated(self):
        """TickReceived is a frozen dataclass — attributes cannot be reassigned."""
        from app.domain.trading.events import TickReceived
        tick = _make_tick(close=100)
        event = TickReceived(symbol="SYM", tick=tick)
        with pytest.raises(AttributeError):
            event.symbol = "MUTATED"


# =====================================================================
# 5. SL WATCHDOG INTEGRATION TEST (Lightweight)
# =====================================================================

class TestSLWatchdogLogic:
    """Tests the core SL watchdog logic without needing the full engine."""

    def test_should_close_detects_sl_breach(self):
        """Position.should_close must return True when LTP breaches SL."""
        pos = Position(
            id="test1", symbol="SYM", side=Side.LONG, source=Source.AMT,
            entry_price=100, size=10, stop_loss=95, take_profit=120,
            pnl=0, entry_time="t", status=PositionStatus.OPEN,
        )
        should_close, reason = pos.should_close(94.0)  # below SL
        assert should_close is True
        assert "Stop Loss" in reason

    def test_should_close_detects_tp_breach(self):
        """Position.should_close must return True when LTP reaches TP."""
        pos = Position(
            id="test2", symbol="SYM", side=Side.LONG, source=Source.AMT,
            entry_price=100, size=10, stop_loss=95, take_profit=120,
            pnl=0, entry_time="t", status=PositionStatus.OPEN,
        )
        should_close, reason = pos.should_close(121.0)  # above TP
        assert should_close is True
        assert "Take Profit" in reason

    def test_should_close_safe_prices_no_trigger(self):
        """Position.should_close returns False when price is safe."""
        pos = Position(
            id="test3", symbol="SYM", side=Side.LONG, source=Source.AMT,
            entry_price=100, size=10, stop_loss=95, take_profit=120,
            pnl=0, entry_time="t", status=PositionStatus.OPEN,
        )
        should_close, _ = pos.should_close(105.0)  # safe range
        assert should_close is False

    def test_portfolio_close_position_applies_slippage_and_commission(self):
        """close_position should apply both slippage and commission."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=90, tp=120)
        pos = p.open_position(sig, "SYM")
        assert pos is not None

        initial_balance = p.balance
        closed = p.close_position(pos.id, 100.0, "WATCHDOG_Stop Loss")
        assert closed is not None
        # Net P&L should be negative (slippage + commission on a break-even trade)
        assert closed.pnl < 0
