"""Hot-path trace — prove the documented flow matches the real code.

Runs the REAL QuantEngine over the organic approval fixture from
``test_positive_approval`` (synthetic ticks → analyzer → Triple-A
AGGRESSION → gates 1..4 → fill; no injected contexts or mocked pipeline)
with the opt-in hot-path tracer enabled, then asserts the diagram's order:

    tick → bar_closed → decision → fill → snapshot

If a phase is missing or out of order, the flow the code actually takes
differs from the architecture diagram. Run with ``-s`` to print the full
captured path:

    python -m pytest tests/quant/test_hotpath_trace.py -s

Live note: in a running server the ``snapshot`` record is emitted by
``multi_engine.QuantCoordinator.snapshot`` itself (every WS push); this
test emits the equivalent record after ``engine.run()`` because the
standalone engine has no coordinator pulling views.
"""

from __future__ import annotations

import pytest

from quant.events import PositionOpened
from quant.execution.risk import SessionRisk
from quant.hotpath import (
    PHASES,
    get_hotpath_tracer,
    render_records,
)
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_positive_approval import _organic_approval_ticks

TRACER = get_hotpath_tracer()
SYMBOL = "SYM"


@pytest.fixture(autouse=True)
def _isolate_tracer() -> None:
    """Every test starts and ends with an empty, disabled tracer."""
    TRACER.disable()
    TRACER.reset()
    yield
    TRACER.disable()
    TRACER.reset()


def _run_engine_with_trace() -> list:
    """Boot the real engine over the organic approval tape with tracing on.

    The snapshot record is emitted while tracing is still enabled — in the
    live server that emission happens inside
    ``multi_engine.QuantCoordinator.snapshot`` on every WS push.
    """
    SessionRisk(storage=None, symbol=SYMBOL).reset_session()
    TRACER.enable(clear=True)
    try:
        eng = QuantEngine(SyntheticGateway(_organic_approval_ticks()), SYMBOL,
                          interval_seconds=1)
        events = eng.run()
        opens = [e for e in events if isinstance(e, PositionOpened)]
        TRACER.emit(SYMBOL, "snapshot", positions=len(opens), source="harness")
    finally:
        TRACER.disable()
    return events


def test_hotpath_phases_present_in_real_flow() -> None:
    events = _run_engine_with_trace()
    assert any(isinstance(e, PositionOpened) for e in events), (
        "organic fixture must open a position for the trace test to be meaningful"
    )

    counts = TRACER.counts(SYMBOL)
    for phase in ("tick", "bar_closed", "decision", "fill", "snapshot"):
        assert counts[phase] > 0, (
            f"phase {phase!r} never crossed the real hot path — the diagram "
            f"claims it happens; the code disagrees (counts={counts})"
        )
    assert counts["fill"] >= 1
    assert counts["snapshot"] == 1


def test_hotpath_phase_order_matches_diagram() -> None:
    _run_engine_with_trace()
    recs = TRACER.records(SYMBOL)
    seq = {p: [r.seq for r in recs if r.phase == p] for p in PHASES}

    first_tick = min(seq["tick"])
    first_bar = min(seq["bar_closed"])
    first_decision = min(seq["decision"])
    assert first_tick < first_bar < first_decision, (
        "tick → bar_closed → decision violated: "
        f"tick@{first_tick} bar@{first_bar} decision@{first_decision}"
    )

    # The approved decision must precede the fill it caused.
    approved = [r for r in recs if r.phase == "decision"
                and r.fields.get("approved") is True
                and r.fields.get("signal")]
    assert approved, "no approved decision with signal in the trace"
    fill_seq = min(seq["fill"])
    assert max(r.seq for r in approved) < fill_seq, (
        "fill preceded its approving decision — the execution path is not "
        "downstream of the gate pipeline"
    )

    # The snapshot (WS view) is composed after the run's final fill.
    assert max(seq["fill"]) < min(seq["snapshot"]), (
        "snapshot arrived before the final fill"
    )


def test_hotpath_disabled_is_zero_cost_noop() -> None:
    TRACER.disable()
    TRACER.emit("ANY", "tick", price=1.0)
    TRACER.emit("ANY", "decision", approved=True)
    assert TRACER.records() == [], "disabled tracer must not record anything"


