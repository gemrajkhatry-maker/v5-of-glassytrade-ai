"""Chaos Fault-Injection Tests for Phase 2 Contingent Stop & Fail-Closed Storage.

Injects broker network drop/timeout/rejection simulations during Phase 2 contingent
SL-M stop placement; asserts that Emergency Flatten triggers immediately and halts trading.
Also verifies that SQLite storage corruption fails closed by raising DataIntegrityError.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
import pytest

from backend.app.infrastructure.storage.database import DataIntegrityError, SQLiteStorageAdapter
from quant.contracts.aggregates import Portfolio
from quant.contracts.entities import Position as BrokerPosition
from quant.contracts.enums import Side, Source
from quant.contracts.ports.broker import IBroker
from quant.decision.signal_builder import Signal
from quant.events import EmergencyFlatten
from quant.execution.live_oms import EmergencyFlattenError, LiveOMS


class FailingStopBroker(IBroker):
    """Broker test double that successfully enters but drops/fails on contingent stop."""

    def __init__(self, should_fail_stop: bool = True) -> None:
        self.should_fail_stop = should_fail_stop
        self.close_call_count = 0
        self.last_close_side = None
        self.last_close_qty = None

    def execute_order(self, signal, portfolio, symbol, contract_ref=None):
        return BrokerPosition(
            symbol=symbol,
            side=Side.LONG,
            source=Source.AMT,
            entry_price=Decimal("100.0"),
            size=Decimal("25"),
            stop_loss=Decimal("0"),
            take_profit=Decimal("0"),
            entry_time="2026-09-11T09:35:00",
        )

    def close_position(self, symbol, side, quantity, portfolio, reference_price=None, contract_ref=None, close_intent_id=None):
        self.close_call_count += 1
        self.last_close_side = side
        self.last_close_qty = quantity
        return BrokerPosition(
            symbol=symbol,
            side=Side.SHORT,
            source=Source.AMT,
            entry_price=Decimal("100.0"),
            size=Decimal(str(quantity)),
            stop_loss=Decimal("0"),
            take_profit=Decimal("0"),
            entry_time="2026-09-11T09:35:00",
        )

    def place_stop_loss(self, symbol, side, quantity, stop_price, contract_ref=None):
        if self.should_fail_stop:
            raise ConnectionResetError("Broker connection reset during Phase 2 SL-M dispatch")
        return "SL_1001"

    def cancel_order(self, order_id: str) -> bool:
        return True


def test_contingent_stop_broker_drop_triggers_panic_flatten():
    """When Phase 2 stop placement encounters network drop, LiveOMS triggers reverse market order."""
    broker = FailingStopBroker(should_fail_stop=True)
    events_emitted = []

    def mock_emit(event):
        events_emitted.append(event)

    portfolio = MagicMock(spec=Portfolio)
    oms = LiveOMS(broker=broker, portfolio=portfolio, lot_size=25)
    oms.set_emit_fn(mock_emit)

    signal = Signal(
        type="LONG",
        reason="test",
        entry=100.0,
        sl=90.0,
        tp=120.0,
        rr=2.0,
        model_label="Triple-A",
        symbol="NIFTY24AUG25000CE",
        timestamp="2026-09-11T09:35:00",
    )

    with pytest.raises(EmergencyFlattenError) as exc_info:
        oms.submit(signal=signal, quantity=25)

    assert "Emergency Flatten Guard" in str(exc_info.value)

    # Assert reverse market order was submitted to flatten position
    assert broker.close_call_count == 1
    assert broker.last_close_side == "SELL"
    assert broker.last_close_qty == 25

    # Assert EmergencyFlatten event was emitted
    flatten_events = [e for e in events_emitted if isinstance(e, EmergencyFlatten)]
    assert len(flatten_events) == 1
    assert flatten_events[0].symbol == "NIFTY24AUG25000CE"
    assert flatten_events[0].quantity == 25
    assert flatten_events[0].side == "SELL"


def test_storage_corruption_raises_data_integrity_error():
    """Fail-closed persistence protocol: corrupted DB or lock failure raises DataIntegrityError."""
    adapter = SQLiteStorageAdapter(db_path=":memory:")
    # Simulate low-level SQLite failure
    adapter._conn.close()

    with pytest.raises(DataIntegrityError):
        adapter.kv_get("test_key")

    with pytest.raises(DataIntegrityError):
        adapter.kv_set("test_key", "{\"corrupted\": true}")
