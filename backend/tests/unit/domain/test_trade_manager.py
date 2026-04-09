"""Tests for ExitEngine — deterministic trade management logic.

Tests the stateless Position-based API where Position objects are passed
directly to check_position() and other methods.
"""

import time
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.domain.fabio_ai.services.trade_manager import (
    CushionState,
    ExitReason,
    ExitSignal,
    TradeManager,
    TradeManagerConfig,
)
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side


def create_position(
    position_id: str = "P1",
    symbol: str = "NIFTY",
    side: str = "LONG",
    entry_price: float = 100.0,
    stop_loss: float = 95.0,
    take_profit: float = 115.0,
    entry_time: str | None = None,
    session_phase: str = "",
    is_expiry: bool = False,
) -> Position:
    """Helper to create a Position entity for testing."""
    pos = Position(
        id=position_id,
        symbol=symbol,
        side=Side.LONG if side == "LONG" else Side.SHORT,
        entry_price=Decimal(str(entry_price)),
        stop_loss=Decimal(str(stop_loss)),
        take_profit=Decimal(str(take_profit)),
        initial_stop=Decimal(str(stop_loss)),
        entry_time=entry_time or "",
        session_phase=session_phase,
        is_expiry=is_expiry,
    )
    return pos


@pytest.fixture
def mgr() -> TradeManager:
    return TradeManager()


# ---- 1. Stop Loss — Long ----


def test_stop_loss_long(mgr: TradeManager):
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    sig = mgr.check_position(pos, 95.0)
    assert sig is not None
    assert sig.reason == ExitReason.STOP_LOSS
    assert sig.exit_price == 95.0


# ---- 2. Stop Loss — Short ----


def test_stop_loss_short(mgr: TradeManager):
    pos = create_position("P1", "NIFTY", "SHORT", 100.0, 105.0, 85.0)
    sig = mgr.check_position(pos, 105.0)
    assert sig is not None
    assert sig.reason == ExitReason.STOP_LOSS


# ---- 3. No Exit ----


def test_no_exit_when_price_between_sl_and_tp(mgr: TradeManager):
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    # Price at 102 is within SL-TP range
    sig = mgr.check_position(pos, 102.0)
    assert sig is None


# ---- 4. Time Stop ----


def test_time_stop(mgr: TradeManager):
    config = TradeManagerConfig(max_hold_seconds=60)
    mgr = TradeManager(config)
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    # Set entry_time to 120 seconds ago
    from datetime import datetime, timezone
    entry_time = datetime.fromtimestamp(time.time() - 120, tz=timezone.utc).isoformat()
    pos.entry_time = entry_time

    # Advance past grace period (5 ticks)
    for _ in range(6):
        sig = mgr.check_position(pos, 102.0)
    assert sig is not None
    assert sig.reason == ExitReason.TIME_STOP


# ---- 5. Cooldown ----


def test_cooldown_expires():
    config = TradeManagerConfig(cooldown_seconds=0.05)
    mgr = TradeManager(config)
    # Record exit time to start cooldown
    mgr.record_exit_time("NIFTY")
    assert mgr.in_cooldown("NIFTY") is True
    time.sleep(0.1)
    assert mgr.in_cooldown("NIFTY") is False


# ---- 6. MAE/MFE tracking ----


def test_mae_mfe_tracking():
    """MAE and MFE should be tracked as price moves."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 90.0, 120.0)
    
    # Price goes up (MFE)
    mgr.check_position(pos, 104.0)
    assert float(pos.mfe) == 4.0
    assert float(pos.mae) == 0.0
    
    # Price drops below entry (MAE) — but above stop
    mgr.check_position(pos, 97.0)
    assert float(pos.mae) == 3.0
    assert float(pos.mfe) == 4.0  # MFE shouldn't decrease


def test_initial_stop_preserved():
    """Initial stop should be stored separately from current stop."""
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    assert float(pos.initial_stop) == 95.0
    # Move stop to break-even
    pos.stop_loss = Decimal("100.0")
    assert float(pos.initial_stop) == 95.0  # unchanged


# ---- 7. Position metrics ----


def test_position_metrics():
    """get_position_metrics should return lifecycle metrics."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    mgr.check_position(pos, 106.0)

    metrics = mgr.get_position_metrics(pos)
    assert metrics is not None
    assert "tick_count" in metrics
    assert "runner_active" in metrics
    assert metrics["tick_count"] >= 1


