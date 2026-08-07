"""Unit tests for the standalone live engine runner (no network)."""

from __future__ import annotations

from quant.brokers.gateway import Tick
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws

from app.infrastructure.adapters.live_engine_server import run_live_engine  # noqa: F401


class FakeGateway:
    def __init__(self, ticks):
        self._ticks = list(ticks)

    def subscribe(self, symbol: str) -> None:
        pass

    def next_tick(self) -> Tick | None:
        if not self._ticks:
            return None
        return self._ticks.pop(0)


def _ticks() -> list[Tick]:
    return [
        Tick(time="0", price=100.0, volume=10.0, buy_volume=5.0, sell_volume=5.0),
        Tick(time="60", price=101.5, volume=15.0, buy_volume=10.0, sell_volume=5.0),
        Tick(time="120", price=103.0, volume=20.0, buy_volume=12.0, sell_volume=8.0),
        Tick(time="180", price=102.0, volume=25.0, buy_volume=15.0, sell_volume=10.0),
    ]


def test_view_state_to_ws_has_frontend_snapshot_keys():
    eng = QuantEngine(FakeGateway(_ticks()), "NIFTY", interval_seconds=60)
    eng.run()

    ws = view_state_to_ws(eng.projector.snapshot("NIFTY"))

    expected = {
        "_symbol",
        "portfolio",
        "amt",
        "auction",
        "quantDecision",
        "genAIAnalysis",
        "overseerAction",
        "overseerReason",
        "agentDecision",
        "riskState",
        "tick",
        "ltp",
        "oi",
        "depth",
    }
    assert set(ws) == expected
    assert ws["_symbol"] == "NIFTY"
    assert ws["tick"] is not None
    assert ws["ltp"] is not None
    assert ws["auction"] is not None