def test_hotpath_report_renders() -> None:
    """Print the canonical diagram path — run with -s to eyeball it.

    Full rows for: first tick/bar/decision, every approved decision,
    every fill, and the snapshot. (The plain render truncates at 120 rows
    long before the fill on a ~600-record run.)
    """
    _run_engine_with_trace()
    recs = TRACER.records(SYMBOL)
    counts = TRACER.counts(SYMBOL)
    by_seq = {r.seq: r for r in recs}
    first = {p: next((r for r in recs if r.phase == p), None) for p in PHASES}
    interesting = [
        r for r in recs
        if r.phase == "fill"
        or r.phase == "snapshot"
        or (r.phase == "decision" and r.fields.get("approved") is True)
    ]
    for p in ("tick", "bar_closed", "decision"):
        if first[p] is not None:
            interesting.append(first[p])
    rows = [by_seq[r.seq] for r in sorted(interesting, key=lambda r: r.seq)]
    lines = [
        f"hot-path trace for {SYMBOL}: " + " ".join(
            f"{k}={v}" for k, v in counts.items()
        ),
        render_records(rows, include_ticks=True),
    ]
    print("\n" + "\n".join(lines))
    assert rows
    assert counts["fill"] >= 1 and counts["snapshot"] == 1


# ---------------------------------------------------------------------------
# B7 passivity: the hot-path trace is a passive EventBus subscriber owned by
# quant.hotpath. Enabling it must not change the engine's event stream
# (trace-on == trace-off), every event-derived record must carry the event's
# correlation id, ring overflow must be visible, and a trace failure must
# never stop the engine.
# ---------------------------------------------------------------------------

_RING_CAPACITY = 8192  # HotPathTracer default ring (see _DEFAULT_RING)


def _run_engine_trace_off() -> list:
    TRACER.disable()
    eng = QuantEngine(SyntheticGateway(_organic_approval_ticks()), SYMBOL,
                      interval_seconds=1)
    return eng.run()


def test_trace_on_event_stream_equals_trace_off() -> None:
    """The deletion gate for B7: a trace-enabled run must emit byte-identical
    events to a trace-disabled run (ignoring volatile engine ids)."""
    from tests.quant.certification import trace_compare

    # Engine Signals now carry a stable signal_id (uuid) — also volatile.
    trace_compare._VOLATILE_KEYS = trace_compare._VOLATILE_KEYS | {"signal_id"}
    from tests.quant.certification.trace_compare import first_divergence

    events_off = _run_engine_trace_off()
    TRACER.enable(clear=True)
    try:
        events_on = QuantEngine(
            SyntheticGateway(_organic_approval_ticks()), SYMBOL,
            interval_seconds=1,
        ).run()
    finally:
        TRACER.disable()

    divergence = first_divergence(events_off, events_on)
    assert divergence is None, (
        "enabling the passive trace changed the engine's event stream "
        f"(B7 passivity violated): {divergence}"
    )


def test_phase_records_carry_event_correlation_id() -> None:
    events = _run_engine_with_trace()
    assert any(isinstance(e, PositionOpened) for e in events)

    event_corrs = {e.correlation_id for e in events}
    phased = [
        r for r in TRACER.records(SYMBOL)
        if r.phase in ("bar_closed", "decision", "fill")
    ]
    assert phased, "no event-derived phase records were captured by the subscriber"
    for r in phased:
        corr = r.fields.get("correlation_id", "")
        assert isinstance(corr, str) and corr, (
            f"{r.phase} record is missing the event correlation_id"
        )
    assert {r.fields["correlation_id"] for r in phased} <= event_corrs, (
        "phase records must reference correlation ids of real emitted events"
    )


def test_ring_overflow_is_visible() -> None:
    """When the ring buffer overflows, evictions are counted, not silent."""
    total = _RING_CAPACITY + 900
    TRACER.enable(clear=True)
    try:
        for i in range(total):
            TRACER.emit(f"S{i % 7}", "tick", n=i)
    finally:
        TRACER.disable()

    assert len(TRACER.records()) <= _RING_CAPACITY
    assert TRACER.dropped == total - _RING_CAPACITY, (
        "ring evictions must be observable through tracer.dropped"
    )


def test_trace_failure_does_not_stop_engine(monkeypatch) -> None:
    """Every trace emit raises — the engine (and its event stream) survives.

    Event phases run through the bus's per-handler isolation plus
    try_emit; tick ingress and the snapshot call-site use try_emit, so a
    trace-internal failure can never stop trading or the WS push.
    """
    import logging
    import types

    # The failure path logs a traceback per phase crossing (thousands) —
    # silence it: the point is that trading continues, not the log volume.
    monkeypatch.setattr(logging.getLogger("quant.hotpath"), "disabled", True)

    def _boom(self, symbol, phase, **fields):
        raise RuntimeError(f"trace exploded on {phase}")

    monkeypatch.setattr(TRACER, "emit", types.MethodType(_boom, TRACER))
    TRACER.enable(clear=True)
    try:
        eng = QuantEngine(SyntheticGateway(_organic_approval_ticks()), SYMBOL,
                          interval_seconds=1)
        events = eng.run()
    finally:
        TRACER.disable()

    assert any(isinstance(e, PositionOpened) for e in events), (
        "engine must keep trading when the trace subscriber fails"
    )
    assert TRACER.records() == []  # nothing recorded — but nothing crashed
