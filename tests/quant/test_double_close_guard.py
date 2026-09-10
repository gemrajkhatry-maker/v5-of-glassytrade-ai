"""Regression test for the double-close bug.

Bug: A single position was being closed multiple times (38+ closes for 1 open),
causing P&L to be overstated by 10-100x.

Root cause: _execute_full_close had no guard against double-close. Each close
emitted PositionClosed and booked P&L.

Fix: Added _closed_ids set to PositionManager to track already-closed positions.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from quant.execution.order import Position, Order
from quant.execution.oms import PaperOMS
from quant.execution.exits import ExitDecision, ExitEngine
from quant.execution.risk import SessionRisk
from quant.events import PositionClosed
from quant.decision.signal_builder import Signal


def _make_position(size=100):
    sig = Signal(
        type="LONG", reason="test", entry=100.0, sl=95.0, tp=110.0,
        rr=2.0, model_label="Test", symbol="TEST", timestamp="t0",
    )
    return Position(
        order=Order(signal=sig, quantity=size),
        open_price=100.0,
        open_time="t0",
        size=size,
    )


def test_double_close_guard():
    """Closing the same position twice must not emit two PositionClosed events."""
    from quant.position_manager import PositionManager

    emitted = []
    def emit_fn(event):
        emitted.append(event)

    pm = PositionManager(
        oms=PaperOMS(lot_size=1.0),
        exits=ExitEngine(time_stop_bars=30),
        risk=SessionRisk(storage=None, symbol="TEST"),
        emit_fn=emit_fn,
        symbol="TEST",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
    )

    pos = _make_position()

    # First close should succeed and return the closing Fill (money-path
    # consumers key the risk release off it; None means "guarded skip").
    result1 = pm._execute_full_close(pos, ExitDecision(True, "SL", 90.0), "t1")
    assert result1 is not None and result1.reason == "SL"
    assert len([e for e in emitted if isinstance(e, PositionClosed)]) == 1

    # Second close must be skipped (double-close guard)
    result2 = pm._execute_full_close(pos, ExitDecision(True, "SL", 90.0), "t2")
    assert result2 is None
    assert len([e for e in emitted if isinstance(e, PositionClosed)]) == 1, (
        "Double-close guard failed: position was closed twice"
    )


def test_different_positions_can_close():
    """Different positions must be allowed to close."""
    from quant.position_manager import PositionManager

    emitted = []
    def emit_fn(event):
        emitted.append(event)

    pm = PositionManager(
        oms=PaperOMS(lot_size=1.0),
        exits=ExitEngine(time_stop_bars=30),
        risk=SessionRisk(storage=None, symbol="TEST"),
        emit_fn=emit_fn,
        symbol="TEST",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
    )

    pos1 = _make_position(size=100)
    pos2 = _make_position(size=50)

    pm._execute_full_close(pos1, ExitDecision(True, "SL", 90.0), "t1")
    pm._execute_full_close(pos2, ExitDecision(True, "TP", 110.0), "t2")

    closed = [e for e in emitted if isinstance(e, PositionClosed)]
    assert len(closed) == 2, f"Expected 2 closes, got {len(closed)}"


if __name__ == "__main__":
    test_double_close_guard()
    test_different_positions_can_close()
    print("All double-close tests passed!")
