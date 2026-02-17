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
