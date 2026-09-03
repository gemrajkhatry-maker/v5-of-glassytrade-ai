# tests/quant/test_fast_determinism_parity.py
"""Phase 6: fast replay-determinism parity probe.

The heavy determinism battery (tests/quant/test_determinism.py) replays three
golden sessions 10x through the replay harness and takes minutes. This probe
runs the SAME tick sequence through two FRESH QuantEngines and asserts the
full event traces are identical element-for-element — decision path AND
position-management path. Event dataclasses ignore ``correlation_id`` and
position ``_id`` (compare=False), so identity-free equality is exact.

Residual wall-clock touchpoints (NOT in the decision path; documented here
so replay harnesses know the boundaries):

- ``SessionRisk._today()`` (quant/execution/risk.py) keys the persisted
  daily budget by the IST calendar date. In-memory decisions never read the
  clock; a REPLAY that straddles IST midnight would switch storage keys on
  trade record. Deterministic runs must stay within one IST date.
- ``parse_contract_expiry(today=...)`` (quant/session_gates.py) already
  accepts an injected clock for replay/cert paths.
- ``session_allow_entry``/``session_force_exit`` treat unparseable
  (synthetic/replay) timestamps as open by design — replay traces never
  depend on wall-clock time (documented in session_gates).
- Coordinator layer (EOD watchdog, staleness/rotation, square-off) reads the
  wall clock by design — it is the operator layer, never a decision input.
"""
from __future__ import annotations

import pytest

from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_positive_approval import _organic_approval_ticks
from tests.quant.runtime.test_tick_partial_adoption import (
    _intraday_ticks,
    _make_signal,
    _OPENED_SIZE,
)


def _types(trace) -> list[str]:
    return [type(e).__name__ for e in trace]


def _normalized(state):
    """Blank position ids for cross-run state comparison — uuids are
    identity, not behavior; every BEHAVIORAL field must still match."""
    from dataclasses import replace

    pos = state.position
    if pos is not None:
        pos = replace(pos, id="")
    return replace(
        state,
        position=pos,
        pyramids=tuple(replace(p, id="") for p in state.pyramids),
    )


def _open_long(eng):
    """Inject an open position via the established test hook (mirrors
    tests/quant/runtime/test_tick_partial_adoption._open_long)."""
    sig = _make_signal()
    position = eng._oms.submit(sig, _OPENED_SIZE)
    from quant.transitions import _position_to_state
    eng.state = eng.state.with_position(_position_to_state(position))
    eng._get_position_manager().current_position = position
    eng._entry_bar_index = 0
    return position


def test_organic_decision_trace_is_identical_across_runs():
    """An organic approval run (ticks -> analyzer -> gates -> signal ->
    position open) produces the identical event trace on a second engine."""
    ticks = list(_organic_approval_ticks())
    eng1 = QuantEngine(SyntheticGateway(ticks), "DET", interval_seconds=1)
    trace1 = eng1.run()
    eng2 = QuantEngine(SyntheticGateway(list(ticks)), "DET", interval_seconds=1)
    trace2 = eng2.run()

    assert len(trace1) == len(trace2)
    assert _types(trace1) == _types(trace2)
    for i, (a, b) in enumerate(zip(trace1, trace2)):
        assert a == b, f"event {i} diverged across runs: {a!r} != {b!r}"
    # Final folded state (behavioral fields, ids blanked) and risk book agree.
    assert _normalized(eng1.state) == _normalized(eng2.state)
    assert eng1._risk.state() == eng2._risk.state()
    # Sanity: the scenario really exercised the decision path and filled.
    assert any(
        type(e).__name__ == "SignalApproved" for e in trace1
    ), "fixture sanity: expected an organic approval"
    assert any(
        type(e).__name__ == "PositionOpened" for e in trace1
    ), "fixture sanity: expected a real fill"


def test_position_management_trace_is_identical_across_runs():
    """Tiered partial (TP1) + full close bookkeeping is trace-identical on a
    second engine given the same ticks and an equivalent injected position."""
    ticks = list(_intraday_ticks())
    eng1 = QuantEngine(SyntheticGateway(ticks), "MGMT", interval_seconds=300)
    _open_long(eng1)
    trace1 = eng1.run()
    eng2 = QuantEngine(SyntheticGateway(list(ticks)), "MGMT", interval_seconds=300)
    _open_long(eng2)
    trace2 = eng2.run()

    assert len(trace1) == len(trace2)
    assert _types(trace1) == _types(trace2)
    for i, (a, b) in enumerate(zip(trace1, trace2)):
        assert a == b, f"event {i} diverged across runs: {a!r} != {b!r}"
    assert _normalized(eng1.state) == _normalized(eng2.state)
    # The scenario must exercise a partial and a full close (sanity).
    names = _types(trace1)
    assert "PositionReduced" in names and "PositionClosed" in names