# ---- 8. CVD Breakeven ----


def test_cvd_breakeven_long():
    """CVD confirms LONG direction (positive slope) -> SL moves to entry."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    moved = mgr.apply_cvd_breakeven(pos, cvd_slope=0.5)
    assert moved is True
    assert pos.breakeven_set is True
    assert float(pos.stop_loss) == 100.0


def test_cvd_breakeven_short():
    """CVD confirms SHORT direction (negative slope) -> SL moves to entry."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "SHORT", 100.0, 105.0, 85.0)
    
    moved = mgr.apply_cvd_breakeven(pos, cvd_slope=-0.5)
    assert moved is True
    assert pos.breakeven_set is True
    assert float(pos.stop_loss) == 100.0


def test_cvd_breakeven_wrong_direction_no_move():
    """CVD opposing trade direction should NOT move SL to breakeven."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    moved = mgr.apply_cvd_breakeven(pos, cvd_slope=-0.5)
    assert moved is False
    assert pos.breakeven_set is False
    assert float(pos.stop_loss) == 95.0


def test_cvd_breakeven_noise_skipped():
    """CVD slope below minimum threshold should NOT trigger breakeven."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    # Noise-level slope (0.2 < 0.5 threshold)
    moved = mgr.apply_cvd_breakeven(pos, cvd_slope=0.2)
    assert moved is False
    assert pos.breakeven_set is False
    assert float(pos.stop_loss) == 95.0


def test_cvd_breakeven_then_doji_holds():
    """After CVD triggers breakeven, a doji candle should hold at BE."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    mgr.apply_cvd_breakeven(pos, cvd_slope=0.5)
    assert pos.breakeven_set is True
    
    # Doji-like: price stays near entry, slightly above SL (breakeven)
    sig = mgr.check_position(pos, 100.1)
    assert sig is None  # no exit, position holds at breakeven


# ---- 9. Spread Blowout Detection ----


def test_spread_below_threshold_no_exit():
    """Spread < 3% of premium should not trigger exit."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    # Premium=100, spread=2 (2% < 3%)
    sig = mgr.check_spread_blowout(pos, best_bid=99.0, best_ask=101.0, premium=100.0)
    assert sig is None


def test_spread_at_threshold_triggers_exit():
    """Spread exactly at 3% of premium should trigger SPREAD_BLOWOUT exit."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    # Premium=100, spread=3 (3% == 3%)
    sig = mgr.check_spread_blowout(pos, best_bid=98.5, best_ask=101.5, premium=100.0)
    assert sig is not None
    assert sig.reason == ExitReason.SPREAD_BLOWOUT
    assert sig.exit_price == 100.0  # midpoint of bid/ask


def test_spread_above_threshold_triggers_exit():
    """Spread > 3% of premium should trigger SPREAD_BLOWOUT exit."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    # Premium=100, spread=5 (5% > 3%)
    sig = mgr.check_spread_blowout(pos, best_bid=97.5, best_ask=102.5, premium=100.0)
    assert sig is not None
    assert sig.reason == ExitReason.SPREAD_BLOWOUT


def test_spread_no_order_book_data_skips():
    """Missing order book data (bid/ask <= 0) should skip gracefully."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    # Zero bid/ask
    assert mgr.check_spread_blowout(pos, best_bid=0, best_ask=0, premium=100.0) is None
    # Negative values
    assert mgr.check_spread_blowout(pos, best_bid=-1, best_ask=101, premium=100.0) is None
    # Zero premium
    assert mgr.check_spread_blowout(pos, best_bid=99, best_ask=101, premium=0) is None


# ---- 10. Session-Aware Time Stops ----


def test_session_time_stop_morning_balanced():
    """Morning balanced session should use 1200s time stop."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED",
        session_phase="MORNING",
        is_expiry=False,
        time_to_close=0.0,
    )
    assert stop == 1200.0


