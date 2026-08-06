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
        assert p.leverage == 1
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
        # risk_amount = 5M (INITIAL_CAPITAL) * 0.0035 = 17.5K
        # risk_per_unit = 5; size = 17.5K / 5 = 3500
        assert pos.size == pytest.approx(3500, rel=0.01)


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
        assert closed[0].close_reason == "STOP_LOSS"
        assert len(p.positions) == 0

    def test_closes_on_take_profit(self):
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=90, tp=110)
        p.open_position(sig, "BTCUSDT")

        tick = _make_tick(close=110)
        closed = p.process_tick(tick)
        assert len(closed) == 1
        assert "TAKE_PROFIT" in closed[0].close_reason

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


class TestStraddlePrevention:
    def test_straddle_conflict_detected(self):
        """Test that has_straddle_conflict returns True when position exists at same strike."""
        p = Portfolio.create_default()
        assert not p.has_straddle_conflict("NIFTY", 24000)
        
        # Open a position with strike info
        sig = _make_signal(price=100, sl=95, tp=110)
        sig.metadata = {"strike": 24000}
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        
        # Should detect conflict for same strike
        assert p.has_straddle_conflict("NIFTY", 24000)
        assert not p.has_straddle_conflict("NIFTY", 24500)  # Different strike
        assert not p.has_straddle_conflict("BANKNIFTY", 24000)  # Different symbol

    def test_straddle_prevention_blocks_entry(self):
        """Test that open_position blocks entry when straddle would be created."""
        p = Portfolio.create_default()
        
        # Open CE position
        sig1 = _make_signal(price=100, sl=95, tp=110)
        sig1.metadata = {"strike": 24000}
        pos1 = p.open_position(sig1, "NIFTY")
        assert pos1 is not None
        
        # Try PE at same strike - should be blocked
        sig2 = _make_signal(price=100, sl=95, tp=110)
        sig2.metadata = {"strike": 24000}
        pos2 = p.open_position(sig2, "NIFTY")
        assert pos2 is None  # Blocked - straddle prevention
        assert len(p.positions) == 1

    def test_get_open_positions_summary(self):
        """Test that get_open_positions_summary returns correct format."""
        p = Portfolio.create_default()
        
        # Empty portfolio
        assert p.get_open_positions_summary() == []
        
        # Add positions - use different sources to avoid duplicate source block
        sig1 = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig1.metadata = {"strike": 24000}
        p.open_position(sig1, "NIFTY")
        
        # Second position at different strike (no straddle conflict) - use different source
        sig2 = _make_signal(price=110, sl=105, tp=120, source=Source.PREDICTION)
        sig2.metadata = {"strike": 24500}
        p.open_position(sig2, "NIFTY")  # Same symbol, different strike - allowed
        
        summary = p.get_open_positions_summary()
        assert len(summary) == 2
        assert any(s["symbol"] == "NIFTY" and s["strike"] == 24000 for s in summary)
        assert any(s["symbol"] == "NIFTY" and s["strike"] == 24500 for s in summary)

    def test_straddle_prevention_different_symbols(self):
        """Test that same strike at different symbols doesn't trigger straddle block."""
        p = Portfolio.create_default()
        
        # Open position in NIFTY
        sig1 = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig1.metadata = {"strike": 24000}
        pos1 = p.open_position(sig1, "NIFTY")
        assert pos1 is not None
        
        # Open position in BANKNIFTY at same strike - should be allowed
        sig2 = _make_signal(price=100, sl=95, tp=110, source=Source.PREDICTION)
        sig2.metadata = {"strike": 24000}
        pos2 = p.open_position(sig2, "BANKNIFTY")
        assert pos2 is not None  # Different symbol - allowed
        assert len(p.positions) == 2

    def test_straddle_blocked_with_option_strike_and_type(self):
        """Regression: the production entry path stores the strike under
        ``option_strike`` (with ``option_type``), not ``strike``.  A CE at a
        strike must block a PE at the same strike (true straddle)."""
        p = Portfolio.create_default()
        sig_ce = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig_ce.metadata = {"option_strike": 24000, "option_type": "CE"}
        assert p.open_position(sig_ce, "NIFTY") is not None

        # PE at the same strike -> straddle, must be blocked
        sig_pe = _make_signal(price=100, sl=95, tp=110, source=Source.PREDICTION)
        sig_pe.metadata = {"option_strike": 24000, "option_type": "PE"}
        assert p.open_position(sig_pe, "NIFTY") is None
        assert len(p.positions) == 1

    def test_same_option_type_same_strike_allowed(self):
        """Regression: two CALLs at the same strike are NOT a straddle — AMT
        only forbids holding both CE and PE.  Same-type duplicates remain
        governed by the duplicate-source invariant."""
        p = Portfolio.create_default()
        sig1 = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig1.metadata = {"option_strike": 24000, "option_type": "CE"}
        assert p.open_position(sig1, "NIFTY") is not None

        sig2 = _make_signal(price=101, sl=96, tp=111, source=Source.PREDICTION)
        sig2.metadata = {"option_strike": 24000, "option_type": "CE"}
        assert p.open_position(sig2, "NIFTY") is not None
        assert len(p.positions) == 2

    def test_straddle_not_blocked_across_strikes_with_option_keys(self):
        """Opposite option types at different strikes are not a straddle."""
        p = Portfolio.create_default()
        sig1 = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig1.metadata = {"option_strike": 24000, "option_type": "CE"}
        assert p.open_position(sig1, "NIFTY") is not None

        sig2 = _make_signal(price=110, sl=105, tp=120, source=Source.PREDICTION)
        sig2.metadata = {"option_strike": 24500, "option_type": "PE"}
        assert p.open_position(sig2, "NIFTY") is not None
        assert len(p.positions) == 2

    def test_open_positions_summary_reports_option_strike(self):
        """Regression: the LLM context summary must report the strike even
        when it is stored under ``option_strike``."""
        p = Portfolio.create_default()
        sig = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig.metadata = {"option_strike": 24000, "option_type": "CE"}
        p.open_position(sig, "NIFTY")
        summary = p.get_open_positions_summary()
        assert len(summary) == 1
        assert summary[0]["strike"] == 24000

    def test_position_helpers(self):
        """Test helper methods: has_open_positions, open_position_ids, etc."""
        p = Portfolio.create_default()
        
        # No positions initially
        assert not p.has_open_positions()
        assert p.open_position_ids() == set()
        
        # Add position
        sig = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig.metadata = {"strike": 24000}
        p.open_position(sig, "NIFTY")
        
        assert p.has_open_positions()
        assert len(p.open_position_ids()) == 1
        assert p.has_open_position_for_source(Source.AMT)
        assert not p.has_open_position_for_source(Source.PREDICTION)

    def test_session_risk_pct_metadata(self):
        """Test that session_risk_pct in metadata affects position sizing."""
        p = Portfolio.create_default()
        
        # Signal with session_risk_pct should use that value
        sig = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig.metadata = {
            "strike": 24000,
            "session_risk_pct": 0.004,  # 0.4% risk
        }
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        # Should have larger size due to higher risk pct
        assert pos.size > 700  # Default is ~700 with 0.35%

    def test_scale_in_fraction(self):
        """Test scale_in_fraction affects position size."""
        p = Portfolio.create_default()
        
        sig = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig.metadata = {"strike": 24000}
        
        # Full size entry
        pos1 = p.open_position(sig, "NIFTY", scale_fraction=1.0)
        assert pos1 is not None
        full_size = pos1.size
        
        # Create new portfolio for second test
        p2 = Portfolio.create_default()
        pos2 = p2.open_position(sig, "NIFTY", scale_fraction=0.4)  # 40% scale-in
        assert pos2 is not None
        assert pos2.size < full_size  # 40% of full size

    def test_commission_with_lot_size(self):
        """Test commission calculation with lot size."""
        p = Portfolio.create_default()
        
        # Test commission calculation with lot size
        commission = p._compute_commission(100, {"option_lot_size": 65})
        assert commission > 0
        
        # Test without lot size (flat fee)
        commission_no_lot = p._compute_commission(100, None)
        assert commission_no_lot > 0

    def test_history_trim(self):
        """Test that closed_trades list is trimmed at 200."""
        from app.domain.trading.models.entities import Position
        
        p = Portfolio.create_default()
        
        # Create 250 closed positions
        for i in range(250):
            pos = Position(
                id=f"test-{i}",
                symbol="TEST",
                side=Side.LONG,
                source=Source.AMT,
                entry_price=100,
                size=1,
                stop_loss=95,
                take_profit=110,
                pnl=10,
                entry_time="t",
                status=PositionStatus.CLOSED,
            )
            p.closed_trades.append(pos)
        
        # Process a tick to trigger trimming logic
        tick = _make_tick(close=100)
        p.process_tick(tick)
        
        # Should be trimmed to 200
        assert len(p.closed_trades) <= 200

    def test_long_position_small_loss_at_time_stop(self):
        """Test TIME_STOP behavior with R-multiple logic for small loss trades."""
        from app.domain.fabio_ai.services.exit_rules import check_time_stop_with_price, ExitReason
        
        p = Portfolio.create_default()
        
        # Open position with small loss at time stop
        sig = _make_signal(price=100, sl=95, tp=110, source=Source.AMT)
        sig.metadata = {"strike": 24000}
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        
        # Simulate time stop with small loss (below entry)
        import time
        entry_time = time.time() - 2000  # 33+ minutes ago
        pos.entry_time = "2026-01-01T00:00:00Z"  # Over 30 min old
        
        exit = check_time_stop_with_price(
            position=pos,
            current_price=99.5,  # Below entry = loss
            current_time=time.time(),
            time_to_close=3600,
            max_hold_seconds=1800,
            scratch_threshold_pct=0.0005,
        )
        # Should exit due to time stop for small loss
        assert exit is not None

    def test_time_stop_r_multiple_at_one_r(self):
        """Test TIME_STOP doesn't exit when at 1R profit."""
        from app.domain.trading.models.entities import Position
        from app.domain.fabio_ai.services.exit_rules import check_time_stop_with_price
        import time
        
        p = Portfolio.create_default()
        
        # Create position manually with 1R profit
        pos = Position(
            id="test-1r",
            symbol="TEST",
            side=Side.LONG,
            source=Source.AMT,
            entry_price=100,
            size=1,
            stop_loss=95,
            take_profit=110,
            pnl=5,  # 1R profit
            entry_time="2026-01-01T00:00:00Z",
            status=PositionStatus.OPEN,
            initial_stop=95,
        )
        p.positions.append(pos)
        
        # At 1.03R profit (price = 105, entry = 100, SL = 95)
        exit = check_time_stop_with_price(
            position=pos,
            current_price=105,  # 1.03R profit (5 points vs 5 point risk)
            current_time=time.time(),
            time_to_close=3600,
            max_hold_seconds=1800,
            scratch_threshold_pct=0.0005,
        )
        # Should NOT exit - at 1R, activate trailing instead
        assert exit is None or exit.reason != ExitReason.TIME_STOP
