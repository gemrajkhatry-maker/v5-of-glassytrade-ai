"""Tests for TradeManager — deterministic trade management logic."""

import time
from unittest.mock import patch

import pytest

from app.domain.fabio_ai.services.trade_manager import (
    ExitReason,
    ExitSignal,
    ManagedPosition,
    TradeManager,
    TradeManagerConfig,
)


@pytest.fixture
def mgr() -> TradeManager:
    return TradeManager()


# ---- 1. Registration ----

def test_register_position_creates_managed_position(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 99.0, 102.0)
    assert mgr.has_managed_positions
    assert mgr._positions["P1"].entry_price == 100.0
    assert mgr._positions["P1"].side == "LONG"


# ---- 2. Stop Loss — Long ----

def test_stop_loss_long(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    sig = mgr.check_position("P1", 95.0)
    assert sig is not None
    assert sig.reason == ExitReason.STOP_LOSS
    assert sig.exit_price == 95.0


# ---- 3. Stop Loss — Short ----

def test_stop_loss_short(mgr: TradeManager):
    mgr.register_position("P1", "SHORT", 100.0, 105.0, 90.0)
    sig = mgr.check_position("P1", 105.0)
    assert sig is not None
    assert sig.reason == ExitReason.STOP_LOSS


# ---- 4. Take Profit — Long ----

def test_take_profit_long(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    sig = mgr.check_position("P1", 110.0)
    assert sig is not None
    assert sig.reason == ExitReason.TAKE_PROFIT


# ---- 5. Take Profit — Short ----

def test_take_profit_short(mgr: TradeManager):
    mgr.register_position("P1", "SHORT", 100.0, 105.0, 90.0)
    sig = mgr.check_position("P1", 90.0)
    assert sig is not None
    assert sig.reason == ExitReason.TAKE_PROFIT


# ---- 6. No Exit ----

def test_no_exit_when_price_between_sl_and_tp(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    # Price at 102 is within SL-TP range and below partial TP threshold (105)
    sig = mgr.check_position("P1", 102.0)
    assert sig is None


# ---- 7. Trailing Stop Activation ----

def test_trailing_stop_activation(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=True)
    # TP distance = 10, 50% = 5, so price 105 triggers partial TP first
    sig = mgr.check_position("P1", 105.0)
    assert sig is not None
    assert sig.reason == ExitReason.PARTIAL_TAKE_PROFIT
    mp = mgr._positions["P1"]
    assert mp.partial_taken is True
    # Second check at same price should now activate trailing stop
    mgr.check_position("P1", 105.0)
    assert mp.trailing_active is True
    assert mp.trailing_stop > 0


# ---- 8. Trailing Stop Ratchet ----

def test_trailing_stop_ratchets_up(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=True)
    mgr.check_position("P1", 105.0)  # partial TP fires
    mgr.check_position("P1", 105.0)  # trail activates
    trail_1 = mgr._positions["P1"].trailing_stop

    mgr.check_position("P1", 107.0)  # price moves higher
    trail_2 = mgr._positions["P1"].trailing_stop
    assert trail_2 > trail_1  # trail ratcheted up

    mgr.check_position("P1", 106.0)  # price drops but above trail
    trail_3 = mgr._positions["P1"].trailing_stop
    assert trail_3 == trail_2  # trail did NOT move down


# ---- 9. Trailing Stop Hit ----

def test_trailing_stop_hit(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=True)
    mgr.check_position("P1", 105.0)  # partial TP fires
    mgr.check_position("P1", 105.0)  # trail activates
    trail = mgr._positions["P1"].trailing_stop
    # Price reverses to hit trailing stop (but SL is now at break-even=100)
    # Trail stop should be above break-even, so it triggers first
    sig = mgr.check_position("P1", trail)
    assert sig is not None
    assert sig.reason == ExitReason.TRAILING_STOP


# ---- 10. Trail Not Allowed ----

def test_trail_not_allowed(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=False)
    mgr.check_position("P1", 105.0)  # partial TP fires at 50% of TP distance
    mgr.check_position("P1", 105.0)  # second check — trail should NOT activate
    mp = mgr._positions["P1"]
    assert mp.trailing_active is False


# ---- 11. Time Stop ----

def test_time_stop(mgr: TradeManager):
    config = TradeManagerConfig(max_hold_seconds=60)
    mgr = TradeManager(config)
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    # Backdate entry_time
    mgr._positions["P1"].entry_time = time.time() - 120
    # Advance past grace period (5 ticks)
    for _ in range(5):
        mgr.check_position("P1", 102.0)
    sig = mgr.check_position("P1", 102.0)
    assert sig is not None
    assert sig.reason == ExitReason.TIME_STOP


# ---- 12. Cooldown ----

def test_cooldown_after_unregister(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    mgr.unregister_position("P1")
    assert mgr.in_cooldown() is True


def test_cooldown_expires():
    config = TradeManagerConfig(cooldown_seconds=0.05)
    mgr = TradeManager(config)
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    mgr.unregister_position("P1")
    time.sleep(0.1)
    assert mgr.in_cooldown() is False


# ---- 13. Unregistered Position ----

def test_check_unknown_position(mgr: TradeManager):
    assert mgr.check_position("UNKNOWN", 100.0) is None


# ---- 14. has_managed_positions ----

def test_has_managed_positions(mgr: TradeManager):
    assert mgr.has_managed_positions is False
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    assert mgr.has_managed_positions is True
    mgr.unregister_position("P1")
    assert mgr.has_managed_positions is False


# ---- 15. Runner logic (Trend model) ----

def test_runner_activates_on_tp_with_allow_trail():
    """When allow_trail=True and TP is hit, runner should activate (partial exit)."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=True, market_state="IMBALANCED")
    # Price hits TP
    result = mgr.check_position("P1", 110.0)
    assert result is not None
    assert result.reason == ExitReason.PARTIAL_TAKE_PROFIT
    # Runner should be active now
    mp = mgr._positions["P1"]
    assert mp.runner_active is True
    assert mp.trailing_active is True
    assert mp.stop_loss == 100.0  # moved to break-even


def test_no_runner_on_mean_reversion():
    """Mean reversion (allow_trail=False) should close 100% at TP."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=False, market_state="BALANCED")
    result = mgr.check_position("P1", 110.0)
    assert result is not None
    assert result.reason == ExitReason.TAKE_PROFIT  # full close, not partial


# ---- 16. MAE/MFE tracking ----

def test_mae_mfe_tracking():
    """MAE and MFE should be tracked as price moves."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 90.0, 120.0)
    # Price goes up (MFE) — below partial TP threshold
    mgr.check_position("P1", 104.0)
    mp = mgr._positions["P1"]
    assert mp.mfe == 4.0
    assert mp.mae == 0.0
    # Price drops below entry (MAE) — but above stop
    mgr.check_position("P1", 97.0)
    assert mp.mae == 3.0
    assert mp.mfe == 4.0  # MFE shouldn't decrease


def test_initial_stop_preserved():
    """Initial stop should be stored separately from current stop."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    mp = mgr._positions["P1"]
    assert mp.initial_stop == 95.0
    # Move stop to break-even
    mp.stop_loss = 100.0
    assert mp.initial_stop == 95.0  # unchanged


# ---- 17. R-multiple in position state ----

def test_r_multiple_in_position_state():
    """get_position_state should include r_multiple."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    state = mgr.get_position_state("P1", 105.0)
    assert "r_multiple" in state
    assert state["r_multiple"] == 1.0  # 5.0 unrealised / 5.0 risk = 1R
    assert "mae" in state
    assert "mfe" in state


# ---- 18. Volatility filter ----

def test_zero_volume_blocks_entry():
    """Zero-volume tick should block LLM entry."""
    from app.domain.fabio_ai.services.entry_gate import check_volatility_filter
    from app.domain.trading.models.value_objects import OHLC

    tick = OHLC(time="t", open=100, high=101, low=99, close=100, volume=0)
    assert check_volatility_filter([], tick) is True  # blocked


# ---- 19. Breakeven at 1R ----

def test_breakeven_at_1r_long():
    """When unrealised profit reaches 1R, SL should move to entry price."""
    mgr = TradeManager()
    # Entry=100, SL=95 -> risk=5. 1R profit at price=105.
    mgr.register_position("P1", "LONG", 100.0, 95.0, 115.0)
    sig = mgr.check_position("P1", 105.0)
    mp = mgr._positions["P1"]
    assert mp.breakeven_set is True
    assert mp.stop_loss == 100.0  # moved to entry (breakeven)
    # No exit signal, just SL adjustment
    assert sig is None


def test_breakeven_at_1r_short():
    """Short position: 1R profit moves SL to entry."""
    mgr = TradeManager()
    # Entry=100, SL=105 -> risk=5. 1R profit at price=95.
    mgr.register_position("P1", "SHORT", 100.0, 105.0, 85.0)
    mgr.check_position("P1", 95.0)
    mp = mgr._positions["P1"]
    assert mp.breakeven_set is True
    assert mp.stop_loss == 100.0


def test_sl_never_below_entry_once_breakeven_set():
    """Once breakeven_set=True, SL must never go below entry for LONG."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 115.0)
    # Trigger breakeven
    mgr.check_position("P1", 105.0)
    mp = mgr._positions["P1"]
    assert mp.breakeven_set is True
    assert mp.stop_loss == 100.0
    # Attempt to adjust SL below entry — should be rejected
    result = mgr.adjust_stop_loss("P1", 98.0)
    assert result is False
    assert mp.stop_loss == 100.0  # unchanged


def test_cvd_breakeven_long():
    """CVD confirms LONG direction (positive slope) -> SL moves to entry."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 115.0)
    # Positive CVD slope confirms long
    moved = mgr.apply_cvd_breakeven("P1", cvd_slope=0.5)
    mp = mgr._positions["P1"]
    assert moved is True
    assert mp.breakeven_set is True
    assert mp.stop_loss == 100.0


def test_cvd_breakeven_short():
    """CVD confirms SHORT direction (negative slope) -> SL moves to entry."""
    mgr = TradeManager()
    mgr.register_position("P1", "SHORT", 100.0, 105.0, 85.0)
    moved = mgr.apply_cvd_breakeven("P1", cvd_slope=-0.5)
    mp = mgr._positions["P1"]
    assert moved is True
    assert mp.breakeven_set is True
    assert mp.stop_loss == 100.0


def test_cvd_breakeven_wrong_direction_no_move():
    """CVD opposing trade direction should NOT move SL to breakeven."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 115.0)
    moved = mgr.apply_cvd_breakeven("P1", cvd_slope=-0.5)
    mp = mgr._positions["P1"]
    assert moved is False
    assert mp.breakeven_set is False
    assert mp.stop_loss == 95.0


def test_partial_tp_still_fires_after_breakeven():
    """Partial TP should still fire at correct distance (no regression)."""
    mgr = TradeManager()
    # Entry=100, SL=95, TP=110 -> risk=5, partial at 50% of TP dist = 5
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    # First reach 1R (price=105) -> breakeven set, partial also fires (50% of 10 = 5)
    sig = mgr.check_position("P1", 105.0)
    mp = mgr._positions["P1"]
    assert mp.breakeven_set is True
    # Partial TP fires at same threshold
    assert sig is not None
    assert sig.reason == ExitReason.PARTIAL_TAKE_PROFIT


def test_trailing_activates_at_1r():
    """Trailing stop should activate at 1R instead of 50% TP distance."""
    mgr = TradeManager()
    # Entry=100, SL=95, TP=120 -> risk=5, 1R at 105
    # Old 50% TP activation = 110, new 1R activation = 105
    mgr.register_position("P1", "LONG", 100.0, 95.0, 120.0, allow_trail=True)
    # Price at 105 = 1R profit. Trail should activate.
    mgr.check_position("P1", 105.0)  # breakeven + partial
    mgr.check_position("P1", 105.0)  # trail activation
    mp = mgr._positions["P1"]
    assert mp.trailing_active is True


def test_tight_sl_wide_spread_edge_case():
    """Tight SL (small risk) should still trigger breakeven at 1R."""
    mgr = TradeManager()
    # Entry=100, SL=99.5 -> risk=0.5. 1R at 100.5.
    mgr.register_position("P1", "LONG", 100.0, 99.5, 105.0)
    mgr.check_position("P1", 100.5)
    mp = mgr._positions["P1"]
    assert mp.breakeven_set is True
    assert mp.stop_loss == 100.0


def test_cvd_breakeven_then_doji_holds():
    """After CVD triggers breakeven, a doji candle should hold at BE."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 115.0)
    mgr.apply_cvd_breakeven("P1", cvd_slope=0.5)
    mp = mgr._positions["P1"]
    assert mp.breakeven_set is True
    # Doji-like: price stays near entry, slightly above SL (breakeven)
    sig = mgr.check_position("P1", 100.1)
    assert sig is None  # no exit, position holds at breakeven


# ---- 22. Spread Blowout Detection ----

def test_spread_below_threshold_no_exit():
    """Spread < 3% of premium should not trigger exit."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    # Premium=100, spread=2 (2% < 3%)
    sig = mgr.check_spread_blowout("P1", best_bid=99.0, best_ask=101.0, premium=100.0)
    assert sig is None


def test_spread_at_threshold_triggers_exit():
    """Spread exactly at 3% of premium should trigger SPREAD_BLOWOUT exit."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    # Premium=100, spread=3 (3% == 3%)
    sig = mgr.check_spread_blowout("P1", best_bid=98.5, best_ask=101.5, premium=100.0)
    assert sig is not None
    assert sig.reason == ExitReason.SPREAD_BLOWOUT
    assert sig.exit_price == 100.0  # midpoint of bid/ask


def test_spread_above_threshold_triggers_exit():
    """Spread > 3% of premium should trigger SPREAD_BLOWOUT exit."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    # Premium=100, spread=5 (5% > 3%)
    sig = mgr.check_spread_blowout("P1", best_bid=97.5, best_ask=102.5, premium=100.0)
    assert sig is not None
    assert sig.reason == ExitReason.SPREAD_BLOWOUT


def test_spread_no_order_book_data_skips():
    """Missing order book data (bid/ask <= 0) should skip gracefully."""
    mgr = TradeManager()
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
    # Zero bid/ask
    assert mgr.check_spread_blowout("P1", best_bid=0, best_ask=0, premium=100.0) is None
    # Negative values
    assert mgr.check_spread_blowout("P1", best_bid=-1, best_ask=101, premium=100.0) is None
    # Zero premium
    assert mgr.check_spread_blowout("P1", best_bid=99, best_ask=101, premium=0) is None


def test_spread_unknown_position_returns_none():
    """Spread check on unknown position should return None."""
    mgr = TradeManager()
    sig = mgr.check_spread_blowout("UNKNOWN", best_bid=99, best_ask=101, premium=100.0)
    assert sig is None


# ---- Session-Aware Time Stops ----

def test_session_time_stop_morning_balanced():
    """Morning balanced session should use 1200s time stop."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED", session_phase="MORNING",
        is_expiry=False, time_to_close=0.0,
    )
    assert stop == 1200.0


def test_session_time_stop_afternoon_imbalanced():
    """Afternoon imbalanced session should use 1800s time stop."""
    stop = TradeManager.get_session_time_stop(
        market_state="IMBALANCED", session_phase="AFTERNOON",
        is_expiry=False, time_to_close=0.0,
    )
    assert stop == 1800.0


def test_session_time_stop_expiry_day():
    """Expiry day should use flat 600s regardless of session/state."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED", session_phase="MORNING",
        is_expiry=True, time_to_close=0.0,
    )
    assert stop == 600.0


def test_session_time_stop_near_close():
    """Near close: min(phase_stop, time_to_close - 300)."""
    # 20 min to close = 1200s; phase stop for morning balanced = 1200s
    # near_close = 1200 - 300 = 900; min(1200, 900) = 900
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED", session_phase="MORNING",
        is_expiry=False, time_to_close=1200.0,
    )
    assert stop == 900.0


def test_session_time_stop_very_near_close():
    """Less than 5 min to close should force immediate exit (1s)."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED", session_phase="MORNING",
        is_expiry=False, time_to_close=200.0,
    )
    assert stop == 1.0


def test_session_time_stop_never_shrinks():
    """BALANCED -> IMBALANCED mid-trade: time stop should extend, never shrink."""
    mgr = TradeManager()
    entry_time = time.time() - 100  # entered 100s ago
    mgr.register_position(
        "P1", "LONG", 100.0, 95.0, 110.0,
        market_state="BALANCED", session_phase="MORNING",
        entry_time=entry_time,
    )
    mp = mgr._positions["P1"]

    # First check: BALANCED morning -> 1200s
    for _ in range(5):
        mgr.check_position("P1", 102.0)
    mgr.check_position("P1", 102.0)
    assert mp.applied_time_stop == 1200.0

    # Market state changes to IMBALANCED -> 2700s (extends)
    mp.market_state = "IMBALANCED"
    mgr.check_position("P1", 102.0)
    assert mp.applied_time_stop == 2700.0

    # Change back to BALANCED -> should stay at 2700 (never shrink)
    mp.market_state = "BALANCED"
    mgr.check_position("P1", 102.0)
    assert mp.applied_time_stop == 2700.0


def test_session_time_stop_no_session_fallback():
    """No session data should fall back to 1800/7200."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED", session_phase="",
        is_expiry=False, time_to_close=0.0,
    )
    assert stop == 1800.0

    stop = TradeManager.get_session_time_stop(
        market_state="IMBALANCED", session_phase="",
        is_expiry=False, time_to_close=0.0,
    )
    assert stop == 7200.0


def test_session_time_stop_fires_at_correct_time():
    """Position with session phase should exit at session-aware time stop."""
    config = TradeManagerConfig(max_hold_seconds=1800)
    mgr = TradeManager(config)
    entry_time = time.time() - 1300  # 1300s ago (>1200s morning balanced)
    mgr.register_position(
        "P1", "LONG", 100.0, 95.0, 110.0,
        market_state="BALANCED", session_phase="MORNING",
        entry_time=entry_time,
    )
    # Advance past grace period
    for _ in range(5):
        mgr.check_position("P1", 102.0)
    sig = mgr.check_position("P1", 102.0)
    assert sig is not None
    assert sig.reason == ExitReason.TIME_STOP


def test_session_time_stop_morning_imbalanced():
    """Morning imbalanced session should use 2700s."""
    stop = TradeManager.get_session_time_stop(
        market_state="IMBALANCED", session_phase="MORNING",
        is_expiry=False, time_to_close=0.0,
    )
    assert stop == 2700.0


def test_session_time_stop_afternoon_balanced():
    """Afternoon balanced session should use 900s."""
    stop = TradeManager.get_session_time_stop(
        market_state="BALANCED", session_phase="AFTERNOON",
        is_expiry=False, time_to_close=0.0,
    )
    assert stop == 900.0


# ---- VWAP Trail Tests ----

def test_vwap_trail_at_1_5r_long():
    """At 1.5R profit, SL moves to nearest VWAP band above entry."""
    mgr = TradeManager()
    # Entry=100, SL=95 -> risk=5. 1.5R profit at price=107.5
    mgr.register_position("P1", "LONG", 100.0, 95.0, 115.0, allow_trail=True)
    # VWAP bands: vwap=100, upper1=103, upper2=106, lower1=97, lower2=94
    mgr.apply_vwap_trail(
        "P1", current_price=107.5,
        vwap=100.0, vwap_upper_1=103.0, vwap_lower_1=97.0,
        vwap_upper_2=106.0, vwap_lower_2=94.0,
    )
    mp = mgr._positions["P1"]
    # Should trail to highest band below price and above entry: 106
    # But 1.5R floor = 100 + 7.5 = 107.5, so floor dominates
    assert mp.stop_loss >= 107.5


def test_vwap_trail_at_2sigma_tighten():
    """At 2 sigma overextension, SL tightened to 50% of current distance."""
    mgr = TradeManager()
    # Entry=100, SL=95 -> risk=5.
    mgr.register_position("P1", "LONG", 100.0, 95.0, 115.0, allow_trail=True)
    # Price at vwap_upper_2 (110) -> overextended, triggers 2sigma tighten
    # unrealised_r = (110 - 100) / 5 = 2.0 >= 1.5
    mgr.apply_vwap_trail(
        "P1", current_price=110.0,
        vwap=100.0, vwap_upper_1=103.0, vwap_lower_1=97.0,
        vwap_upper_2=110.0, vwap_lower_2=90.0,
    )
    mp = mgr._positions["P1"]
    # 2sigma tighten: current_distance = 110 - 95 = 15, tightened = 110 - 7.5 = 102.5
    # 1.5R floor = 100 + 7.5 = 107.5
    # max(107.5, 102.5) = 107.5
    assert mp.stop_loss >= 107.5


# ---- Imbalance Tighten Tests (Task 21) ----

class TestImbalanceTighten:
    def test_opposing_imbalance_tightens_sl_long(self):
        """LONG position + SELL imbalance -> SL tightened by 30% of distance."""
        from app.domain.trading.models.value_objects import StackedImbalance
        mgr = TradeManager()
        mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
        imbalances = [
            StackedImbalance(direction="SELL", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
        ]
        result = mgr.check_imbalance_tighten("P1", imbalances, current_price=102.0)
        assert result is True
        mp = mgr._positions["P1"]
        # distance = 102 - 95 = 7, tighten by 30% = 2.1, new SL = 95 + 2.1 = 97.1
        assert mp.stop_loss == pytest.approx(97.1)

    def test_aligned_imbalance_no_tighten(self):
        """LONG position + BUY imbalance -> no tighten."""
        from app.domain.trading.models.value_objects import StackedImbalance
        mgr = TradeManager()
        mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
        imbalances = [
            StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
        ]
        result = mgr.check_imbalance_tighten("P1", imbalances, current_price=102.0)
        assert result is False
        assert mgr._positions["P1"].stop_loss == 95.0

    def test_no_imbalances_no_tighten(self):
        """Empty list -> False."""
        mgr = TradeManager()
        mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0)
        assert mgr.check_imbalance_tighten("P1", [], current_price=102.0) is False

    def test_unknown_position_returns_false(self):
        """Bad position_id -> False."""
        mgr = TradeManager()
        assert mgr.check_imbalance_tighten("UNKNOWN", [], current_price=102.0) is False

    def test_opposing_imbalance_tightens_sl_short(self):
        """SHORT position + BUY imbalance -> SL tightened by 30%."""
        from app.domain.trading.models.value_objects import StackedImbalance
        mgr = TradeManager()
        mgr.register_position("P1", "SHORT", 100.0, 105.0, 90.0)
        imbalances = [
            StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
        ]
        result = mgr.check_imbalance_tighten("P1", imbalances, current_price=98.0)
        assert result is True
        mp = mgr._positions["P1"]
        # distance = 105 - 98 = 7, tighten by 30% = 2.1, new SL = 105 - 2.1 = 102.9
        assert mp.stop_loss == pytest.approx(102.9)


def test_vwap_trail_cap_at_1_5r():
    """High-vol wide bands: trail capped at 1.5R distance from entry."""
    mgr = TradeManager()
    # Entry=100, SL=95 -> risk=5
    mgr.register_position("P1", "LONG", 100.0, 95.0, 120.0, allow_trail=True)
    # Very wide VWAP bands — nearest valid band is far below
    # Price at 108 -> unrealised_r = 8/5 = 1.6 >= 1.5
    mgr.apply_vwap_trail(
        "P1", current_price=108.0,
        vwap=100.0, vwap_upper_1=101.0, vwap_lower_1=99.0,
        vwap_upper_2=102.0, vwap_lower_2=98.0,
    )
    mp = mgr._positions["P1"]
    # Valid bands below price and above entry: 100, 101, 102
    # max valid = 102, but 1.5R floor = 100 + 7.5 = 107.5
    # max(102, 107.5) = 107.5
    assert mp.stop_loss >= 107.5