def test_session_time_stop_afternoon_imbalanced():
    """Afternoon imbalanced session should use 1800s time stop."""
    stop = TradeManager.get_session_time_stop(
        market_state="IMBALANCED",
        session_phase="AFTERNOON",
        is_expiry=False,
        time_to_close=0.0,
    )
    assert stop == 1800.0


def test_session_time_stop_expiry_day():
    """Expiry day should use flat 600s regardless of session/state."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED",
        session_phase="MORNING",
        is_expiry=True,
        time_to_close=0.0,
    )
    assert stop == 600.0


def test_session_time_stop_near_close():
    """Near close: min(phase_stop, time_to_close - 300)."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED",
        session_phase="MORNING",
        is_expiry=False,
        time_to_close=1200.0,
    )
    assert stop == 900.0


def test_session_time_stop_very_near_close():
    """Less than 5 min to close should force immediate exit (1s)."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED",
        session_phase="MORNING",
        is_expiry=False,
        time_to_close=200.0,
    )
    assert stop == 1.0


def test_session_time_stop_no_session_fallback():
    """No session data should fall back to 1800/7200."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED",
        session_phase="",
        is_expiry=False,
        time_to_close=0.0,
    )
    assert stop == 1800.0

    stop = TradeManager.get_session_time_stop(
        market_state="IMBALANCED",
        session_phase="",
        is_expiry=False,
        time_to_close=0.0,
    )
    assert stop == 7200.0


def test_session_time_stop_morning_imbalanced():
    """Morning imbalanced session should use 2700s."""
    stop = TradeManager.get_session_time_stop(
        market_state="IMBALANCED",
        session_phase="MORNING",
        is_expiry=False,
        time_to_close=0.0,
    )
    assert stop == 2700.0


def test_session_time_stop_afternoon_balanced():
    """Afternoon balanced session should use 900s."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED",
        session_phase="AFTERNOON",
        is_expiry=False,
        time_to_close=0.0,
    )
    assert stop == 900.0


# ---- 11. VWAP Trail Tests ----


def test_vwap_trail_at_1_5r_long():
    """At 1.5R profit, SL moves to nearest VWAP band above entry."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    # VWAP bands: vwap=100, upper1=103, upper2=106, lower1=97, lower2=94
    # Price at 107.5 -> 1.5R profit
    mgr.apply_vwap_trail(
        pos,
        current_price=107.5,
        vwap=100.0,
        vwap_upper_1=103.0,
        vwap_lower_1=97.0,
        vwap_upper_2=106.0,
        vwap_lower_2=94.0,
    )
    # Should trail to highest band below price and above entry: 106
    # But 1.5R floor = 100 + 7.5 = 107.5, so floor dominates
    assert float(pos.stop_loss) >= 107.5


def test_vwap_trail_at_2sigma_tighten():
    """At 2 sigma overextension, SL tightened to 50% of current distance."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    # Price at vwap_upper_2 (110) -> overextended, triggers 2sigma tighten
    mgr.apply_vwap_trail(
        pos,
        current_price=110.0,
        vwap=100.0,
        vwap_upper_1=103.0,
        vwap_lower_1=97.0,
        vwap_upper_2=110.0,
        vwap_lower_2=90.0,
    )
    # 1.5R floor = 100 + 7.5 = 107.5
    assert float(pos.stop_loss) >= 107.5


def test_vwap_trail_cap_at_1_5r():
    """High-vol wide bands: trail capped at 1.5R distance from entry."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 120.0)
    
    # Very wide VWAP bands
    mgr.apply_vwap_trail(
        pos,
        current_price=108.0,
        vwap=100.0,
        vwap_upper_1=101.0,
        vwap_lower_1=99.0,
        vwap_upper_2=102.0,
        vwap_lower_2=98.0,
    )
    # 1.5R floor = 100 + 7.5 = 107.5
    assert float(pos.stop_loss) >= 107.5


