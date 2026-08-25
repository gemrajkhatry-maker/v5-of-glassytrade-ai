# tests/system/test_quant_runtime_e2e.py
"""System E2E: the greenfield QuantEngine's projected state fills the exact
frontend WS contract that the legacy backend snapshot builder defines.

The engine consumes the same ``_ticks()`` fixture as the runtime test but stops
right after the AGGRESSION-LONG bar (t306) so the final snapshot's decision
state IS the state at the moment the LONG fired — the projected state is the
WS state the frontend would receive at that moment.
"""

from tests.helpers.synthetic import SyntheticGateway
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws
from tests.quant.runtime.test_runtime import _ticks

WS_CONTRACT_KEYS = (
    "_symbol", "portfolio", "amt", "quantDecision",
    "agentDecision", "riskState", "tick", "ltp", "oi", "depth",
)

# The keys emitted by the WS adapter (quant/ws_adapter.py). The LLM-derived
# keys (genAIAnalysis, overseerAction, overseerReason) were removed with the
# LLM layer; agentDecision is projected from the deterministic quantDecision.
BACKEND_SNAPSHOT_KEYS = {
    "_symbol", "portfolio", "amt", "quantDecision",
    "agentDecision", "riskState",
}
ENGINE_ADDED_KEYS = {"tick", "ltp", "oi", "depth"}


from tests.system.test_paper_protocol import _session_ticks


def _run_ws():
    from quant.execution.risk import SessionRisk
    SessionRisk(storage=None, symbol="SYM").reset_session()
    eng = QuantEngine(SyntheticGateway(_session_ticks()[:170]), "SYM",
                      interval_seconds=2)
    eng.run()
    return view_state_to_ws(eng.projector.snapshot("SYM"))


def test_runtime_state_fills_frontend_contract():
    ws = _run_ws()
    for key in WS_CONTRACT_KEYS:
        assert key in ws
    assert ws["_symbol"] == "SYM"
    assert ws["quantDecision"]["approved"] is True
    assert ws["amt"] is not None
    assert "marketState" in ws["amt"]


def test_ws_contract_matches_backend_snapshot_keys():
    ws = _run_ws()
    assert BACKEND_SNAPSHOT_KEYS <= set(ws)
    assert set(ws) == BACKEND_SNAPSHOT_KEYS | ENGINE_ADDED_KEYS
