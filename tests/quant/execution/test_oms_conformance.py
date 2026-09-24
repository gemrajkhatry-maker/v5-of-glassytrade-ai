"""OMS conformance suite — ONE suite run against BOTH PaperOMS and LiveOMS.

Plan E Task 3 Half B. LiveOMS runs against FakeBroker, a fake implementing the
CURRENT quant IBroker (no dependency on the Half A port investigation).

Conformance rule: shared behavior is asserted identically for both
implementations. Where the implementations semantically diverge, the suite
asserts each implementation's CURRENT behavior in an explicit branch (no
xfail, no weakening) and documents WHY normalization would invent semantics.
Those branches are owner decisions — see ADR-0002 and the Task 3 report.

Owner-decision branches (do NOT normalize without owner sign-off):
  OD-1 add_pyramid: PaperOMS creates the add-on; LiveOMS raises ValueError
      (E9 ghost-pyramid guard). Unifying either way chooses live-trading
      semantics (allow ghost positions vs refuse adds).
  OD-2 broker rejection: LiveOMS raises RuntimeError on broker None;
      PaperOMS always fills (it is a simulator with no rejection path).
      Giving PaperOMS a rejection mode invents simulator semantics.
  OD-3 dust-fraction close_partial: size=10, fraction=0.01 -> PaperOMS closes
      a 0.1 float slice; LiveOMS int-truncates qty to 0 and returns a
      zero-fill with the position unchanged. Unifying either way chooses
      sizing semantics (float slices vs integer lots).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quant.contracts.aggregates import Portfolio
from quant.contracts.entities import Position as BrokerPosition
from quant.contracts.enums import Side, Source
from quant.contracts.ports.broker import IBroker
from quant.decision.signal_builder import Signal
from quant.execution.live_oms import LiveOMS
from quant.execution.oms import PaperOMS
from quant.execution.order import Order, Position
from quant.execution.ports import IOMS

# ---------------------------------------------------------------------------
# Fake broker (CURRENT quant IBroker) — perfect fills at requested price/size
# ---------------------------------------------------------------------------

class FakeBroker(IBroker):
    """Fake IBroker: fills everything at the requested price and size.

    Rejection mode (should_reject=True) returns None like a real broker
    refusing an order, so the LiveOMS rejection path is exercised.
    """

    def __init__(self, should_reject: bool = False):
        self.should_reject = should_reject
        self.close_call_count = 0
        self.last_close = None  # (symbol, side, quantity, reference_price)
        self.stop_call_count = 0
        self.last_stop_order_id = None

    def execute_order(self, signal, portfolio, symbol):
        if self.should_reject:
            return None
        meta = signal.metadata or {}
        qty = float(meta.get("order_quantity", 0) or 0)
        price = float(signal.price)
        return BrokerPosition(
            symbol=symbol,
            side=Side.LONG if signal.is_buy else Side.SHORT,
            source=Source.AMT,
            entry_price=Decimal(str(price)),
            size=Decimal(str(qty)),
            stop_loss=Decimal("0"),
            take_profit=Decimal("0"),
            entry_time="2026-09-03T10:00:00+05:30",
        )

    def supports_native_stop_loss(self) -> bool:
        return True

    def place_stop_loss(
        self, symbol, side, quantity, stop_price, contract_ref=None
    ) -> str | None:
        self.stop_call_count += 1
        self.last_stop_order_id = f"stop-{self.stop_call_count}"
        return self.last_stop_order_id

    def close_position(self, symbol, side, quantity, portfolio, reference_price=None):
        self.close_call_count += 1
        self.last_close = (symbol, side, quantity, reference_price)
        if self.should_reject:
            return None
        fill_price = float(reference_price) if reference_price else 0.0
        return BrokerPosition(
            symbol=symbol,
            side=Side.LONG if side == "BUY" else Side.SHORT,
            source=Source.AMT,
            entry_price=Decimal(str(fill_price)),
            size=Decimal(str(quantity)),
            stop_loss=Decimal("0"),
            take_profit=Decimal("0"),
            entry_time="2026-09-03T12:00:00+05:30",
        )

    def cancel_order(self, order_id):
        return True


# ---------------------------------------------------------------------------
# Fixture: both implementations, same lot sizes
# ---------------------------------------------------------------------------

@pytest.fixture(params=["paper", "live"])
def oms(request):
    """Build the OMS under test. LiveOMS gets a perfect-fill FakeBroker."""
    if request.param == "paper":
        return PaperOMS(lot_size=1.0)
    return LiveOMS(
        broker=FakeBroker(), portfolio=MagicMock(spec=Portfolio), lot_size=1.0
    )


@pytest.fixture(params=["paper", "live"])
def oms_lot65(request):
    if request.param == "paper":
        return PaperOMS(lot_size=65.0)
    return LiveOMS(
        broker=FakeBroker(), portfolio=MagicMock(spec=Portfolio), lot_size=65.0
    )


def _sig(direction="LONG", entry=100.0, sl=95.0, tp=110.0, symbol="SYM"):
    return Signal(
        type=direction, reason="conform", entry=entry, sl=sl, tp=tp,
        rr=2.0, model_label="Triple-A", symbol=symbol, timestamp="t0",
    )


def _pos(entry=100.0, size=10.0, symbol="SYM"):
    sig = _sig(entry=entry, symbol=symbol)
    return Position(
        order=Order(signal=sig, quantity=abs(size)),
        open_price=entry,
        open_time="t0",
        size=size,
    )


# ---------------------------------------------------------------------------
# Shared conformance: submit / close / close_partial
# ---------------------------------------------------------------------------

class TestSubmitConformance:
    def test_satisfies_ioms(self, oms):
        assert isinstance(oms, IOMS)

    def test_submit_long(self, oms):
        pos = oms.submit(_sig(), quantity=10.0)
        assert pos.size == 10.0
        assert pos.open_price == pytest.approx(100.0)

    def test_submit_short_is_negative(self, oms):
        pos = oms.submit(_sig("SHORT"), quantity=5.0)
        assert pos.size == -5.0
        assert pos.open_price == pytest.approx(100.0)

    def test_submit_snaps_to_lot(self, oms_lot65):
        pos = oms_lot65.submit(_sig(), quantity=100.0)
        assert pos.size == 130.0  # round(100/65)=2 lots

    def test_submit_minimum_one_lot(self, oms_lot65):
        pos = oms_lot65.submit(_sig(), quantity=10.0)
        assert pos.size == 65.0

    def test_submit_half_lot_rounds_up_s10(self, oms_lot65):
        # S10: half-lots round UP (banker's round(2.5)=2 under-sized P2 by 20%).
        pos = oms_lot65.submit(_sig(), quantity=2.5 * 65.0)
        assert pos.size == 3 * 65.0


class TestCloseConformance:
    def test_close_long_pnl(self, oms):
        pos = oms.submit(_sig(), quantity=10.0)
        fill = oms.close(pos, price=102.0, time="t1", reason="TP")
        assert fill.close_price == pytest.approx(102.0)
        assert fill.pnl == pytest.approx((102.0 - 100.0) * 10.0)
        assert fill.reason == "TP"

    def test_close_short_pnl(self, oms):
        pos = oms.submit(_sig("SHORT"), quantity=5.0)
        fill = oms.close(pos, price=99.0, time="t1", reason="SL")
        assert fill.pnl == pytest.approx((99.0 - 100.0) * -5.0)

    def test_close_zero_size_no_broker_call(self, oms):
        pos = _pos(entry=100.0, size=0.0)
        fill = oms.close(pos, price=100.0, time="t1", reason="TP")
        assert fill.pnl == 0.0
        if isinstance(oms, LiveOMS):
            assert oms._broker.close_call_count == 0

    def test_close_lot_scaled_pnl(self, oms_lot65):
        pos = oms_lot65.submit(_sig(), quantity=100.0)  # snapped to 130
        fill = oms_lot65.close(pos, price=102.0, time="t1", reason="TP")
        assert fill.pnl == pytest.approx((102.0 - 100.0) * 130.0)


class TestClosePartialConformance:
    @pytest.mark.parametrize("fraction,closed,remaining", [(0.50, 50.0, 50.0), (0.25, 25.0, 75.0)])
    def test_pyramid_fractions(self, oms, fraction, closed, remaining):
        # Spec 13.3 tiered TP: TP1=50%, TP2=25% of a 100-unit position.
        pos = oms.submit(_sig(), quantity=100.0)
        fill, rest = oms.close_partial(
            position=pos, fraction=fraction, price=110.0, time="t1", reason="TP1"
        )
        assert fill.position.size == pytest.approx(closed)
        assert fill.pnl == pytest.approx((110.0 - 100.0) * closed)
        assert rest.size == pytest.approx(remaining)
        assert rest._id == pos._id  # _id preserved so trail/breakeven persist
        assert rest.open_price == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Owner-decision branches (explicit, xfail-free — see module docstring)
# ---------------------------------------------------------------------------

class TestOwnerDecisions:
    def test_od1_add_pyramid(self, oms):
        """OD-1: PaperOMS creates the pyramid; LiveOMS refuses (E9)."""
        base = oms.submit(_sig(entry=100.0, sl=95.0, tp=115.0), quantity=40.0)
        if isinstance(oms, LiveOMS):
            with pytest.raises(ValueError, match="E9: pyramids disabled"):
                oms.add_pyramid(
                    base=base, entry_price=105.0, new_sl=102.0,
                    size=25.0, time="t1", pyramid_level=1,
                )
        else:
            pyr1 = oms.add_pyramid(
                base=base, entry_price=105.0, new_sl=102.0,
                size=20.0, time="t1", pyramid_level=1,
            )
            assert pyr1.pyramid_level == 1
            assert pyr1.is_pyramid is True
            assert pyr1.size == 20.0  # 50% of base
            assert pyr1.open_price == pytest.approx(105.0)
            assert pyr1.order.signal.tp == pytest.approx(115.0)  # inherits base TP
            pyr2 = oms.add_pyramid(
                base=base, entry_price=106.0, new_sl=103.0,
                size=10.0, time="t2", pyramid_level=2,
            )
            assert pyr2.size == 10.0  # 25% of base
            assert pyr2.pyramid_level == 2

    def test_od2_broker_rejection(self, oms):
        """OD-2: LiveOMS surfaces broker rejection as RuntimeError; PaperOMS
        always fills (simulator — no rejection path exists)."""
        if isinstance(oms, LiveOMS):
            oms._broker.should_reject = True
            with pytest.raises(RuntimeError, match="broker rejected"):
                oms.submit(_sig(), quantity=10.0)
            pos = _pos(entry=100.0, size=10.0)
            with pytest.raises(RuntimeError, match="broker failed to close"):
                oms.close(pos, price=102.0, time="t1", reason="TP")
        else:
            pos = oms.submit(_sig(), quantity=10.0)
            assert pos.size == 10.0
            fill = oms.close(pos, price=102.0, time="t1", reason="TP")
            assert fill.pnl == pytest.approx(20.0)

    def test_od3_dust_fraction_close_partial(self, oms):
        """OD-3: fraction so small int(closed) truncates to 0 — PaperOMS books
        a 0.1-unit float slice; LiveOMS returns a zero-fill, position intact."""
        pos = oms.submit(_sig(), quantity=10.0)
        fill, rest = oms.close_partial(
            position=pos, fraction=0.01, price=110.0, time="t1", reason="TP1"
        )
        if isinstance(oms, LiveOMS):
            assert fill.pnl == 0.0
            assert rest.size == pytest.approx(10.0)
        else:
            assert fill.position.size == pytest.approx(0.1)
            assert fill.pnl == pytest.approx((110.0 - 100.0) * 0.1)
            assert rest.size == pytest.approx(9.9)
