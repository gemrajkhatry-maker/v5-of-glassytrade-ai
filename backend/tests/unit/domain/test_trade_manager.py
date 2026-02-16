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
    sig = mgr.check_position("P1", 102.0)
    assert sig is None


# ---- 7. Trailing Stop Activation ----

def test_trailing_stop_activation(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=True)
    # TP distance = 10, 50% = 5, so price 105 should activate
    mgr.check_position("P1", 105.0)
    mp = mgr._positions["P1"]
    assert mp.trailing_active is True
    assert mp.trailing_stop > 0


# ---- 8. Trailing Stop Ratchet ----

def test_trailing_stop_ratchets_up(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=True)
    mgr.check_position("P1", 105.0)  # activate
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
    mgr.check_position("P1", 105.0)  # activate
    trail = mgr._positions["P1"].trailing_stop
    # Price reverses to hit trailing stop
    sig = mgr.check_position("P1", trail)
    assert sig is not None
    assert sig.reason == ExitReason.TRAILING_STOP


# ---- 10. Trail Not Allowed ----

def test_trail_not_allowed(mgr: TradeManager):
    mgr.register_position("P1", "LONG", 100.0, 95.0, 110.0, allow_trail=False)
    mgr.check_position("P1", 105.0)
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
