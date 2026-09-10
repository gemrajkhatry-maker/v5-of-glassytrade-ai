"""Structured block_reasons on every emitted decision (Task 11).

When the gate pipeline rejects a setup, the emitted ``DecisionProduced`` (and
the engine's ``latest_quant_decision`` view) must enumerate every failed gate as
``"NAME: reason"`` strings via ``GateResult.name`` — not just the first
failing gate's reason.
"""

from quant.brokers.gateway import Tick
from quant.events import DecisionProduced
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def _force_allowlisted_quality(monkeypatch):
    """Replay fixture carries footprint-grade provenance.

    The data-quality gate is STRICT everywhere (incl. replay): synthetic
    ticks aggregate into bars with no completed tick footprints, so the DTO
    derives CANDLE_GAUSSIAN and DecisionService short-circuits with
    DATA_QUALITY_BLOCKED before any gate runs. These tests target the
    post-gate block-reason contract, so the fixture stands in for a
    footprint-grade feed by stamping the allowlisted TICK_EXACT quality.
    """
    import quant.amt_engine as _amt_engine_mod

    _real = _amt_engine_mod.amt_result_to_dto

    def _wrapped(result):
        dto = _real(result)
        dto["dataQuality"] = "TICK_EXACT"
        return dto

    monkeypatch.setattr(_amt_engine_mod, "amt_result_to_dto", _wrapped)


def _blocked_ticks():
    """Ticks that drive the engine to a decision with several failed gates.

    Synthetic ``tNN`` tick ids carry no parseable timestamp, so warmup
    (gate-level, not the wall-clock session gate) blocks every decision. Two
    windows = one closed bar = one decision.
    """
    return [Tick(f"t{i}", 100.0, 10, 6, 4) for i in range(6)]


def test_block_reasons_listed_on_rejected_decision(monkeypatch):
    _force_allowlisted_quality(monkeypatch)
    eng = QuantEngine(SyntheticGateway(_blocked_ticks()), "SYM", interval_seconds=1)
    trace = eng.run()

    decisions = [e for e in trace if isinstance(e, DecisionProduced)]
    assert decisions, "engine must emit at least one decision"
    for evt in decisions:
        br = evt.decision.block_reasons
        assert isinstance(br, tuple)
        assert all(isinstance(s, str) for s in br)
        failed = [g for g in evt.decision.gate_results if not g.passed]
        assert br == tuple(f"{g.name}: {g.reason}" for g in failed)


def test_block_reasons_use_symbolic_gate_names(monkeypatch):
    _force_allowlisted_quality(monkeypatch)
    eng = QuantEngine(SyntheticGateway(_blocked_ticks()), "SYM", interval_seconds=1)
    trace = eng.run()

    blocked = next(
        e for e in trace
        if isinstance(e, DecisionProduced) and e.decision.block_reasons
    )
    assert any(s.startswith("SESSION_PHASE:") for s in blocked.decision.block_reasons)
    assert any(
        s.startswith("TRIPLE_A_EDGE:")
        for s in blocked.decision.block_reasons
    )


def test_block_reasons_reach_engine_quant_decision_view(monkeypatch):
    _force_allowlisted_quality(monkeypatch)
    eng = QuantEngine(SyntheticGateway(_blocked_ticks()), "SYM", interval_seconds=1)
    eng.run()

    view = eng.latest_quant_decision
    assert view is not None
    br = view["blockReasons"]
    assert isinstance(br, list) and br
    assert any(s.startswith("SESSION_PHASE:") for s in br)
    assert any(s.startswith("TRIPLE_A_EDGE:") for s in br)
    failed = [g for g in view["gateResults"] if not g["passed"]]
    assert br == [f"{g['name']}: {g['reason']}" for g in failed]
    assert tuple(br) == tuple(f"{g['name']}: {g['reason']}" for g in failed)