# ---- 12. Imbalance Tighten Tests ----


class TestImbalanceTighten:
    def test_opposing_imbalance_tightens_sl_long(self):
        """LONG position + SELL imbalance -> SL tightened by 30% of distance."""
        from app.domain.trading.models.value_objects import StackedImbalance

        mgr = TradeManager()
        pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
        
        imbalances = [
            StackedImbalance(
                direction="SELL",
                price_low=99,
                price_high=101,
                magnitude=3,
                candle_time="t1",
            ),
        ]
        result = mgr.check_imbalance_tighten(pos, imbalances, current_price=102.0)
        assert result is True
        # distance = 102 - 95 = 7, tighten by 30% = 2.1, new SL = 95 + 2.1 = 97.1
        assert float(pos.stop_loss) == pytest.approx(97.1)

    def test_aligned_imbalance_no_tighten(self):
        """LONG position + BUY imbalance -> no tighten."""
        from app.domain.trading.models.value_objects import StackedImbalance

        mgr = TradeManager()
        pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
        
        imbalances = [
            StackedImbalance(
                direction="BUY",
                price_low=99,
                price_high=101,
                magnitude=3,
                candle_time="t1",
            ),
        ]
        result = mgr.check_imbalance_tighten(pos, imbalances, current_price=102.0)
        assert result is False
        assert float(pos.stop_loss) == 95.0

    def test_no_imbalances_no_tighten(self):
        """Empty list -> False."""
        mgr = TradeManager()
        pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
        
        assert mgr.check_imbalance_tighten(pos, [], current_price=102.0) is False

    def test_opposing_imbalance_tightens_sl_short(self):
        """SHORT position + BUY imbalance -> SL tightened by 30%."""
        from app.domain.trading.models.value_objects import StackedImbalance

        mgr = TradeManager()
        pos = create_position("P1", "NIFTY", "SHORT", 100.0, 105.0, 85.0)
        
        imbalances = [
            StackedImbalance(
                direction="BUY",
                price_low=99,
                price_high=101,
                magnitude=3,
                candle_time="t1",
            ),
        ]
        result = mgr.check_imbalance_tighten(pos, imbalances, current_price=98.0)
        assert result is True
        # distance = 105 - 98 = 7, tighten by 30% = 2.1, new SL = 105 - 2.1 = 102.9
        assert float(pos.stop_loss) == pytest.approx(102.9)


# ---- 13. Per-Symbol Daily Loss Limits ----


def test_daily_loss_limit_isolation():
    """Verify daily losses are isolated per-symbol but respect a global limit multiplier."""
    mgr = TradeManager()
    mgr.MAX_DAILY_LOSSES = 2

    mgr.record_loss("NIFTY")
    assert not mgr.should_block_entry("NIFTY")
    assert not mgr.should_block_entry("BANKNIFTY")

    mgr.record_loss("NIFTY")
    # NIFTY should be blocked (reached its limit of 2)
    assert mgr.should_block_entry("NIFTY")
    # BANKNIFTY should NOT be blocked (has 0 losses)
    assert not mgr.should_block_entry("BANKNIFTY")

    # Global limit allows more symbols to trade
    mgr.record_loss("BANKNIFTY")
    mgr.record_loss("BANKNIFTY")
    assert mgr.should_block_entry("BANKNIFTY")

    # Global limit = MAX_DAILY_LOSSES * 3 = 6
    assert mgr._global_daily_losses == 4
    assert not mgr.should_block_entry("FINNIFTY")

    mgr.record_loss("FINNIFTY")
    mgr.record_loss("FINNIFTY")
    assert mgr._global_daily_losses == 6

    # Now global limit is reached, EVERY symbol should be blocked
    assert mgr.should_block_entry("MIDCPNIFTY")


# ---- 14. Consecutive Loss Circuit Breaker Tests ----


