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
from brokers.broker.types import OrderStatus


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
# Scale-in metadata (40/30/30)
# ---------------------------------------------------------------------------


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
