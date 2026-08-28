"""Regression tests for DhanBrokerAdapter order lifecycle metadata.

Covers fixes from the entry/exit execution-flow audit:
- Live positions must carry ``initial_stop`` (the original stop).  Without it
  the exit engine treats risk as 0 and every R-multiple / ATR-VWAP trail /
  partition exit silently no-ops on live positions.
- 40/30/30 scale-in entries deploy only 40% of target; the adapter must record
  ``full_size`` and ``deployed_fraction`` so ``Portfolio.add_to_position`` can
  size the 30% confirm/breakout adds.

All tests mock DhanBroker so no live credentials or network are needed.
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Ensure project root is on path so `brokers.broker...` resolves.
# (dhan_broker_adapter also inserts it at import time.)
_project_root = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
from quant.contracts.entities import Signal
from quant.contracts.enums import SignalType, SetupType, Source
from quant.contracts.aggregates import Portfolio
from brokers.broker.dhan.domain.errors import DhanError
from brokers.broker.types import OrderStatus, OrderType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(mock_broker: MagicMock) -> DhanBrokerAdapter:
    """Build an adapter without its real __init__ (avoids DhanBroker.create
    and the client-id requirement); only the fields execute_order touches."""
    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    adapter._broker = mock_broker
    adapter._order_poll_interval = 0.01
    adapter._order_poll_timeout = 2.0
    adapter._config = None
    adapter._executing_signal_ids = set()
    adapter._executing_lock = threading.Lock()
    return adapter


def _make_signal(
    price=100.0, sl=95.0, tp=110.0, is_buy=True, metadata=None
) -> Signal:
    return Signal(
        type=SignalType.BUY if is_buy else SignalType.SELL,
        price=price,
        reason="test",
        stop_loss=sl,
        take_profit=tp,
        timestamp="2026-08-05T10:00:00Z",
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
        metadata=metadata,
    )


def _mock_broker_filled(quantity=4, fill_price=100.0) -> MagicMock:
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


def _status(**overrides) -> SimpleNamespace:
    """A broker get_order_status payload with sensible defaults."""
    base = dict(
        status=OrderStatus.OPEN,
        quantity=4,
        filled_quantity=2,
        average_fill_price=100.0,
        instrument=SimpleNamespace(symbol="CRUDEOIL 17 AUG 7200 CALL"),
        timestamp=datetime.now().isoformat(),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_signal_once(metadata=None):
    """Create a signal and capture its signal_id (used for duplicate tests)."""
    signal = _make_signal(metadata=metadata)
    return signal, signal.signal_id


# ---------------------------------------------------------------------------
# initial_stop
# ---------------------------------------------------------------------------


def test_execute_order_sets_initial_stop():
    """Regression: live positions must carry initial_stop == signal.stop_loss.

    Before the fix the adapter built Position without initial_stop, so the
    exit engine computed risk = 0 and every R-multiple / ATR-VWAP trail /
    partition exit silently no-oped on live positions.
    """
    broker = _mock_broker_filled()
    adapter = _make_adapter(broker)
    signal = _make_signal(
        price=100.0,
        sl=95.0,
        tp=110.0,
        metadata={"order_quantity": 4, "option_type": "CE"},
    )
    portfolio = Portfolio.create_default()

    pos = adapter.execute_order(signal, portfolio, "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is not None
    assert float(pos.initial_stop) == pytest.approx(95.0)
    assert float(pos.stop_loss) == pytest.approx(95.0)


def test_execute_order_sets_initial_stop_for_short():
    """initial_stop must be set for SHORT positions too."""
    broker = _mock_broker_filled()
    adapter = _make_adapter(broker)
    signal = _make_signal(
        price=100.0,
        sl=105.0,
        tp=90.0,
        is_buy=False,
        metadata={"order_quantity": 4, "option_type": "PE"},
    )
    portfolio = Portfolio.create_default()

    pos = adapter.execute_order(signal, portfolio, "CRUDEOIL 17 AUG 7200 PUT")

    assert pos is not None
    assert float(pos.initial_stop) == pytest.approx(105.0)


# ---------------------------------------------------------------------------
# Duplicate-order protection + broker-callback idempotency
# ---------------------------------------------------------------------------


def test_duplicate_signal_skipped_second_execution():
    """Calling execute_order twice with the SAME signal must place exactly one
    broker order — the second call is refused by the adapter's dedup guard."""
    broker = _mock_broker_filled()
    adapter = _make_adapter(broker)
    signal, signal_id = _make_signal_once(metadata={"order_quantity": 4})
    portfolio = Portfolio.create_default()
    symbol = "CRUDEOIL 17 AUG 7200 CALL"

    pos1 = adapter.execute_order(signal, portfolio, symbol)
    pos2 = adapter.execute_order(signal, portfolio, symbol)

    assert pos1 is not None
    assert pos2 is None, "duplicate signal must not open a second position"
    assert broker.place_order.call_count == 1
    assert signal_id


