"""System E2E: synthetic tick session -> QuantEngine -> AuctionUpdated trace
(AGGRESSION/LONG) -> WS ``auction`` DTO via view_state_to_ws.

The current architecture: QuantEngine aggregates ticks into bars, folds them
through AuctionCoordinator (Triple-A state machine), and StateProjector
serializes each AuctionState into the frontend's ``auction`` contract.
"""

import pathlib
import sys

_BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from quant.brokers.gateway import Tick
from quant.events import AmtUpdated
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway

SYMBOL = "SYM"


def _session_ticks():
    """Deterministic AGGRESSION-LONG session (proven shape from
    tests/quant/runtime): ~150 quiet 0.1-range bars @100 (keeps avg_range > 0
    so the zero-range spike passes range_ok), an absorption spike bar (zero
    range, 5x volume, 90% buys), accumulation near POC, then rising closes
    above vwap.upper_1 -> AGGRESSION/LONG on the final bar."""
    out = [
        Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 6, 4)
        for i in range(300)
    ]
    out.append(Tick("t300", 100.0, 500, 450, 50))
    for i in range(1, 6):
        out.append(Tick(f"t{300 + i}", 100.0, 10, 6, 4))
    for i, price in enumerate([100.3, 100.6, 100.9, 101.2]):
        out.append(Tick(f"t{306 + i}", price, 10, 6, 4))
    return out


def _run_trace():
    eng = QuantEngine(
        SyntheticGateway(_session_ticks()), SYMBOL, interval_seconds=1
    )
    return eng.run()


def _amts(trace):
    return [e.amt for e in trace if isinstance(e, AmtUpdated)]


def test_amt_trace_produces_unified_results():
    amts = _amts(_run_trace())
    assert len(amts) >= 150
    assert all(isinstance(a, dict) and "poc" in a and "marketState" in a for a in amts)
    assert any(a["marketState"] in ("BALANCED", "IMBALANCED") for a in amts)


def test_dto_has_ws_amt_contract_keys():
    eng = QuantEngine(
        SyntheticGateway(_session_ticks()), SYMBOL, interval_seconds=1
    )
    eng.run()
    from quant.ws_adapter import view_state_to_ws

    last = view_state_to_ws(eng.projector.snapshot(SYMBOL))
    amt = last["amt"]
    assert amt is not None, "projector must carry the final amt state"
    assert {"poc", "valueAreaHigh", "valueAreaLow", "marketState", "sessionVwap", "profile"} <= set(amt)


def test_determinism_same_bars_same_trace():
    from quant.events import AgentDecisionProduced
    t1 = [e for e in _run_trace() if not isinstance(e, AgentDecisionProduced)]
    t2 = [e for e in _run_trace() if not isinstance(e, AgentDecisionProduced)]
    assert [(type(e).__name__, getattr(e, "time", "")) for e in t1] == [(type(e).__name__, getattr(e, "time", "")) for e in t2]
