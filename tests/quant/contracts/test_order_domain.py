from dataclasses import replace
from types import SimpleNamespace

from brokers.broker.dhan.domain.order_status import (
    DHAN_ORDER_STATUS_MAP,
    TERMINAL_STATUSES,
    is_terminal,
    normalize_status,
)
from brokers.broker.types import OrderStatus
from quant.decision.signal_builder import Signal as EngineSignal
from quant.decision.signal_builder import (
    SignalBuilder,
    clamp_quantity,
    is_stop_too_thin,
)
from quant.execution.fills import broker_position_to_fill
from quant.execution.lots import snap_to_lot
from quant.execution.order import Order, Position, position_to_row, row_to_position


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


def _eng_position(pyramid=False, level=0):
    sig = EngineSignal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0,
                       rr=2.0, model_label="Triple-A", symbol="NIFTY", timestamp="t")
    return Position(order=Order(signal=sig, quantity=65.0), open_price=100.0,
                    open_time="t", size=65.0, pyramid_level=level, is_pyramid=pyramid)


def test_id_alias_matches_private():
    p = _eng_position()
    assert p.id == p._id and len(p.id) > 0


def test_row_roundtrip_base_and_pyramid():
    for p in (_eng_position(), _eng_position(pyramid=True, level=1)):
        row = position_to_row("NIFTY", p)
        q = row_to_position(row)
        assert q._id == p._id and q.size == p.size and q.open_price == p.open_price
        assert q.order.signal.entry == 100.0 and q.order.quantity == 65.0
        assert q.pyramid_level == p.pyramid_level and q.is_pyramid == p.is_pyramid
        assert row["side"] == "LONG" and row["symbol"] == "NIFTY"


def test_stop_order_id_roundtrips_through_persistence_row():
    p = replace(_eng_position(), stop_order_id="stop-1")
    row = position_to_row("NIFTY", p)
    restored = row_to_position(row)
    assert row["stop_order_id"] == "stop-1"
    assert restored.stop_order_id == "stop-1"


def test_fill_mapping_exact_values():
    bp = SimpleNamespace(entry_price=101.5, size=65)
    f = broker_position_to_fill(bp, fallback_price=100.0, fallback_qty=65.0)
    assert (f.fill_price, f.filled_qty, f.fill_quantity_assumed) == (101.5, 65.0, False)


def test_fill_mapping_fallbacks_marked():
    f = broker_position_to_fill(SimpleNamespace(), fallback_price=100.0, fallback_qty=65.0)
    assert (f.fill_price, f.filled_qty, f.fill_quantity_assumed) == (100.0, 65.0, True)
    g = broker_position_to_fill(SimpleNamespace(entry_price=101.5), fallback_price=100.0, fallback_qty=65.0)
    assert (g.fill_price, g.filled_qty, g.fill_quantity_assumed) == (101.5, 65.0, True)


def test_snap_matrix():
    assert snap_to_lot(130.0, 65.0) == 130.0
    assert snap_to_lot(100.0, 65.0) == 130.0
    assert snap_to_lot(10.0, 65.0) == 65.0      # minimum one lot
    assert snap_to_lot(2.5 * 65.0, 65.0) == 3 * 65.0  # half-lots round UP (S10)
    assert snap_to_lot(0.0, 65.0) == 0.0
    assert snap_to_lot(100.0, 0.0) == 100.0     # bad lot passthrough
    assert snap_to_lot(100.0, -5.0) == 100.0
