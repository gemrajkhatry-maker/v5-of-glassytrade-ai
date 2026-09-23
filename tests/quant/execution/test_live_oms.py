"""Unit tests for LiveOMS — the live order management system.

Tests use a MockBroker that implements IBroker to verify LiveOMS
without touching a real exchange.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quant.contracts.aggregates import Portfolio
from quant.contracts.entities import Position as BrokerPosition
from quant.contracts.enums import Side, SignalType, Source
from quant.contracts.ports.broker import IBroker
from quant.decision.signal_builder import Signal
from quant.execution.live_oms import LiveOMS
from quant.execution.lots import snap_to_lot
from quant.execution.order import Position


class MockBroker(IBroker):
    """Mock broker that simulates fills at requested prices."""

    def __init__(
        self,
        fill_price: float = 100.0,
        fill_qty: float = 100.0,
        should_reject: bool = False,
    ):
        self.fill_price = fill_price
        self.fill_qty = fill_qty
        self.should_reject = should_reject
        self.last_close_symbol = None
        self.last_close_side = None
        self.last_close_qty = None
        self.close_call_count = 0

    def execute_order(self, signal, portfolio, symbol):
        if self.should_reject:
            return None
        return BrokerPosition(
            symbol=symbol,
            side=Side.LONG if signal.type == SignalType.BUY else Side.SHORT,
            source=Source.AMT,
            entry_price=Decimal(str(self.fill_price)),
            size=Decimal(str(self.fill_qty)),
            stop_loss=Decimal("0"),
            take_profit=Decimal("0"),
            entry_time="2026-08-26T10:00:00+05:30",
        )

    def close_position(self, symbol, side, quantity, portfolio, reference_price=None):
        self.last_close_symbol = symbol
        self.last_close_side = side
        self.last_close_qty = quantity
        self.last_close_reference_price = reference_price
        self.close_call_count += 1
        if self.should_reject:
            return None
        return BrokerPosition(
            symbol=symbol,
            side=Side.LONG if side == "BUY" else Side.SHORT,
            source=Source.AMT,
            entry_price=Decimal(str(self.fill_price)),  # fill price on close
            size=Decimal(str(quantity)),
            stop_loss=Decimal("0"),
            take_profit=Decimal("0"),
            entry_time="2026-08-26T12:00:00+05:30",
        )

    def cancel_order(self, order_id):
        return True


def _make_signal(entry=100.0, sl=95.0, tp=110.0, symbol="NIFTY 24800 CE"):
    return Signal(
        type="LONG",
        reason="test",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=2.0,
        model_label="Triple-A",
        symbol=symbol,
        timestamp="2026-08-26T10:00:00+05:30",
    )


def _make_position(entry=100.0, size=130.0, symbol="NIFTY 24800 CE"):
    sig = _make_signal(entry=entry, symbol=symbol)
    return Position(
        order=MagicMock(signal=sig, quantity=abs(size)),
        open_price=entry,
        open_time="2026-08-26T10:00:00+05:30",
        size=size,
    )


# ---------------------------------------------------------------------------
# IOMS compliance
# ---------------------------------------------------------------------------

class TestLiveOMSProtocolCompliance:
    def test_satisfies_ioms_at_runtime(self):
        from quant.execution.ports import IOMS
        broker = MockBroker()
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)
        assert isinstance(oms, IOMS)

    def test_lot_size_property(self):
        broker = MockBroker()
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio, lot_size=65.0)
        assert oms.lot_size == 65.0


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

class TestLiveOMSSubmit:
    @pytest.mark.parametrize("bad_quantity", [0.0, -1.0, float("nan"), float("inf")])
    def test_invalid_quantity_fails_before_broker_call(self, bad_quantity):
        broker = _CapturingBroker()
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio, lot_size=65.0)

        with pytest.raises(ValueError, match="quantity"):
            oms.submit(_make_signal(), quantity=bad_quantity)

        assert broker.last_signal is None

    def test_submit_long_creates_position(self):
        broker = MockBroker(fill_price=102.0, fill_qty=130.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio, lot_size=65.0)

        signal = _make_signal(entry=100.0)
        pos = oms.submit(signal, quantity=130.0)

        assert pos is not None
        assert pos.open_price == 102.0
        assert pos.size == 130.0
        assert pos.order.signal == signal

    def test_submit_short_creates_negative_position(self):
        broker = MockBroker(fill_price=98.0, fill_qty=65.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio, lot_size=65.0)

        signal = Signal(
            type="SHORT", reason="test", entry=100.0, sl=105.0, tp=90.0,
            rr=2.0, model_label="Triple-A", symbol="NIFTY", timestamp="t0",
        )
        pos = oms.submit(signal, quantity=65.0)

        assert pos.size == -65.0
        assert pos.open_price == 98.0

    def test_submit_reject_raises(self):
        broker = MockBroker(should_reject=True)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)

        signal = _make_signal()
        with pytest.raises(RuntimeError, match="broker rejected"):
            oms.submit(signal, quantity=100.0)


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestLiveOMSClose:
    def test_close_long_sends_sell_order(self):
        broker = MockBroker(fill_price=105.0, fill_qty=130.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)

        pos = _make_position(entry=100.0, size=130.0)
        fill = oms.close(pos, price=105.0, time="t1", reason="TP")

        assert broker.last_close_side == "SELL"
        assert broker.last_close_qty == 130
        assert fill.close_price == 105.0
        assert fill.pnl == pytest.approx((105.0 - 100.0) * 130.0)
        assert fill.reason == "TP"

    def test_close_short_sends_buy_order(self):
        broker = MockBroker(fill_price=95.0, fill_qty=65.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)

        pos = _make_position(entry=100.0, size=-65.0)
        fill = oms.close(pos, price=95.0, time="t1", reason="TP")

        assert broker.last_close_side == "BUY"
        assert broker.last_close_qty == 65
        assert fill.pnl == pytest.approx((95.0 - 100.0) * (-65.0))

    def test_close_threads_exit_price_as_reference(self):
        """C7: the exit price is passed to the broker as reference_price (collar)."""
        broker = MockBroker(fill_price=105.0, fill_qty=130.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)

        pos = _make_position(entry=100.0, size=130.0)
        oms.close(pos, price=105.0, time="t1", reason="TP")

        assert broker.last_close_reference_price == 105.0

    def test_close_broker_failure_raises(self):
        broker = MockBroker(should_reject=True)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)

        pos = _make_position()
        with pytest.raises(RuntimeError, match="broker failed to close"):
            oms.close(pos, price=105.0, time="t1", reason="TP")

    def test_close_zero_size_returns_zero_pnl(self):
        broker = MockBroker()
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)

        pos = _make_position(entry=100.0, size=0.0)
        fill = oms.close(pos, price=100.0, time="t1", reason="TP")

        assert fill.pnl == 0.0
        assert broker.close_call_count == 0  # no broker call


# ---------------------------------------------------------------------------
# close_partial
# ---------------------------------------------------------------------------

class TestLiveOMSClosePartial:
    def test_close_partial_50_percent(self):
        broker = MockBroker(fill_price=105.0, fill_qty=65.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)

        pos = _make_position(entry=100.0, size=130.0)
        fill, remaining = oms.close_partial(pos, fraction=0.50, price=105.0, time="t1", reason="TP1")

        assert broker.last_close_qty == 65  # 130 * 0.5
        assert fill.position.size == 65.0
        assert fill.pnl == pytest.approx((105.0 - 100.0) * 65.0)
        assert remaining.size == 65.0
        assert remaining._id == pos._id  # preserves position ID

    def test_close_partial_preserves_position_id(self):
        broker = MockBroker(fill_price=105.0, fill_qty=32.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio)

        pos = _make_position(entry=100.0, size=130.0)
        _, remaining = oms.close_partial(pos, fraction=0.25, price=105.0, time="t1", reason="TP1")

        assert remaining._id == pos._id
        assert remaining.pyramid_level == pos.pyramid_level
        assert remaining.is_pyramid == pos.is_pyramid


# ---------------------------------------------------------------------------
# add_pyramid
# ---------------------------------------------------------------------------

class TestLiveOMSAddPyramid:
    def test_pyramid_disabled_under_live_oms(self):
        broker = MockBroker()
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio, lot_size=65.0)

        base = _make_position(entry=100.0, size=130.0)
        with pytest.raises(ValueError, match="E9: pyramids disabled under LiveOMS"):
            oms.add_pyramid(
                base=base, entry_price=102.0, new_sl=100.0,
                size=65.0, time="t1", pyramid_level=1,
            )


# ---------------------------------------------------------------------------
# lot snapping
# ---------------------------------------------------------------------------

class TestLiveOMSLotSnapping:
    def test_snaps_to_lot_multiple(self):
        assert snap_to_lot(100.0, 65.0) == 130.0  # 2 lots
        assert snap_to_lot(65.0, 65.0) == 65.0    # 1 lot
        assert snap_to_lot(30.0, 65.0) == 65.0    # minimum 1 lot
        assert snap_to_lot(200.0, 65.0) == 195.0  # 3 lots


# ---------------------------------------------------------------------------
# C1: submit must carry the engine-sized, lot-snapped quantity to the broker
# signal. Before the fix the sized quantity was dropped at to_broker_signal and
# the adapter re-derived it against a frozen phantom portfolio — the exchange
# never received the size the risk layer approved.
# ---------------------------------------------------------------------------

class _CapturingBroker(MockBroker):
    """MockBroker that records the broker signal handed to execute_order."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_signal = None

    def execute_order(self, signal, portfolio, symbol):
        self.last_signal = signal
        return super().execute_order(signal, portfolio, symbol)


class TestLiveOMSSubmitCarriesEngineQuantity:
    def test_submit_passes_quantity_to_broker_signal(self):
        broker = _CapturingBroker(fill_price=102.0, fill_qty=130.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio, lot_size=65.0)

        oms.submit(_make_signal(entry=100.0), quantity=130.0)

        meta = broker.last_signal.metadata or {}
        assert meta.get("order_quantity") == 130.0, (
            "engine-sized quantity must be carried to the broker signal so the "
            "adapter executes it instead of re-sizing"
        )

    def test_submit_snaps_quantity_to_lot_before_passing(self):
        broker = _CapturingBroker(fill_price=102.0, fill_qty=130.0)
        portfolio = MagicMock(spec=Portfolio)
        oms = LiveOMS(broker=broker, portfolio=portfolio, lot_size=65.0)

        # 100 units at lot 65 -> 2 lots = 130
        oms.submit(_make_signal(entry=100.0), quantity=100.0)

        meta = broker.last_signal.metadata or {}
        assert meta.get("order_quantity") == 130.0