def test_order_carries_signal_id_for_broker_dedup():
    """The order handed to place_order must carry user_order_id == signal_id,
    which DhanConverter sends as correlationId for broker-side idempotency."""
    broker = _mock_broker_filled()
    adapter = _make_adapter(broker)
    signal, signal_id = _make_signal_once(metadata={"order_quantity": 4})

    adapter.execute_order(signal, Portfolio.create_default(),
                         "CRUDEOIL 17 AUG 7200 CALL")

    order = broker.place_order.call_args[0][0]
    assert getattr(order, "user_order_id", None) == signal_id


# ---------------------------------------------------------------------------
# C7: entry slippage collar (marketable LIMIT instead of naked MARKET)
# ---------------------------------------------------------------------------


def test_entry_buy_uses_marketable_limit_with_collar():
    """C7: a default BUY entry becomes a marketable LIMIT bounded by the
    slippage tolerance — never a naked MARKET order."""
    from brokers.broker.types import OrderType

    broker = _mock_broker_filled()
    adapter = _make_adapter(broker)
    adapter._entry_slippage_tol = 0.01
    signal = _make_signal(price=100.0, is_buy=True, metadata={"order_quantity": 4})

    adapter.execute_order(signal, Portfolio.create_default(), "CRUDEOIL 17 AUG 7200 CALL")

    order = broker.place_order.call_args[0][0]
    assert order.order_type == OrderType.LIMIT
    assert order.price == pytest.approx(101.0)  # 100 * (1 + 0.01)
    assert order.trigger_price == pytest.approx(0.0)


def test_entry_sell_uses_marketable_limit_with_collar():
    """C7: a default SELL entry's collar sits below the signal price."""
    from brokers.broker.types import OrderType

    broker = _mock_broker_filled()
    adapter = _make_adapter(broker)
    adapter._entry_slippage_tol = 0.01
    signal = _make_signal(price=100.0, is_buy=False, metadata={"order_quantity": 4})

    adapter.execute_order(signal, Portfolio.create_default(), "CRUDEOIL 17 AUG 7200 CALL")

    order = broker.place_order.call_args[0][0]
    assert order.order_type == OrderType.LIMIT
    assert order.price == pytest.approx(99.0)  # 100 * (1 - 0.01)


def test_entry_explicit_market_order_type_honored():
    """An explicitly requested MARKET order opts out of the collar."""
    from brokers.broker.types import OrderType

    broker = _mock_broker_filled()
    adapter = _make_adapter(broker)
    adapter._entry_slippage_tol = 0.01
    signal = _make_signal(price=100.0, is_buy=True,
                          metadata={"order_quantity": 4, "order_type": "MARKET"})

    adapter.execute_order(signal, Portfolio.create_default(), "CRUDEOIL 17 AUG 7200 CALL")

    order = broker.place_order.call_args[0][0]
    assert order.order_type == OrderType.MARKET


def test_marketable_limit_price_helper():
    f = DhanBrokerAdapter._marketable_limit_price
    assert f(100.0, True, 0.01) == pytest.approx(101.0)
    assert f(100.0, False, 0.01) == pytest.approx(99.0)
    assert f(100.0, True, 0.0) == pytest.approx(100.0)   # no tolerance -> unchanged
    assert f(0.0, True, 0.01) == pytest.approx(0.0)      # invalid price -> unchanged


# ---------------------------------------------------------------------------
# C4: durable order state persistence
# ---------------------------------------------------------------------------


class _RecordingStorage:
    def __init__(self):
        self.saved = {}
        self.updates = []

    def save_order(self, order):
        self.saved[order["order_id"]] = dict(order)

    def update_order_status(self, order_id, status, **kw):
        self.updates.append((order_id, status, kw))