class TestConsecutiveLossCircuitBreaker:
    def test_blocks_after_two_consecutive_losses(self):
        """Should block entry after 2 consecutive stop-outs in the same zone."""
        mgr = TradeManager()
        # Record two losses
        mgr.record_loss("NIFTY", stop_price=100.0)
        mgr.record_loss("NIFTY", stop_price=99.0)

        # Checking entry at 99.5, with ATR 1.0 (requires 1.5 distance)
        blocked = mgr.should_block_entry("NIFTY", current_price=99.5, current_atr=1.0)
        assert blocked is True

    def test_allows_reentry_if_price_moves_beyond_atr_buffer(self):
        """Should ALLOW entry if price has moved > 1.5 ATR from bloodbath zone."""
        mgr = TradeManager()
        # Record two losses
        mgr.record_loss("NIFTY", stop_price=100.0)
        mgr.record_loss("NIFTY", stop_price=99.0)

        # Distance from last stop (99.0) is 2.0. 1.5 * 1.0 = 1.5
        blocked = mgr.should_block_entry("NIFTY", current_price=97.0, current_atr=1.0)
        assert blocked is False

    def test_resets_consecutive_losses_on_profit(self):
        """Should reset consecutive loss counter when a partial or full TP hits."""
        mgr = TradeManager()
        # Record one loss
        mgr.record_loss("NIFTY", stop_price=100.0)

        # A profit trade clears it
        mgr.reset_consecutive_losses("NIFTY")

        # Another single loss happens
        mgr.record_loss("NIFTY", stop_price=100.0)

        # Now we only have 1 consecutive loss, so entry shouldn't be blocked!
        blocked = mgr.should_block_entry("NIFTY", current_price=100.5, current_atr=1.0)
        assert blocked is False


# ---- 15. Scale-In Tests ----


def test_scale_in_confirmation_step():
    """Scale-in step 2 triggers when price confirms direction."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    pos.scale_step = 1
    pos.scale_confirm_price = Decimal("102.0")
    
    # Price reaches confirmation level
    add_pct = mgr.check_scale_in(pos, current_price=102.0)
    assert add_pct == 0.3  # Add 30%
    assert pos.scale_step == 2


def test_scale_in_breakout_step():
    """Scale-in step 3 triggers on breakout."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    pos.scale_step = 2
    pos.scale_breakout_price = Decimal("105.0")
    
    # Price reaches breakout level
    add_pct = mgr.check_scale_in(pos, current_price=105.0)
    assert add_pct == 0.3  # Add 30%
    assert pos.scale_step == 3


# ---- 16. CVD Kill Signal Tests ----


def test_cvd_kill_signal_bearish_div_long():
    """CVD bearish divergence on LONG should scratch or move SL to BE."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    
    # Bearish divergence, partial not taken yet
    sig = mgr.apply_cvd_kill_signal(pos, "BEARISH_DIV", current_price=102.0)
    # Should move SL to breakeven
    assert float(pos.stop_loss) == 100.0
    assert sig is None


def test_cvd_kill_signal_bearish_div_long_partial_taken():
    """CVD bearish divergence on LONG with partial taken should scratch."""
    mgr = TradeManager()
    pos = create_position("P1", "NIFTY", "LONG", 100.0, 95.0, 115.0)
    pos.partial_taken = True
    
    sig = mgr.apply_cvd_kill_signal(pos, "BEARISH_DIV", current_price=102.0)
    assert sig is not None
    assert sig.reason == ExitReason.SCRATCH


# ---- 17. Dynamic Risk Tests ----


def test_dynamic_risk_conservative_when_negative():
    """Dynamic risk should be conservative when session PnL is negative."""
    mgr = TradeManager()
    mgr.add_realized_pnl(-1000.0)
    
    risk_pct, mode = mgr.compute_dynamic_risk(base_capital=100000.0)
    assert risk_pct == 0.0025  # Conservative
    assert mode == "Conservative"


def test_dynamic_risk_scales_with_profit():
    """Dynamic risk should scale up with session profit."""
    mgr = TradeManager()
    mgr.add_realized_pnl(5000.0)
    
    risk_pct, mode = mgr.compute_dynamic_risk(base_capital=100000.0)
    assert risk_pct > 0.0025  # Higher than conservative
