from brokers.broker.types import OrderStatus
from brokers.broker.dhan.domain.order_status import (
    DHAN_ORDER_STATUS_MAP, TERMINAL_STATUSES, is_terminal, normalize_status,
)
from quant.decision.signal_builder import SignalBuilder, is_stop_too_thin, clamp_quantity

def test_status_table_values():
    assert DHAN_ORDER_STATUS_MAP["TRADED"] is OrderStatus.FILLED
    assert DHAN_ORDER_STATUS_MAP["FILLED"] is OrderStatus.FILLED
    assert DHAN_ORDER_STATUS_MAP["PART_TRADED"] is OrderStatus.OPEN
    assert DHAN_ORDER_STATUS_MAP["PARTIALLY_FILLED"] is OrderStatus.OPEN
    assert DHAN_ORDER_STATUS_MAP["TRANSIT"] is OrderStatus.PENDING
    assert DHAN_ORDER_STATUS_MAP["EXPIRED"] is OrderStatus.CANCELLED

def test_normalize_status_rules():
    assert normalize_status("traded") is OrderStatus.FILLED
    assert normalize_status("  part_traded ") is OrderStatus.OPEN
    assert normalize_status("WEIRD_NEW_CODE") is OrderStatus.PENDING
    assert normalize_status("") is OrderStatus.PENDING

def test_terminal_sets():
    assert is_terminal(OrderStatus.FILLED) is True
    assert is_terminal(OrderStatus.CANCELLED) is True
    assert is_terminal(OrderStatus.REJECTED) is True
    assert is_terminal(OrderStatus.PENDING) is False
    assert is_terminal(OrderStatus.OPEN) is False
    assert TERMINAL_STATUSES == frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED})


def _ctx_double(direction="LONG", entry=100.0):
    from types import SimpleNamespace
    bar = SimpleNamespace(close=entry, low=entry - 1.0, high=entry + 1.0)
    return SimpleNamespace(
        agent_direction=direction, bar=bar, tick_size=0.05,
        symbol="NIFTY", time_str="t",
        setup_evidence=None, poc=None, npoc_above=None, npoc_below=None,
        prior_poc=None, vah=None, val=None,
        leg_lvn=0.0, nearest_buy_print_below=0.0, nearest_sell_print_above=0.0,
    )


def _passing():
    from quant.decision.result import GateResult
    return [GateResult(gate=1, passed=True)]


def test_thin_stop_helpers():
    assert is_stop_too_thin(100.0, 99.95) is True
    assert is_stop_too_thin(100.0, 99.0) is False
    assert clamp_quantity(5000.0) == 1000.0
    assert clamp_quantity(-5.0) == 0.0
    assert clamp_quantity(5000.0, max_quantity=0) == 5000.0


def test_builder_happy_path_long():
    sig, why = SignalBuilder().build_or_reason(_ctx_double("LONG", 100.0), _passing())
    assert sig is not None and why == ""
    assert sig.type == "LONG" and sig.entry == 100.0
    assert sig.sl < sig.entry < sig.tp
