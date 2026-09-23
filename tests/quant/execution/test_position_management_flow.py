# tests/quant/execution/test_position_management_flow.py
"""Tests for 7-Level Deterministic Exit Priority and Position Management Flow (Task 7)."""

import uuid
from quant.execution.exits import ExitEngine


class DummySignal:
    entry = 100.0
    sl = 95.0
    tp = 110.0


class DummyOrder:
    signal = DummySignal()


class DummyPosition:
    order = DummyOrder()
    size = 1.0
    current_stop = 95.0
    unrealized_r = 0.0
    open_price = 100.0
    # ExitEngine keys trail/BE state by position._id (stable UUID), not id().
    _id = str(uuid.uuid4())


def test_spread_emergency_precedes_all_other_exits():
    engine = ExitEngine(spread_max_pct=0.02)
    pos = DummyPosition()
    dec = engine.evaluate(
        pos,
        amt_dto={},
        bar_index=1,
        bar_high=115.0,  # TP reached
        bar_low=90.0,    # SL reached
        best_bid=98.0,
        best_ask=102.0,  # spread 4% > 2% limit
        bar_close=100.0,
    )
    assert dec.should_exit is True
    assert dec.reason == "SPREAD_BLOWOUT"


def test_hard_stop_precedes_take_profit_and_trailing():
    engine = ExitEngine(spread_max_pct=0.05)
    pos = DummyPosition()
    dec = engine.evaluate(
        pos,
        amt_dto={},
        bar_index=1,
        bar_high=102.0,
        bar_low=94.0,   # SL hit (sl=95)
        best_bid=99.9,
        best_ask=100.1,
        bar_close=94.5,
    )
    assert dec.should_exit is True
    assert dec.reason == "SL"


def test_invalidation_cvd_kill_exits_before_normal_trail():
    engine = ExitEngine(cvd_kill_threshold=1.5)
    pos = DummyPosition()
    dec = engine.evaluate(
        pos,
        amt_dto={"cvdSlope": -2.0},  # Aggressive sell CVD conflicts with LONG
        bar_index=1,
        bar_high=102.0,
        bar_low=98.0,
        best_bid=100.0,
        best_ask=100.1,
        bar_close=101.0,
    )
    assert dec.should_exit is True
    assert dec.reason == "CVD_KILL"


def test_breakeven_arms_at_point_eight_r():
    engine = ExitEngine()
    pos = DummyPosition()
    # At 104.0 (+0.8R of 5.0 risk), breakeven arms
    dec = engine.evaluate(
        pos,
        amt_dto={},
        bar_index=1,
        bar_high=104.0,
        bar_low=102.0,
        best_bid=103.9,
        best_ask=104.1,
        bar_close=104.0,
    )
    assert dec.should_exit is False
    assert engine._breakeven.get(pos._id) == 100.0


def test_trailing_stop_ratchets_above_one_r():
    engine = ExitEngine(trail_giveback_pct=0.30)
    pos = DummyPosition()
    # At 106.0 (+1.2R), trailing arms with stop at 106 - 0.3*(6) = 104.2.
    # Bar low is 105.0 > 104.2, so position survives and stop is ratcheted.
    dec = engine.evaluate(
        pos,
        amt_dto={},
        bar_index=1,
        bar_high=106.0,
        bar_low=105.0,
        best_bid=105.9,
        best_ask=106.1,
        bar_close=106.0,
    )
    assert dec.should_exit is False
    tr = engine._trail.get(pos._id)
    assert tr is not None
    assert tr.active is True
    assert tr.stop >= 104.0


def test_trailing_stop_triggers_when_low_drops_below_trail():
    engine = ExitEngine(trail_giveback_pct=0.30)
    pos = DummyPosition()
    # Bar 1: arm trail at 104.2
    engine.evaluate(
        pos,
        amt_dto={},
        bar_index=1,
        bar_high=106.0,
        bar_low=105.0,
        best_bid=105.9,
        best_ask=106.1,
        bar_close=106.0,
    )
    # Bar 2: price pulls back to 103.5 (below 104.2)
    dec = engine.evaluate(
        pos,
        amt_dto={},
        bar_index=2,
        bar_high=105.0,
        bar_low=103.5,
        best_bid=103.4,
        best_ask=103.6,
        bar_close=103.8,
    )
    assert dec.should_exit is True
    assert dec.reason == "TRAIL"
