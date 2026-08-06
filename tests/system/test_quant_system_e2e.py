"""System E2E: synthetic OHLC session -> AuctionCoordinator -> QuantBridge
-> WS ``auction`` DTO (shared frontend contract).

This is the backend half of the true end-to-end wiring: a synthetic session
drives the greenfield `quant.AuctionCoordinator` to AGGRESSION/LONG, and its
`AuctionState` is serialized via `auction_state_to_dto` into the snapshot's
``auction`` field exactly as the WS frontend test consumes it.
"""

import json
import pathlib
import sys

_BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.application.services.quant_bridge import QuantBridge
from quant.contracts.value_objects import OHLC

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ws_session_long.json"


def _session_ohlc():
    """Deterministic 60-bar synthetic session (AGGRESSION-LONG on bar 59).

    Mirrors the greenfield determinism pattern from tests/quant: quiet bars
    @100 -> absorption spike bar (500 vol, 450 buys, tight range) -> rising
    closes that break above vwap.upper_1 near POC.

      bars 0-54   quiet at 100, vol 100                  -> WAITING
      bar  55     volume spike 5x, zero range @100, 90% buys -> BUY absorption
      bars 56-58  accumulation near POC (100)            -> ABSORBING -> ACCUMULATING
      bar  59     breakout 104 (> vwap.upper_1)          -> AGGRESSION -> LONG
    """
    out = []
    for i in range(55):
        out.append(OHLC.create(f"t{i}", 100, 101, 99, 100, 100, 0, 60, 20))
    out.append(OHLC.create("t55", 100, 100, 100, 100, 500, 0, 450, 400))
    for i in range(56, 59):
        out.append(OHLC.create(f"t{i}", 100, 101, 99, 100, 100, 0, 60, 20))
    out.append(OHLC.create("t59", 103.5, 105, 103, 104, 100, 0, 60, 20))
    return out


def _run_trace():
    bridge = QuantBridge()
    return [bridge.on_bar_close("SYM", ohlc) for ohlc in _session_ohlc()]


def test_auction_trace_reaches_aggression_long():
    dtos = _run_trace()
    assert len(dtos) == 60
    # intermediate progression: spike re-arms ABSORBING, near-POC accumulation,
    # then the breakout bar trips AGGRESSION/LONG on the final bar.
    assert dtos[55]["tripleAPhase"] == "ABSORBING"
    assert dtos[57]["tripleAPhase"] == "ACCUMULATING"
    assert dtos[-1]["tripleAPhase"] == "AGGRESSION"
    assert dtos[-1]["tripleASignal"] == "LONG"
    assert dtos[-1]["close"] > dtos[-1]["vwap"]["upper1"]


def test_dto_has_ws_auction_contract_keys():
    last = _run_trace()[-1]
    vp = last["volumeProfile"]
    vw = last["vwap"]
    of = last["orderFlow"]
    loc = last["location"]
    assert {"poc", "vah", "val"} <= set(vp)
    assert {"value", "deviationSigmas"} <= set(vw)
    assert {"cvd", "cvdSlope"} <= set(of)
    assert "zone" in loc
    assert "tripleAPhase" in last and "tripleASignal" in last


def test_determinism_same_bars_same_trace():
    assert _run_trace() == _run_trace()


def test_fixture_matches_trace():
    """Committed fixture = the shared contract the frontend test consumes."""
    fixture = json.loads(FIXTURE.read_text())
    assert fixture == _run_trace()
