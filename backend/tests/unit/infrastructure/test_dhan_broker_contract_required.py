from __future__ import annotations

import threading
from unittest.mock import MagicMock

from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
from quant.contracts.contracts import ContractRef
from quant.contracts.aggregates import Portfolio
from quant.contracts.enums import SignalType, SetupType, Source
from quant.contracts.entities import Signal


def _signal():
    return Signal(type=SignalType.BUY, price=100.0, reason="test", stop_loss=95.0,
                  take_profit=110.0, timestamp="2026-08-05T10:00:00Z",
                  setup=SetupType.MEAN_REVERSION, source=Source.AMT)


def _adapter():
    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    adapter._broker = MagicMock()
    adapter._executing_signal_ids = set()
    adapter._executing_lock = threading.Lock()
    return adapter


def test_live_adapter_rejects_missing_contract_ref_before_broker_call():
    adapter = _adapter()
    signal = _signal()
    assert adapter.execute_order(signal, Portfolio.create_default(), "CRUDEOIL") is None
    adapter._broker.place_order.assert_not_called()


def test_live_adapter_rejects_mismatched_contract_ref_before_broker_call():
    adapter = _adapter()
    signal = _signal()
    ref = ContractRef(symbol="OTHER", exchange="MCX", expiry="2026-09-30", lot_size=1, tick_size=0.05)
    assert adapter.execute_order(signal, Portfolio.create_default(), "CRUDEOIL", contract_ref=ref) is None
    adapter._broker.place_order.assert_not_called()
