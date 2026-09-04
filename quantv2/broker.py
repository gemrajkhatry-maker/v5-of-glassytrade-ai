from __future__ import annotations
from typing import Protocol, runtime_checkable
from quantv2.types import Signal
from quantv2.oms import Position


class LiveNotEnabled(Exception):
    pass


@runtime_checkable
class BrokerPort(Protocol):
    """Live broker port contract: submit MUST return a quantv2 Position or raise."""
    def submit(self, signal, qty: float): ...


class BrokerAdapter:
    def __init__(self, mode: str = "paper", oms=None, live_port=None) -> None:
        assert mode in ("paper", "live")
        self.mode = mode
        self.oms = oms
        self.live_port = live_port

    def submit(self, signal: Signal, qty: float) -> Position:
        if self.mode == "paper":
            return self.oms.submit(signal, qty)
        if self.live_port is None:
            raise LiveNotEnabled("live port not wired (paper-live phase)")
        return self.live_port.submit(signal, qty)
