from __future__ import annotations
import time
from typing import Protocol
from quantv2.oms import Position
from quantv2.types import Signal

class SubmitError(Exception):
    pass

class RestPort(Protocol):
    def place(self, order: dict) -> dict: ...
    def orders(self) -> list: ...

_SIDE = {"LONG": "BUY", "SHORT": "SELL"}

class DhanBroker:
    def __init__(self, rest: RestPort, product: str = "MIS", poll_attempts: int = 20, poll_delay: float = 0.25) -> None:
        self.rest = rest
        self.product = product
        self.poll_attempts = poll_attempts
        self.poll_delay = poll_delay

    def submit(self, signal: Signal, qty: float) -> Position:
        order = {
            "securityId": signal.symbol,
            "transactionType": _SIDE[signal.type],
            "quantity": int(qty),
            "orderType": "MARKET",
            "productType": self.product,
        }
        resp = self.rest.place(order)
        oid = resp.get("orderId")
        if not oid:
            raise SubmitError(f"no orderId: {resp}")
        for _ in range(self.poll_attempts):
            for o in self.rest.orders():
                if o.get("orderId") == oid and o.get("orderStatus") == "TRADED":
                    return Position(
                        pid=str(oid), symbol=signal.symbol, side=signal.type,
                        qty=float(o.get("filledQty") or qty),
                        entry=float(o.get("averageTradedPrice") or signal.entry),
                        sl=signal.sl, tp=signal.tp, setup=signal.setup, opened_at=signal.timestamp,
                    )
            time.sleep(self.poll_delay)
        raise SubmitError(f"order {oid} not filled in {self.poll_attempts} polls")

def reconcile(ours: list, theirs: list) -> list[str]:
    a = {getattr(p, "symbol", None): float(getattr(p, "qty", 0.0)) for p in ours}
    b = {getattr(p, "symbol", None): float(getattr(p, "qty", 0.0)) for p in theirs}
    out = []
    for sym in sorted(set(a) | set(b)):
        if a.get(sym, 0.0) != b.get(sym, 0.0):
            out.append(f"{sym}: ours={a.get(sym, 0.0)} broker={b.get(sym, 0.0)}")
    return out