def test_execute_order_persists_submitted_then_filled():
    """C4: with storage wired, execute_order persists SUBMITTED then FILLED."""
    broker = _mock_broker_filled(quantity=4, fill_price=100.0)
    adapter = _make_adapter(broker)
    storage = _RecordingStorage()
    adapter._storage = storage
    signal = _make_signal(price=100.0, metadata={"order_quantity": 4})

    pos = adapter.execute_order(signal, Portfolio.create_default(), "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is not None
    order_id = signal.signal_id
    assert order_id in storage.saved
    assert storage.saved[order_id]["status"] == "SUBMITTED"
    statuses = [s for (_, s, _) in storage.updates]
    assert "FILLED" in statuses
    filled_kw = [kw for (_, s, kw) in storage.updates if s == "FILLED"][0]
    assert filled_kw["filled_quantity"] == pytest.approx(4.0)
    assert filled_kw["broker_order_id"] == "ORD-1"


def test_execute_order_persists_rejected_on_broker_rejection():
    """C4: a broker-rejected order persists a REJECTED terminal state."""
    broker = _mock_broker_filled(quantity=4)
    broker.get_order_status.return_value = _status(status=OrderStatus.REJECTED, filled_quantity=0)
    adapter = _make_adapter(broker)
    storage = _RecordingStorage()
    adapter._storage = storage
    signal = _make_signal(price=100.0, metadata={"order_quantity": 4})

    pos = adapter.execute_order(signal, Portfolio.create_default(), "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is None
    statuses = [s for (_, s, _) in storage.updates]
    assert "REJECTED" in statuses


def test_execute_order_no_storage_is_noop():
    """C4: without storage wired, persistence is a safe no-op (still executes)."""
    broker = _mock_broker_filled(quantity=4)
    adapter = _make_adapter(broker)  # no _storage attribute set
    signal = _make_signal(price=100.0, metadata={"order_quantity": 4})

    pos = adapter.execute_order(signal, Portfolio.create_default(), "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is not None


# ---------------------------------------------------------------------------
# C7 (close side): close slippage collar
# ---------------------------------------------------------------------------


def test_close_long_with_reference_price_uses_marketable_limit_sell():
    """C7: closing a LONG (SELL) with a reference price -> LIMIT priced low."""
    broker = _mock_broker_filled(quantity=4, fill_price=99.0)
    adapter = _make_adapter(broker)
    adapter._close_slippage_tol = 0.05

    pos = adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL", "SELL", 4,
        Portfolio.create_default(), reference_price=100.0,
    )

    assert pos is not None
    order = broker.place_order.call_args[0][0]
    assert order.order_type == OrderType.LIMIT
    assert order.price == pytest.approx(95.0)  # 100 * (1 - 0.05): aggressive SELL


def test_close_short_with_reference_price_uses_marketable_limit_buy():
    """C7: closing a SHORT (BUY) with a reference price -> LIMIT priced high."""
    broker = _mock_broker_filled(quantity=4, fill_price=101.0)
    adapter = _make_adapter(broker)
    adapter._close_slippage_tol = 0.05

    pos = adapter.close_position(
        "CRUDEOIL 17 AUG 7200 PUT", "BUY", 4,
        Portfolio.create_default(), reference_price=100.0,
    )

    assert pos is not None
    order = broker.place_order.call_args[0][0]
    assert order.order_type == OrderType.LIMIT
    assert order.price == pytest.approx(105.0)  # 100 * (1 + 0.05): aggressive BUY


def test_close_without_reference_price_stays_market():
    """C7: no reference price -> unchanged MARKET close (fill guarantee)."""
    broker = _mock_broker_filled(quantity=4, fill_price=100.0)
    adapter = _make_adapter(broker)
    adapter._close_slippage_tol = 0.05

    pos = adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL", "SELL", 4, Portfolio.create_default()
    )

    assert pos is not None
    order = broker.place_order.call_args[0][0]
    assert order.order_type == OrderType.MARKET


def test_close_collar_disabled_when_tolerance_zero():
    """C7: tolerance 0 disables the collar -> MARKET close."""
    broker = _mock_broker_filled(quantity=4, fill_price=100.0)
    adapter = _make_adapter(broker)
    adapter._close_slippage_tol = 0.0

    pos = adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL", "SELL", 4,
        Portfolio.create_default(), reference_price=100.0,
    )

    assert pos is not None
    order = broker.place_order.call_args[0][0]
    assert order.order_type == OrderType.MARKET


