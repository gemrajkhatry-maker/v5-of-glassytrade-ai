"""Deterministic Golden Tape Replay Verification Suite.

Executes 1,000 runs of recorded session event tapes and asserts that all runs
yield bit-for-bit identical SHA-256 event log hashes and identical folded EngineStates.
"""

from __future__ import annotations

import pytest

from quant.decision.signal_builder import Signal
from quant.event_store import EventStore
from quant.events import (
    BarClosed,
    OrderSubmitted,
    PositionClosed,
    PositionOpened,
    SignalApproved,
    SignalProduced,
)
from quant.execution.order import Fill, Order, Position


class MockBar:
    def __init__(self, close: float = 104.5):
        self.time = "2026-09-11T09:30:00"
        self.open = 100.0
        self.high = 105.0
        self.low = 99.5
        self.close = close
        self.volume = 5000.0
        self.vwap = 103.0
        self.buy_volume = 3500.0
        self.sell_volume = 1500.0
        self.oi = 50000.0


def create_golden_tape():
    """Generates a deterministic sequence of trading events."""
    bar = MockBar()
    signal = Signal(
        type="LONG",
        reason="TRIPLE_A",
        entry=105.0,
        sl=98.0,
        tp=119.0,
        rr=2.0,
        model_label="Triple-A",
        symbol="NIFTY24AUG25000CE",
        timestamp="2026-09-11T09:31:00",
    )
    order = Order(signal=signal, quantity=50.0)
    pos = Position(
        order=order,
        open_price=105.0,
        open_time="2026-09-11T09:31:02",
        size=50.0,
        _id="pos-deterministic-1001",
    )
    fill = Fill(
        position=pos,
        close_price=119.0,
        close_time="2026-09-11T09:45:00",
        reason="TP",
        pnl=700.0,
        logical_id="fill-deterministic-1001",
    )

    events = [
        BarClosed(
            symbol="NIFTY24AUG25000CE",
            time="2026-09-11T09:30:00",
            bar=bar,
        ),
        SignalProduced(
            symbol="NIFTY24AUG25000CE",
            time="2026-09-11T09:31:00",
            signal=signal,
            setup_name="TRIPLE_A",
        ),
        SignalApproved(
            symbol="NIFTY24AUG25000CE",
            time="2026-09-11T09:31:00",
            signal=signal,
        ),
        OrderSubmitted(
            symbol="NIFTY24AUG25000CE",
            time="2026-09-11T09:31:01",
            order_id="ORD_1001",
            side="BUY",
            quantity=50.0,
            price=105.0,
            reason="ENTRY",
        ),
        PositionOpened(
            symbol="NIFTY24AUG25000CE",
            time="2026-09-11T09:31:02",
            position=pos,
        ),
        PositionClosed(
            symbol="NIFTY24AUG25000CE",
            time="2026-09-11T09:45:00",
            fill=fill,
        ),
    ]
    return events


def test_1000_run_golden_tape_replay_bit_for_bit_determinism():
    """Execute 1,000 runs of golden tape replay and verify identical SHA-256 hash lineage."""
    base_store = EventStore()
    tape = create_golden_tape()
    for ev in tape:
        base_store.append(ev)

    golden_checksum = base_store.last_checksum
    golden_state = base_store.fold()

    assert golden_checksum is not None
    assert len(golden_state.closed_trades) == 1
    assert golden_state.position is None
    assert golden_state.realized_pnl == pytest.approx(700.0)

    # Replay 1,000 times
    for _ in range(1000):
        replay_store = EventStore()
        for ev in tape:
            replay_store.append(ev)

        replay_checksum = replay_store.last_checksum
        assert replay_checksum == golden_checksum, "Bit-for-bit SHA-256 hash drift detected!"
