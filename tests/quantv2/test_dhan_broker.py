from quantv2.dhan_broker import DhanBroker, SubmitError, reconcile
from quantv2.types import Signal
import pytest

class FakeRest:
    def __init__(self):
        self.placed = []
        self._fills = []
    def place(self, order: dict) -> dict:
        self.placed.append(order)
        return {"orderId": f"o{len(self.placed)}", "orderStatus": "PENDING"}
    def orders(self):
        return self._fills

def test_submit_polls_to_filled():
    rest = FakeRest()
    b = DhanBroker(rest)
    sig = Signal(type="LONG", entry=100.0, sl=99.0, tp=102.0, rr=2.0, setup="T", symbol="NF", timestamp="t")
    rest._fills = [{"orderId": "o1", "orderStatus": "TRADED", "filledQty": 75, "averageTradedPrice": 100.1}]
    pos = b.submit(sig, 75.0)
    assert pos.qty == 75.0 and pos.entry == 100.1 and pos.side == "LONG"

def test_unfilled_raises():
    rest = FakeRest()
    b = DhanBroker(rest, poll_attempts=1)
    sig = Signal(type="LONG", entry=100.0, sl=99.0, tp=102.0, rr=2.0, setup="T", symbol="NF", timestamp="t")
    with pytest.raises(SubmitError):
        b.submit(sig, 75.0)

def test_reconcile_reports_mismatch():
    class P:
        def __init__(self, symbol, qty):
            self.symbol = symbol
            self.qty = qty
    out = reconcile([P("NF", 75)], [P("NF", 150)])
    assert out and "NF" in out[0]