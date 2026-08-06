"""Regression tests for EntryCoordinator scale-in trigger initialization.

Covers the fix where ``scale_confirm_price`` / ``scale_breakout_price`` were
never initialized on new positions, so ``ScaleManager.check_scale_in`` could
never fire and positions stayed at the initial 40% deployment forever.

``_init_scale_prices`` is a staticmethod — tested directly without wiring the
whole coordinator.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.application.services.entry_coordinator import EntryCoordinator
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.enums import SignalType, SetupType, Source, Side
from app.domain.fabio_ai.services.scale_manager import ScaleManager


def _make_signal(is_buy=True, price=100.0, sl=95.0, tp=110.0) -> Signal:
    return Signal(
        type=SignalType.BUY if is_buy else SignalType.SELL,
        price=price,
        reason="test",
        stop_loss=sl,
        take_profit=tp,
        timestamp="2026-08-05T10:00:00Z",
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
    )


def _make_position(is_buy=True, entry=100.0, sl=95.0, tp=110.0) -> Position:
    return Position(
        symbol="CRUDEOIL 17 AUG 7200 CALL",
        side=Side.LONG if is_buy else Side.SHORT,
        source=Source.AMT,
        entry_price=Decimal(str(entry)),
        size=Decimal("4"),
        stop_loss=Decimal(str(sl)),
        take_profit=Decimal(str(tp)),
        initial_stop=Decimal(str(sl)),
        entry_time="2026-08-05T10:00:00Z",
    )


def test_init_scale_prices_long():
    """LONG: confirm at 50% of the reward distance, breakout at 80%."""
    sig = _make_signal(is_buy=True, price=100, sl=95, tp=110)
    pos = _make_position(is_buy=True, entry=100, sl=95, tp=110)
    EntryCoordinator._init_scale_prices(pos, sig)
    assert pos.scale_confirm_price == Decimal("105")
    assert pos.scale_breakout_price == Decimal("108")


def test_init_scale_prices_short():
    """SHORT: confirm/breakout mirror below entry (reward = entry - tp)."""
    sig = _make_signal(is_buy=False, price=100, sl=105, tp=90)
    pos = _make_position(is_buy=False, entry=100, sl=105, tp=90)
    EntryCoordinator._init_scale_prices(pos, sig)
    assert pos.scale_confirm_price == Decimal("95")
    assert pos.scale_breakout_price == Decimal("92")


def test_init_scale_prices_guard_zero_sl():
    """No stop-loss -> no scale plan (triggers stay 0 so check_scale_in no-ops)."""
    sig = _make_signal(price=100, sl=0, tp=110)
    pos = _make_position(entry=100, sl=0, tp=110)
    EntryCoordinator._init_scale_prices(pos, sig)
    assert pos.scale_confirm_price == Decimal("0")
    assert pos.scale_breakout_price == Decimal("0")


def test_init_scale_prices_guard_invalid_reward():
    """TP not in the trade's direction -> no scale plan."""
    sig = _make_signal(is_buy=True, price=100, sl=95, tp=90)  # TP below entry
    pos = _make_position(is_buy=True, entry=100, sl=95, tp=90)
    EntryCoordinator._init_scale_prices(pos, sig)
    assert pos.scale_confirm_price == Decimal("0")
    assert pos.scale_breakout_price == Decimal("0")


def test_scale_in_fires_after_init():
    """End-to-end regression: once prices are initialized, ScaleManager advances
    step 2 at the confirm price and step 3 at the breakout price, each adding
    30%.  Before the fix these never fired."""
    sig = _make_signal(is_buy=True, price=100, sl=95, tp=110)
    pos = _make_position(is_buy=True, entry=100, sl=95, tp=110)
    EntryCoordinator._init_scale_prices(pos, sig)
    sm = ScaleManager()

    # Below confirm: no add
    assert sm.check_scale_in(pos, 104.0) == 0.0
    # At confirm (105): step 2 fires
    assert sm.check_scale_in(pos, 105.0) == pytest.approx(0.3)
    # At breakout (108): step 3 fires
    assert sm.check_scale_in(pos, 108.0) == pytest.approx(0.3)
    # Fully scaled in: no more adds
    assert sm.check_scale_in(pos, 110.0) == 0.0
    assert pos.scale_step == 3
