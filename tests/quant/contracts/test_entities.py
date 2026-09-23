"""Unit tests for domain entities — Position lifecycle, Signal creation."""

from quant.contracts.enums import (
    Side, SignalType, Source, SetupType, PositionStatus,
)
from quant.contracts.entities import Signal, Position
from quant.execution.exit_rules import ExitReason


class TestSignal:
    def test_create(self):
        s = Signal(
            type=SignalType.BUY, price=50000, reason="Test",
            stop_loss=49000, take_profit=52000, timestamp="2026-01-01T00:00:00Z",
            setup=SetupType.TREND_MODEL, source=Source.AMT,
        )
        assert s.is_buy is True
        assert s.source == Source.AMT

    def test_sell_signal(self):
        s = Signal(
            type=SignalType.SELL, price=50000, reason="Test",
            stop_loss=51000, take_profit=48000, timestamp="t",
            setup=SetupType.MEAN_REVERSION, source=Source.PREDICTION,
        )
        assert s.is_buy is False

    def test_with_metadata(self):
        s = Signal(
            type=SignalType.BUY, price=100, reason="r",
            stop_loss=95, take_profit=110, timestamp="t",
            setup=SetupType.PREDICTION_ENTRY, source=Source.PREDICTION,
            metadata={"factorBreakdown": {"trend": 0.5}},
        )
        assert s.metadata["factorBreakdown"]["trend"] == 0.5


class TestPosition:
    def _make_position(self, side=Side.LONG, **kwargs):
        defaults = dict(
            id="p1", symbol="BTCUSDT", side=side,
            source=Source.AMT, entry_price=50000, size=1.0,
            stop_loss=49000, take_profit=52000, entry_time="t",
        )
        defaults.update(kwargs)
        return Position(**defaults)

    def test_create_open(self):
        p = self._make_position()
        assert p.is_open is True
        assert p.pnl == 0.0
        assert p.exit_price is None

    def test_update_pnl_long(self):
        p = self._make_position(side=Side.LONG, entry_price=100)
        pnl = p.update_pnl(110)
        assert pnl == 10.0

    def test_update_pnl_short(self):
        p = self._make_position(side=Side.SHORT, entry_price=100)
        pnl = p.update_pnl(90)
        assert pnl == 10.0

    def test_should_close_long_sl(self):
        p = self._make_position(side=Side.LONG, stop_loss=95, entry_price=100)
        closed, reason = p.should_close(94)
        assert closed is True
        assert reason == "Stop Loss"

    def test_should_close_long_tp(self):
        p = self._make_position(side=Side.LONG, stop_loss=90, take_profit=110, entry_price=100)
        closed, reason = p.should_close(110)
        assert closed is True
        assert "Take Profit" in reason

    def test_should_close_short_sl(self):
        p = self._make_position(side=Side.SHORT, stop_loss=105, entry_price=100)
        closed, reason = p.should_close(106)
        assert closed is True
        assert reason == "Stop Loss"

    def test_should_close_short_tp(self):
        p = self._make_position(side=Side.SHORT, take_profit=90, entry_price=100)
        closed, reason = p.should_close(89)
        assert closed is True
        assert "Take Profit" in reason

    def test_should_not_close(self):
        p = self._make_position(stop_loss=95, take_profit=110, entry_price=100)
        closed, _ = p.should_close(102)
        assert closed is False

    def test_close(self):
        p = self._make_position(entry_price=100)
        p.close(110, "2026-01-02T00:00:00Z", "Take Profit (Full)")
        assert p.is_open is False
        assert p.status == PositionStatus.CLOSED
        assert p.exit_price == 110
        assert p.pnl == 10.0

    def test_close_classifies_breakeven_and_tp2_literals(self):
        p = self._make_position(entry_price=100, stop_loss=95, take_profit=105)
        # Exit exactly at the SL level: geometric classification would call this
        # STOP_LOSS, but the journal truth is a breakeven scratch.
        p.close(95, "t", "BREAKEVEN")
        assert p.close_reason == ExitReason.BREAK_EVEN

        p2 = self._make_position(entry_price=100, stop_loss=95, take_profit=102)
        # Below TP minus tolerance and above entry: geometric classification
        # falls through to SCRATCH, but a journaled TP2 is TAKE_PROFIT family.
        p2.close(101.3, "t", "TP2")
        assert p2.close_reason == ExitReason.TAKE_PROFIT

    def test_close_classifies_opposing_signal_literal(self):
        p = self._make_position(entry_price=100, stop_loss=95, take_profit=105)
        # Exit price happens to be a profitable scratch: geometric
        # classification would call it SCRATCH/TAKE_PROFIT, but the journal
        # truth is a fresh contrary approval — ADVERSE_EXIT family.
        p.close(101.3, "t", "OPPOSING_SIGNAL")
        assert p.close_reason == ExitReason.ADVERSE_EXIT

    def test_move_stop_to_breakeven(self):
        p = self._make_position(entry_price=100, stop_loss=95)
        p.move_stop_to_breakeven()
        assert p.stop_loss == 100

    def test_from_signal(self):
        sig = Signal(
            type=SignalType.BUY, price=100, reason="test",
            stop_loss=95, take_profit=110, timestamp="t",
            setup=SetupType.TREND_MODEL, source=Source.AMT,
        )
        p = Position.from_signal(sig, "ETHUSDT", 2.5)
        assert p.symbol == "ETHUSDT"
        assert p.side == Side.LONG
        assert p.size == 2.5
        assert p.is_open is True

    def test_from_signal_sell(self):
        sig = Signal(
            type=SignalType.SELL, price=100, reason="test",
            stop_loss=105, take_profit=90, timestamp="t",
            setup=SetupType.MEAN_REVERSION, source=Source.PREDICTION,
        )
        p = Position.from_signal(sig, "BTCUSDT", 1.0)
        assert p.side == Side.SHORT
