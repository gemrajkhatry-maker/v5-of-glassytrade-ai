# tests/system/test_quant_runtime_e2e.py
"""System E2E: the greenfield QuantEngine's projected state fills the exact
frontend WS contract that the legacy backend snapshot builder defines.

The engine consumes the same ``_ticks()`` fixture as the runtime test but stops
right after the AGGRESSION-LONG bar (t306) so the final snapshot's auction
phase IS the phase the LONG fired in — the projected state is the WS state the
frontend would receive at the moment of the signal.
"""

from tests.helpers.synthetic import SyntheticGateway
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws
from tests.quant.runtime.test_runtime import _ticks

WS_CONTRACT_KEYS = (
    "_symbol", "portfolio", "amt", "auction", "quantDecision",
    "agentDecision", "riskState", "tick", "ltp", "oi", "depth",
)

# The keys emitted by the WS adapter (quant/ws_adapter.py). The LLM-derived
# keys (genAIAnalysis, overseerAction, overseerReason) were removed with the
# LLM layer; agentDecision is projected from the deterministic quantDecision.
BACKEND_SNAPSHOT_KEYS = {
    "_symbol", "portfolio", "amt", "auction", "quantDecision",
    "agentDecision", "riskState",
}
ENGINE_ADDED_KEYS = {"tick", "ltp", "oi", "depth"}


def _run_ws():
    eng = QuantEngine(SyntheticGateway(_ticks()[:308]), "SYM",
                      interval_seconds=1)
    eng.run()
    return view_state_to_ws(eng.projector.snapshot("SYM"))


def test_runtime_state_fills_frontend_contract():
    ws = _run_ws()
    for key in WS_CONTRACT_KEYS:
        assert key in ws
    assert ws["_symbol"] == "SYM"
    assert ws["quantDecision"]["approved"] is True
    assert ws["quantDecision"]["phase"] == "AGGRESSION"
    assert ws["auction"]["tripleAPhase"] == "AGGRESSION"


def test_ws_contract_matches_backend_snapshot_keys():
    ws = _run_ws()
    assert BACKEND_SNAPSHOT_KEYS <= set(ws)
    assert set(ws) == BACKEND_SNAPSHOT_KEYS | ENGINE_ADDED_KEYS
