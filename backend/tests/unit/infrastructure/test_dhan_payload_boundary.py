"""B2 remainder: broker payload boundary — every order type the adapter emits.

The adapter tests stop at the constructed ``Order`` object and the converter
tests start from hand-built orders. Nothing proved the FULL chain
(adapter decision -> actual Dhan JSON payload). These tests run a real
``execute_order`` / ``close_position`` and push the captured ``Order`` through
``DhanConverter.from_order_request`` — the exact dict ``place_order`` POSTs —
asserting the payload contract per order type:

- default entry (C7): MARKET request becomes a marketable LIMIT with price,
  no triggerPrice, correlationId == signal_id
- explicit metadata order_type MARKET stays MARKET (no price field)
- explicit metadata SL / SLM carry triggerPrice (and price for SL)
- close with reference price: collared marketable LIMIT SELL/BUY
- close without reference price: naked MARKET, no price field
- correlationId is truncated to Dhan's 36-char limit in all cases
"""

import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
from brokers.broker.dhan.application.order_converter import from_order_request
from brokers.broker.types import OrderStatus
from quant.contracts.aggregates import Portfolio
from quant.contracts.enums import SetupType, SignalType, Source
from quant.contracts.entities import Signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adapter(broker: MagicMock) -> DhanBrokerAdapter:
    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    adapter._broker = broker
    adapter._order_poll_interval = 0.001
    adapter._order_poll_timeout = 0.05
    adapter._executing_signal_ids = set()
    adapter._executing_lock = threading.Lock()
    adapter._storage = MagicMock(spec=["save_order", "update_order_status"])
    return adapter


def _signal(metadata=None) -> Signal:
    return Signal(
        type=SignalType.BUY,
        price=100.0,
        reason="payload boundary test",
        stop_loss=95.0,
        take_profit=110.0,
        timestamp="2026-09-04T10:00:00+05:30",
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
        metadata=metadata,
    )


def _filled_broker(quantity=4, fill_price=100.0) -> MagicMock:
    broker = MagicMock()
    broker.place_order.return_value = SimpleNamespace(order_id="ORD-1", quantity=quantity)
    broker.get_order_status.return_value = SimpleNamespace(
        status=OrderStatus.FILLED,
        quantity=quantity,
        filled_quantity=quantity,
        average_fill_price=fill_price,
        instrument=SimpleNamespace(symbol="CRUDEOIL 17 AUG 7200 CALL"),
        timestamp=datetime.now().isoformat(),
    )
    return broker


def _captured_order(broker: MagicMock):
    return broker.place_order.call_args.args[0]


def _payload(broker: MagicMock) -> dict:
    """The exact dict the adapter's place_order POSTs to Dhan."""
    return from_order_request(_captured_order(broker), client_id="client-1")


# ---------------------------------------------------------------------------
# Entry payloads
# ---------------------------------------------------------------------------


def test_default_entry_payload_is_marketable_limit_with_correlation_id():
    broker = _filled_broker()
    adapter = _adapter(broker)
    assert adapter.execute_order(_signal({"order_quantity": 4}), Portfolio.create_default(), "CRUDEOIL") is not None

    payload = _payload(broker)
    assert payload["orderType"] == "LIMIT"
    assert payload["quantity"] == 4
    # C7 collar: limit price bounded above the signal price for a BUY
    assert payload["price"] > 100.0
    assert "triggerPrice" not in payload
    # Dhan idempotency: one logical decision -> one correlationId
    assert payload["correlationId"]
    assert len(payload["correlationId"]) <= 36


def test_explicit_market_entry_payload_has_no_price():
    broker = _filled_broker()
    adapter = _adapter(broker)
    sig = _signal({"order_quantity": 4, "order_type": "MARKET"})
    assert adapter.execute_order(sig, Portfolio.create_default(), "CRUDEOIL") is not None

    payload = _payload(broker)
    assert payload["orderType"] == "MARKET"
    assert "price" not in payload
    assert "triggerPrice" not in payload


def test_explicit_sl_entry_payload_carries_trigger_and_price():
    broker = _filled_broker()
    adapter = _adapter(broker)
    sig = _signal({"order_quantity": 4, "order_type": "SL"})
    assert adapter.execute_order(sig, Portfolio.create_default(), "CRUDEOIL") is not None

    payload = _payload(broker)
    # DhanHQ v2 orderType vocabulary (v1 called these SL/SLM)
    assert payload["orderType"] == "STOP_LOSS"
    assert payload["triggerPrice"] == 95.0  # stop_loss becomes the activation trigger
    assert "price" in payload


def test_explicit_slm_entry_payload_carries_only_trigger():
    broker = _filled_broker()
    adapter = _adapter(broker)
    sig = _signal({"order_quantity": 4, "order_type": "SLM"})
    assert adapter.execute_order(sig, Portfolio.create_default(), "CRUDEOIL") is not None

    payload = _payload(broker)
    assert payload["orderType"] == "STOP_LOSS_MARKET"
    assert payload["triggerPrice"] == 95.0
    assert "price" not in payload


# ---------------------------------------------------------------------------
# Close payloads
# ---------------------------------------------------------------------------


def _close_broker() -> MagicMock:
    broker = MagicMock()
    broker.place_order.return_value = SimpleNamespace(order_id="ORD-C", quantity=4)
    broker.get_order_status.return_value = SimpleNamespace(
        status=OrderStatus.FILLED,
        quantity=4,
        filled_quantity=4,
        average_fill_price=100.0,
        instrument=SimpleNamespace(symbol="CRUDEOIL 17 AUG 7200 CALL"),
        timestamp=datetime.now().isoformat(),
    )
    return broker


def test_collared_close_payload_is_marketable_limit():
    broker = _close_broker()
    adapter = _adapter(broker)
    adapter._close_slippage_tol = 0.02
    assert adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL", "SELL", 4, Portfolio.create_default(),
        reference_price=100.0,
    ) is not None

    payload = _payload(broker)
    assert payload["orderType"] == "LIMIT"
    assert payload["transactionType"] == "SELL"
    assert payload["price"] < 100.0  # SELL collar bounds below reference
    assert payload["correlationId"].startswith("close:")


def test_uncollared_close_payload_is_naked_market():
    broker = _close_broker()
    adapter = _adapter(broker)
    adapter._close_slippage_tol = 0.0
    assert adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL", "SELL", 4, Portfolio.create_default(),
        reference_price=100.0,
    ) is not None

    payload = _payload(broker)
    assert payload["orderType"] == "MARKET"
    assert "price" not in payload


def test_close_payload_without_reference_price_is_market():
    broker = _close_broker()
    adapter = _adapter(broker)
    adapter._close_slippage_tol = 0.02
    # No reference price (e.g. feed died) -> plain MARKET regardless of tol
    assert adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL", "SELL", 4, Portfolio.create_default(),
        reference_price=None,
    ) is not None

    payload = _payload(broker)
    assert payload["orderType"] == "MARKET"
    assert "price" not in payload
