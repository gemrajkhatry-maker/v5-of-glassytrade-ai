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
from quant.events import AuctionUpdated
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


def _auctions(trace):
    return [e.auction for e in trace if isinstance(e, AuctionUpdated)]


def test_auction_trace_reaches_aggression_long():
    auctions = _auctions(_run_trace())
    assert len(auctions) == 155
    # intermediate progression: absorption re-arms ABSORBING, near-POC
    # accumulation, then rising closes trip AGGRESSION/LONG.
    phases = [a.triple_a_phase for a in auctions]
    assert "ABSORBING" in phases
    assert "ACCUMULATING" in phases
    assert phases.index("ABSORBING") < phases.index("ACCUMULATING")
    # The breakout bar trips AGGRESSION/LONG; the machine re-arms afterwards.
    agg = [a for a in auctions if a.triple_a_phase == "AGGRESSION"]
    assert agg, "AGGRESSION must be reached"
    assert agg[-1].triple_a_signal == "LONG"
    assert agg[-1].close > agg[-1].vwap.upper_1


def test_dto_has_ws_auction_contract_keys():
    eng = QuantEngine(
        SyntheticGateway(_session_ticks()), SYMBOL, interval_seconds=1
    )
    eng.run()
    from quant.ws_adapter import view_state_to_ws

    last = view_state_to_ws(eng.projector.snapshot(SYMBOL))
    auction = last["auction"]
    assert auction is not None, "projector must carry the final auction state"
    vp = auction["volumeProfile"]
    vw = auction["vwap"]
    of = auction["orderFlow"]
    loc = auction["location"]
    assert {"poc", "vah", "val"} <= set(vp)
    assert {"value", "deviationSigmas"} <= set(vw)
    assert {"cvd", "cvdSlope"} <= set(of)
    assert "zone" in loc
    assert "tripleAPhase" in auction and "tripleASignal" in auction


def test_determinism_same_bars_same_trace():
    assert _run_trace() == _run_trace()