def test_close_unset_tolerance_attribute_defaults_to_market():
    """C7: adapter built without __init__ (no _close_slippage_tol) -> MARKET."""
    broker = _mock_broker_filled(quantity=4, fill_price=100.0)
    adapter = _make_adapter(broker)  # no _close_slippage_tol attribute

    pos = adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL", "SELL", 4,
        Portfolio.create_default(), reference_price=100.0,
    )

    assert pos is not None
    order = broker.place_order.call_args[0][0]
    assert order.order_type == OrderType.MARKET


def test_partial_fill_completes_within_poll_returns_position():
    """A partially filled order that reaches FILLED within the poll window is
    accepted with the filled quantity."""
    broker = _mock_broker_filled(quantity=4)
    broker.get_order_status.side_effect = [
        _status(status=OrderStatus.OPEN, filled_quantity=2),   # partial
        _status(status=OrderStatus.FILLED, filled_quantity=4),
    ]
    adapter = _make_adapter(broker)
    signal, _ = _make_signal_once(metadata={"order_quantity": 4})

    pos = adapter.execute_order(signal, Portfolio.create_default(),
                                "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is not None
    assert float(pos.size) == 4.0
    assert broker.cancel_order.call_count == 0


def test_partial_fill_times_out_and_cancels_remainder():
    """A partial fill that never completes within the poll timeout is
    cancelled and yields no position — never a phantom open position."""
    broker = _mock_broker_filled(quantity=4)
    broker.get_order_status.return_value = _status(
        status=OrderStatus.OPEN, filled_quantity=2
    )
    adapter = _make_adapter(broker)
    adapter._order_poll_timeout = 0.05  # fast timeout for the test
    signal, _ = _make_signal_once(metadata={"order_quantity": 4})

    pos = adapter.execute_order(signal, Portfolio.create_default(),
                                "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is None
    broker.cancel_order.assert_called_once_with("ORD-1")


def test_rejected_order_returns_none():
    """A broker rejection must not open a position and must not be cancelled."""
    broker = _mock_broker_filled(quantity=4)
    broker.get_order_status.return_value = _status(
        status=OrderStatus.REJECTED, filled_quantity=0
    )
    adapter = _make_adapter(broker)
    signal, _ = _make_signal_once(metadata={"order_quantity": 4})

    pos = adapter.execute_order(signal, Portfolio.create_default(),
                                "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is None
    assert broker.cancel_order.call_count == 0


def test_cancelled_order_returns_none():
    """A broker-cancelled order yields no position and no extra cancel."""
    broker = _mock_broker_filled(quantity=4)
    broker.get_order_status.return_value = _status(
        status=OrderStatus.CANCELLED, filled_quantity=0
    )
    adapter = _make_adapter(broker)
    signal, _ = _make_signal_once(metadata={"order_quantity": 4})

    pos = adapter.execute_order(signal, Portfolio.create_default(),
                                "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is None
    assert broker.cancel_order.call_count == 0


def test_place_order_network_error_returns_none():
    """A network failure during place_order must yield None (the HTTP layer
    retries internally; the adapter never fabricates a position)."""
    broker = _mock_broker_filled(quantity=4)
    broker.place_order.side_effect = DhanError(
        message="connection reset", code="NETWORK", details={}
    )
    adapter = _make_adapter(broker)
    signal, _ = _make_signal_once(metadata={"order_quantity": 4})

    pos = adapter.execute_order(signal, Portfolio.create_default(),
                                "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is None
    assert broker.get_order_status.call_count == 0


# ---------------------------------------------------------------------------
# Scale-in metadata (40/30/30)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Exchange routing (D-EXCH-07 sibling: BSE/BFO instruments must not fall
# through the old binary MCX/NFO branch in _make_instrument).
# ---------------------------------------------------------------------------


def test_make_instrument_routes_sensex_option_to_bfo():
    """A SENSEX option must resolve to Exchange.BFO, not the old binary
    "MCX if is_mcx else NFO" default that had no BSE/BFO branch at all."""
    from brokers.broker.types import Exchange

    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    signal = _make_signal(metadata={"option_type": "CE"})

    instrument = adapter._make_instrument(signal, "SENSEX 17 AUG 82000 CALL")

    assert instrument.exchange == Exchange.BFO


def test_make_instrument_routes_bankex_option_to_bfo():
    from brokers.broker.types import Exchange

    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    signal = _make_signal(metadata={"option_type": "PE"}, is_buy=False)

    instrument = adapter._make_instrument(signal, "BANKEX 17 AUG 55000 PUT")

    assert instrument.exchange == Exchange.BFO


def test_make_instrument_routes_nifty_option_to_nfo():
    """NSE index options must still route to NFO (no regression)."""
    from brokers.broker.types import Exchange

    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    signal = _make_signal(metadata={"option_type": "CE"})

    instrument = adapter._make_instrument(signal, "NIFTY 17 AUG 24500 CALL")

    assert instrument.exchange == Exchange.NFO


def test_make_instrument_routes_crudeoil_option_to_mcx():
    """MCX commodity options must still route to MCX (no regression)."""
    from brokers.broker.types import Exchange

    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    signal = _make_signal(metadata={"option_type": "CE"})

    instrument = adapter._make_instrument(signal, "CRUDEOIL 17 AUG 7200 CALL")

    assert instrument.exchange == Exchange.MCX


def test_make_instrument_explicit_exchange_hint_wins():
    """An explicit exchange hint on signal.metadata must still override the
    auto-resolved exchange."""
    from brokers.broker.types import Exchange

    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    signal = _make_signal(metadata={"option_type": "CE", "exchange": "NFO"})

    instrument = adapter._make_instrument(signal, "SENSEX 17 AUG 82000 CALL")

    assert instrument.exchange == Exchange.NFO


def test_execute_order_scale_in_records_full_size_and_deployed_fraction():
    """Regression: a scale_in entry deploys 40% of target — the adapter must
    record full_size and deployed_fraction so add_to_position can size the
    30% confirm/breakout adds.  full_size = filled / 0.4."""
    broker = _mock_broker_filled(quantity=4, fill_price=100.0)
    adapter = _make_adapter(broker)
    signal = _make_signal(
        price=100.0,
        sl=95.0,
        tp=110.0,
        metadata={
            "order_quantity": 4,
            "scale_in": True,
            "option_type": "CE",
        },
    )
    portfolio = Portfolio.create_default()

    pos = adapter.execute_order(signal, portfolio, "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is not None
    assert float(pos.metadata["deployed_fraction"]) == pytest.approx(0.4)
    assert float(pos.metadata["full_size"]) == pytest.approx(10.0)  # 4 / 0.4


def test_execute_order_non_scale_in_has_no_deployed_metadata():
    """A full-size (non-scale-in) entry must not carry scale-in metadata, so
    add_to_position keeps its default fully-deployed behavior."""
    broker = _mock_broker_filled(quantity=4, fill_price=100.0)
    adapter = _make_adapter(broker)
    signal = _make_signal(
        price=100.0,
        sl=95.0,
        tp=110.0,
        metadata={"order_quantity": 4, "option_type": "CE"},
    )
    portfolio = Portfolio.create_default()

    pos = adapter.execute_order(signal, portfolio, "CRUDEOIL 17 AUG 7200 CALL")

    assert pos is not None
    assert "full_size" not in (pos.metadata or {})
    assert "deployed_fraction" not in (pos.metadata or {})


def test_scale_in_metadata_supports_add_to_position():
    """End-to-end sizing check: the recorded full_size + deployed_fraction let
    Portfolio.add_to_position add a 30% leg on top of the 40% initial leg."""
    broker = _mock_broker_filled(quantity=4, fill_price=100.0)
    adapter = _make_adapter(broker)
    signal = _make_signal(
        price=100.0,
        sl=95.0,
        tp=110.0,
        metadata={"order_quantity": 4, "scale_in": True, "option_type": "CE"},
    )
    portfolio = Portfolio.create_default()

    pos = adapter.execute_order(signal, portfolio, "CRUDEOIL 17 AUG 7200 CALL")
    assert pos is not None
    portfolio.positions.append(pos)  # register like the session does

    # 30% of full_size (10.0) = 3 units -> total 7 (4 initial + 3 add)
    assert portfolio.add_to_position(pos.id, 0.30, 100.0) is True
    assert float(pos.size) == pytest.approx(7.0)
    assert float(pos.metadata["deployed_fraction"]) == pytest.approx(0.7)
