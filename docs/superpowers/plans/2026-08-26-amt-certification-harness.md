# AMT Certification Harness & Critical Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert "determinism is designed in" into "determinism is measured and gated": payload-exact replay proof over recorded journals, audit events for every stop move, and closure of the five verified money-critical defects (pyramid ghosting in live, evidence inflation, silent stop moves, empty rejection reasons, threshold drift).

**Architecture:** Everything lands in the existing pure-Python `quant/` core plus a new `tests/quant/certification/` package. Replay reuses the proven composition (`SyntheticGateway` → `QuantEngine.run()`); no new framework, no new dependencies. Audit events ride the existing typed EventBus and fsync JSONL journal.

**Tech Stack:** Python 3.13 stdlib only (dataclasses, json, argparse). pytest. Makefile.

## Global Constraints

- `quant/` stays stdlib-only with zero `backend/` imports (architecture invariant, enforced by tests/architecture).
- Run quant/root tests with `PYTHONPATH=backend:.` (Makefile convention — some tests import `backend.tests.helpers`).
- Conventional commits (`feat:`, `fix:`, `test:`, `chore:`).
- Deliberate ceilings get a `# ponytail:` comment naming the ceiling and upgrade path.
- No new pip/npm dependencies.
- Every behavior change keeps the two-engine payload-exact trace identical unless the change IS the intended behavior fix (then the diff is captured in the certification results doc).

## File Structure

```
tests/quant/certification/__init__.py          # package marker
tests/quant/certification/trace_compare.py     # normalize + deep-compare helpers
tests/quant/certification/journal_ticks.py     # journal JSONL -> synthetic Tick list
tests/quant/certification/journal_replay.py    # 2-engine determinism CLI (replay driver)
tests/quant/certification/run_battery.py       # S9/S11/S13 battery -> results md
tests/quant/certification/test_trace_compare.py
tests/quant/certification/test_journal_ticks.py
tests/quant/certification/test_live_pyramids_disabled.py
tests/quant/certification/test_base_sl_ratchet.py
tests/quant/certification/test_signal_drop_reasons.py
quant/events.py                                # + StopMoved event
quant/execution/exits.py                       # + stop_state() accessor
quant/execution/oms.py                         # PaperOMS.supports_pyramids = True
quant/execution/live_oms.py                    # LiveOMS.supports_pyramids = False
quant/position_manager.py                      # pyramid guard, SL ratchet, risk reservation, StopMoved emits
quant/runtime.py                               # journal subscribes StopMoved; adopt base_override; drop dead pyramid-risk block
quant/decision/context_builder.py              # acceptance sourced from real flags
quant/decision/signal_builder.py               # + build_or_reason()
quant/decision/decision_service.py             # SIGNAL_BUILDER block reasons
quant/amt/market/state_engine.py               # BALANCE_RATIO_THRESHOLD used
quant/session_gates.py                         # parse_contract_expiry(today=None)
Makefile                                       # + parity target
docs/reviews/certification-results-<date>.md   # battery output (generated)
```

---

### Task 1: Payload-exact trace comparison

**Files:**
- Create: `tests/quant/certification/__init__.py` (empty)
- Create: `tests/quant/certification/trace_compare.py`
- Create: `tests/quant/certification/test_trace_compare.py`
- Modify: `tests/quant/test_golden_tape.py:26-51`

**Interfaces:**
- Produces: `normalize(obj) -> obj` (recursive dict/list walk dropping volatile keys), `traces_equal(a: list, b: list) -> bool`, `first_divergence(a, b) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/certification/test_trace_compare.py
"""Payload-exact trace comparison for replay determinism."""

from quant.events import BarClosed, PositionOpened
from quant.execution.order import Order, Position
from quant.decision.signal_builder import Signal
from tests.quant.certification.trace_compare import normalize, traces_equal


def _evt(event_id: str, corr: str) -> BarClosed:
    e = BarClosed(symbol="X", time="100", bar=None)
    object.__setattr__(e, "event_id", event_id)
    object.__setattr__(e, "correlation_id", corr)
    return e


def test_normalize_strips_volatile_ids():
    row = {"type": "BarClosed", "event_id": "7", "correlation_id": "u",
           "symbol": "X", "time": "100"}
    assert normalize(row) == {"type": "BarClosed", "symbol": "X", "time": "100"}


def test_normalize_strips_nested_position_uuid():
    sig = Signal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0,
                 rr=2.0, model_label="T", symbol="X", timestamp="100")
    pos = Position(order=Order(signal=sig, quantity=10), open_price=100.0,
                   open_time="100", size=10)
    row = {"type": "PositionOpened", "position": pos.__dict__}
    norm = normalize(row)
    assert "_id" not in norm["position"]


def test_traces_equal_ignores_volatile_fields():
    a = [_evt("1", "ua"), _evt("2", "ub")]
    b = [_evt("9", "uz"), _evt("8", "uy")]
    assert traces_equal(a, b)


def test_traces_equal_detects_payload_drift():
    a = [_evt("1", "u")]
    b_evt = _evt("9", "u")
    b = [type(b_evt)(symbol="X", time="200", bar=None)]
    assert not traces_equal(a, b)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_trace_compare.py -q`
Expected: FAIL — `ModuleNotFoundError: tests.quant.certification.trace_compare`

- [ ] **Step 3: Implement**

```python
# tests/quant/certification/trace_compare.py
"""Normalize event payloads and compare traces byte-exactly.

Volatile keys stripped recursively: engine-assigned ids that legitimately
differ between two independent engines (event counter, correlation UUID,
position UUIDs). Everything else must match exactly.
"""

from __future__ import annotations

_VOLATILE_KEYS = frozenset({"event_id", "correlation_id", "_id"})


def normalize(obj):
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items() if k not in _VOLATILE_KEYS}
    if isinstance(obj, (list, tuple)):
        return type(obj)(normalize(v) for v in obj) if isinstance(obj, tuple) else [
            normalize(v) for v in obj
        ]
    return obj


def _as_dict(evt) -> dict:
    d = evt.__class__.__name__
    from dataclasses import asdict
    return {"__event__": d, **normalize(asdict(evt))}


def traces_equal(a: list, b: list) -> bool:
    return first_divergence(a, b) is None


def first_divergence(a: list, b: list) -> str | None:
    da = [_as_dict(e) for e in a]
    db = [_as_dict(e) for e in b]
    for i, (x, y) in enumerate(zip(da, db)):
        if x != y:
            keys = set(x) | set(y)
            diff = {k for k in keys if x.get(k) != y.get(k)}
            return f"index={i} type={x.get('__event__')} differing_keys={sorted(diff)}"
    if len(da) != len(db):
        return f"length mismatch: {len(da)} vs {len(db)}"
    return None
```

Note: events are compared via `dataclasses.asdict()` so nested frozen dataclasses (bars, positions, signals) flatten automatically. Events passed to `traces_equal` are Event instances (the in-memory `QuantEngine.run()` trace); journal dicts go through `normalize` directly.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_trace_compare.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Upgrade golden tape to payload-exact**

Replace the assertion block in `tests/quant/test_golden_tape.py::test_golden_tape_event_sequence_determinism` (lines 41–51):

```python
    from tests.quant.certification.trace_compare import traces_equal

    assert len(sync_trace1) == len(sync_trace2)
    assert len(sync_trace1) > 0
    assert "BarClosed" in [e.__class__.__name__ for e in sync_trace1]
    assert "DecisionProduced" in [e.__class__.__name__ for e in sync_trace1]
    assert traces_equal(sync_trace1, sync_trace2), (
        "two engines diverged on payload content"
    )
```

- [ ] **Step 6: Run golden tape**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_golden_tape.py -q`
Expected: PASS. If RED here, STOP — you found real cross-engine nondeterminism; capture the `first_divergence` output as a defect entry and fix root cause before continuing.

- [ ] **Step 7: Commit**

```bash
git add tests/quant/certification tests/quant/test_golden_tape.py
git commit -m "test: payload-exact golden tape via trace_compare normalization"
```

---

### Task 2: Journal → ticks replay driver

**Files:**
- Create: `tests/quant/certification/journal_ticks.py`
- Create: `tests/quant/certification/journal_replay.py`
- Create: `tests/quant/certification/test_journal_ticks.py`

**Interfaces:**
- Consumes: `Journal(path).replay() -> list[dict]` (quant/persistence.py), `Tick(time, price, volume, buy_volume, sell_volume, oi)` (quant/brokers/gateway.py), `SyntheticGateway(ticks)` (tests/helpers/synthetic.py), `QuantEngine(gateway, symbol, interval_seconds)` (quant/runtime.py).
- Produces: `bars_from_journal(rows) -> list[tuple[int, dict]]` (interval, bar-dict pairs), `ticks_from_bars(bars, interval) -> list[Tick]`, `replay_journal(path) -> tuple[list, list]` (two engine traces).

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/certification/test_journal_ticks.py
"""Journal BarClosed rows -> deterministic synthetic ticks."""

from tests.quant.certification.journal_ticks import (
    bars_from_journal, ticks_from_bars,
)

BAR_TIME = 1756200000  # any epoch-second aligned window


def _row(bar_time, o, h, l, c, vol, delta=0.0):
    buy = (vol + delta) / 2
    return {
        "type": "BarClosed", "symbol": "X", "time": str(bar_time),
        "bar": {"time": str(bar_time), "open": o, "high": h, "low": l,
                "close": c, "volume": vol, "buy_volume": buy,
                "sell_volume": vol - buy, "delta": delta, "oi": 0.0,
                "vwap": c},
    }


def test_bars_from_journal_filters_and_infers_interval():
    rows = [{"type": "RiskUpdated"}, _row(BAR_TIME, 1, 2, 0.5, 1.5, 400),
            _row(BAR_TIME + 60, 1.5, 2.5, 1, 2, 400)]
    interval, bars = bars_from_journal(rows)
    assert interval == 60
    assert len(bars) == 2
    assert bars[0]["open"] == 1


def test_ticks_reproduce_ohlc_through_aggregator():
    from copy import copy
    from quant.aggregator import BarAggregator
    from quant.brokers.gateway import Tick
    interval, bars = bars_from_journal(
        [_row(BAR_TIME, 100.0, 105.0, 98.0, 103.0, 400.0, delta=40.0)])
    ticks = ticks_from_bars([bars[0]], interval)
    assert len(ticks) == 4
    # The aggregator holds the forming bar until a tick arrives from a LATER
    # window — append one sentinel tick from the next bucket to force close.
    flush = copy(ticks[-1])
    object.__setattr__(flush, "time", str(int(float(ticks[-1].time)) + interval))
    agg = BarAggregator(interval_seconds=interval)
    closed = None
    for t in [*ticks, flush]:
        closed = agg.add_tick(t) or closed
    assert closed is not None
    assert (closed.open, closed.high, closed.low, closed.close) == \
        (100.0, 105.0, 98.0, 103.0)
    assert abs(closed.volume - 500.0) < 1e-6  # 4 bar ticks + sentinel volume
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_journal_ticks.py -q`
Expected: FAIL — module missing

- [ ] **Step 3: Implement**

```python
# tests/quant/certification/journal_ticks.py
"""Rebuild a deterministic tick stream from journaled BarClosed rows.

Each recorded bar becomes 4 ticks [O, H, L, C]; volume/buy/sell split evenly.
The aggregator reproduces the exact OHLCV because all ticks share one
interval bucket. # ponytail: bar.vwap is NOT reproduced exactly (equal-volume
split vs live weighting) — replay x2 determinism is exact, live-vs-replay
parity needs tick-grade journals. Upgrade path: record raw ticks in live mode.
"""

from __future__ import annotations

from quant.brokers.gateway import Tick

_EPOCH_FLOOR = 946684800


def bars_from_journal(rows: list[dict]) -> tuple[int, list[dict]]:
    """Return (inferred_interval_seconds, bar_dicts) from journal rows."""
    bars = [r["bar"] for r in rows
            if r.get("type") == "BarClosed" and isinstance(r.get("bar"), dict)]
    if len(bars) < 2:
        raise ValueError("journal has fewer than 2 BarClosed rows")
    times = [int(float(b["time"])) for b in bars[:5]]
    deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    interval = min(deltas) if deltas else 60
    return int(interval), bars


def ticks_from_bars(bars: list[dict], interval: int) -> list[Tick]:
    ticks: list[Tick] = []
    for b in bars:
        base = int(float(b["time"]))
        if base < _EPOCH_FLOOR:
            raise ValueError(f"non-epoch bar time {b['time']!r}")
        vol = float(b.get("volume") or 0.0)
        delta = float(b.get("delta") or 0.0)
        buy = (vol + delta) / 2.0
        sell = vol - buy
        qv, qb, qs = vol / 4.0, buy / 4.0, sell / 4.0
        for i, price in enumerate(
            (float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]))
        ):
            ticks.append(Tick(time=str(base + i + 1), price=price, volume=qv,
                              buy_volume=qb, sell_volume=qs,
                              oi=float(b.get("oi") or 0.0)))
    return ticks
```

The flush-tick trick in the test: the aggregator holds the forming bar until a tick arrives from a LATER window, so append one sentinel tick at `base + interval - 1`… which is still the same bucket. Correction — to force the close, run the four ticks then one tick from the NEXT window:

```python
# replace _flush_tick body in the test with:
    t = copy(last_tick)
    object.__setattr__(t, "time", str(int(float(last_tick.time)) + interval))
```

(Use this version; the `-1` variant would never close the bar.)

```python
# tests/quant/certification/journal_replay.py
"""Replay a recorded journal through TWO fresh engines; demand payload-exact
trace identity. Exit 0 = zero divergence.

Usage: PYTHONPATH=backend:. python -m tests.quant.certification.journal_replay \
           backend/journals/<file>.jsonl [--interval SEC]

# ponytail: proves ENGINE determinism over recorded bars. It does not yet
# prove live-parity (depth snapshots + tick-grade VWAP absent). See
# journal_ticks.py ceiling note.
"""
from __future__ import annotations

import argparse
import sys

from quant.execution.risk import SessionRisk
from quant.persistence import Journal
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.certification.journal_ticks import (
    bars_from_journal, ticks_from_bars,
)
from tests.quant.certification.trace_compare import first_divergence


def load_ticks(path: str, interval: int | None = None) -> tuple[list, int]:
    """Return (synthetic_ticks, interval_seconds) for a journal file."""
    rows = Journal(path).replay()
    inf, bars = bars_from_journal(rows)
    iv = int(interval or inf)
    return ticks_from_bars(bars, iv), iv


def replay_twice(ticks: list, symbol: str, interval: int):
    SessionRisk(storage=None, symbol=f"{symbol}_R1").reset_session()
    eng1 = QuantEngine(SyntheticGateway(list(ticks)), f"{symbol}_R1",
                       interval_seconds=interval)
    trace1 = eng1.run()
    SessionRisk(storage=None, symbol=f"{symbol}_R2").reset_session()
    eng2 = QuantEngine(SyntheticGateway(list(ticks)), f"{symbol}_R2",
                       interval_seconds=interval)
    trace2 = eng2.run()
    return trace1, trace2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("journal")
    ap.add_argument("--interval", type=int, default=None)
    args = ap.parse_args(argv)
    ticks, iv = load_ticks(args.journal, args.interval)
    print(f"{len(ticks)} synthetic ticks from {args.journal} (interval={iv}s)")
    t1, t2 = replay_twice(ticks, "CERT", iv)
    div = first_divergence(t1, t2)
    if div:
        print(f"DIVERGENCE: {div}")
        return 1
    print(f"OK: {len(t1)} events, payload-exact across 2 engines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Implementation notes: `SessionRisk.reset_session()` clears persisted state like the golden tape tests do; symbols differ per engine so kv keys cannot collide. `bars_from_journal` raises on journals with fewer than 2 BarClosed rows.

- [ ] **Step 4: Run unit tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_journal_ticks.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Smoke against a real recorded day**

Run: `ls backend/journals/*.jsonl | head -3` then
`PYTHONPATH=backend:. .venv/bin/python -m tests.quant.certification.journal_replay "backend/journals/<one-file>.jsonl"`
Expected: `OK: N events, payload-exact across 2 engines`. If DIVERGENCE, capture output — that is a certification finding, not a harness bug (verify the divergence is not caused by wall-clock keys before treating it as such).

- [ ] **Step 6: Commit**

```bash
git add tests/quant/certification
git commit -m "feat: journal->tick replay driver with 2-engine payload-exact determinism check"
```

---

### Task 3: StopMoved audit event

**Files:**
- Modify: `quant/events.py` (after `OrderFilled`, ~line 113)
- Modify: `quant/execution/exits.py` (new accessor after `pop_trail`, ~line 77)
- Modify: `quant/position_manager.py` (manage_exit, lines 95-143 region)
- Modify: `quant/runtime.py:249-253` (journal subscription tuple)
- Test: `tests/quant/execution/test_exits.py` (extend)

**Interfaces:**
- Produces: `StopMoved(Event)` frozen dataclass with `old_sl: float`, `new_sl: float`, `reason: str`; `ExitEngine.stop_state(position) -> tuple[float | None, float | None]` (breakeven floor, trail stop).

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/execution/test_exits.py` (reuse that file's existing fixtures/helpers for building positions — mirror their setup):

```python
def test_breakeven_arm_emits_stopped_moved(make_position, collect_events):
    """BE floor arming publishes StopMoved with reason BREAKEVEN_ARMED."""
    # arrange: position in profit >= 0.8R on a rising bar (use the same
    # position builder the trailing tests in this file already use)
    pos = make_position(entry=100.0, sl=98.0, size=10)
    engine = ExitEngine()
    dto = {"cvdSlope": 0.0}
    dec = engine.evaluate(pos, dto, bar_high=101.0, bar_low=99.0,
                          bar_close=100.8)
    assert not dec.should_exit
    be, trail = engine.stop_state(pos)
    assert be == 100.0          # BE floor armed at entry
    assert trail is None
```

Adapt to the file's actual fixture names; if none exist, construct `Position(Order(Signal(...)))` inline exactly like neighboring tests do.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exits.py::test_breakeven_arm_emits_stopped_moved -q`
Expected: FAIL — `AttributeError: 'ExitEngine' object has no attribute 'stop_state'`

- [ ] **Step 3: Implement accessor**

In `quant/execution/exits.py` after `pop_trail`:

```python
    def stop_state(self, position: Position) -> tuple[float | None, float | None]:
        """Current (breakeven_floor, trail_stop) for a position."""
        tr = self._trail.get(position._id)
        return self._breakeven.get(position._id), (tr.stop if tr and tr.active else None)
```

- [ ] **Step 4: Add the event**

In `quant/events.py` after `AgentDecisionProduced` (or after `OrderFilled`):

```python
@dataclass(frozen=True)
class StopMoved(Event):
    """Audit trail: the protective stop level changed (BE arm, trail ratchet,
    pyramid ratchet). Emitted at the moment of change, not just when hit."""
    old_sl: float = 0.0
    new_sl: float = 0.0
    reason: str = ""   # BREAKEVEN_ARMED / TRAIL_RATCHET / PYRAMID_RATCHET
```

- [ ] **Step 5: Emit from PositionManager.manage_exit**

In `quant/position_manager.py`: import `StopMoved` alongside the other event imports (line 19). Inside `manage_exit`, wrap the evaluate call (lines 133-143):

```python
            prev_be, prev_trail = self._exits.stop_state(position)
            exit_dec = self._exits.evaluate(
                # ... unchanged arguments ...
            )
            if not exit_dec.should_exit:
                be_floor, trail_stop = self._exits.stop_state(position)
                sig_sl = float(position.order.signal.sl)
                long = position.size > 0
                if be_floor is not None and prev_be is None:
                    self._emit(StopMoved(symbol=self.symbol, time=bar.time,
                                         old_sl=sig_sl, new_sl=float(be_floor),
                                         reason="BREAKEVEN_ARMED"))
                tightened = (
                    trail_stop is not None
                    and (prev_trail is None
                         or (trail_stop > prev_trail if long else trail_stop < prev_trail))
                )
                if tightened:
                    self._emit(StopMoved(symbol=self.symbol, time=bar.time,
                                         old_sl=float(prev_trail if prev_trail is not None else sig_sl),
                                         new_sl=float(trail_stop),
                                         reason="TRAIL_RATCHET"))
```

- [ ] **Step 6: Persist it**

In `quant/runtime.py:249-253` add `StopMoved` to the subscription tuple:

```python
            for evt_type in (BarClosed, DecisionProduced,
                            SignalApproved, PositionOpened, PositionClosed,
                            PositionReduced,
                            RiskUpdated, DepthUpdated, AmtUpdated,
                            OrderSubmitted, OrderFilled, StopMoved):
```

Import `StopMoved` in runtime's existing event import block.

- [ ] **Step 7: Verify**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/ tests/quant/test_golden_tape.py -q`
Expected: PASS. Golden tape stays green (no trades fire in that fixture; no StopMoved emitted — emission happens only around live exit evaluation with changing stops).

Then verify end-to-end emission once via the Task 2 driver on a journal day that contains trailing activity, checking the new trace contains `StopMoved` rows:

Run: `PYTHONPATH=backend:. .venv/bin/python -c "from tests.quant.certification.journal_replay import load_ticks, replay_twice; ticks,iv=load_ticks('backend/journals/<file>.jsonl'); t1,_=replay_twice(ticks,'SMK',iv); print(sum(1 for e in t1 if type(e).__name__=='StopMoved'))"`

- [ ] **Step 8: Commit**

```bash
git add quant/events.py quant/execution/exits.py quant/position_manager.py quant/runtime.py tests/quant/execution/test_exits.py
git commit -m "feat: StopMoved audit event on breakeven-arm and trail ratchet"
```

---

### Task 4: Evidence inflation fix — acceptance must be earned

**Files:**
- Modify: `quant/decision/context_builder.py:169-174`
- Test: `tests/quant/decision/test_context_builder_behavior.py` (extend)

**Interfaces:** unchanged. DTO keys `acceptanceAbove` / `acceptanceBelow` are already produced by `quant/amt/dto.py:104-105`.

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_aggression_without_acceptance_is_not_triple_a_evidence():
    """AGGRESSION phase alone must NOT fabricate acceptance=True.

    Certification defect: SetupEvidence claimed acceptance unconditionally
    whenever tripleAPhase==AGGRESSION, collapsing Triple-A completeness to
    'machine says AGGRESSION'. Acceptance must come from the A/R engine.
    """
    from quant.decision.context_builder import DecisionContextBuilder
    b = DecisionContextBuilder()
    ev = b._build_setup_evidence(
        {"tripleAPhase": "AGGRESSION", "tripleASignal": "LONG",
         "cvdSlope": 0.6, "acceptanceAbove": False},
        agent_direction="LONG", nearest_leg_lvn=0.0)
    # Either falls through to a different setup or returns evidence with
    # acceptance False — never a TRIPLE_A claiming acceptance.
    assert not (ev and ev.setup_type == "TRIPLE_A" and ev.acceptance)


def test_aggression_with_real_acceptance_keeps_triple_a():
    from quant.decision.context_builder import DecisionContextBuilder
    b = DecisionContextBuilder()
    ev = b._build_setup_evidence(
        {"tripleAPhase": "AGGRESSION", "tripleASignal": "LONG",
         "cvdSlope": 0.6, "acceptanceAbove": True},
        agent_direction="LONG", nearest_leg_lvn=0.0)
    assert ev is not None and ev.setup_type == "TRIPLE_A"
    assert ev.acceptance and ev.cvd_agrees
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_context_builder_behavior.py -q`
Expected: first new test FAILS (currently returns acceptance=True)

- [ ] **Step 3: Fix**

Replace `context_builder.py:169-174`:

```python
        if triple_phase == "AGGRESSION" and (
            triple_signal in ("LONG", "SHORT") or agent_direction in ("LONG", "SHORT")
        ):
            direction = triple_signal or agent_direction
            accepted = bool(
                amt_dto.get("acceptanceAbove") if direction == "LONG"
                else amt_dto.get("acceptanceBelow")
            )
            if accepted:
                return SetupEvidence(
                    setup_type="TRIPLE_A", direction=direction,
                    absorption=True, accumulation=True, aggression=True,
                    acceptance=True,
                    cvd_agrees=cvd_agrees,
                )
            # No A/R-engine acceptance: fall through — later branches may
            # qualify a different setup; we never fabricate acceptance.
```

- [ ] **Step 4: Run decision suite**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/system/ -q`
Expected: PASS except tests that ASSERTED the inflated behavior — update those deliberately (they encode the bug). For each updated test, note the name in the commit message.

- [ ] **Step 5: Commit**

```bash
git add quant/decision/context_builder.py tests/quant/decision/test_context_builder_behavior.py
git commit -m "fix: Triple-A acceptance flag sourced from A/R engine, never assumed"
```

---

### Task 5: Signal-builder drops surface reasons

**Files:**
- Modify: `quant/decision/signal_builder.py` (build, lines 72-133)
- Modify: `quant/decision/decision_service.py:79-87`
- Test: create `tests/quant/certification/test_signal_drop_reasons.py`

**Interfaces:**
- Produces: `SignalBuilder.build_or_reason(ctx, pipeline_results, model_label) -> tuple[Signal | None, str]`; `build()` delegates and keeps returning `Signal | None` (zero churn for other callers).

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/certification/test_signal_drop_reasons.py
"""All-gates-pass-but-builder-drops must carry an explainable reason."""

from quant.decision.signal_builder import SignalBuilder
from quant.decision.decision_service import DecisionService
# Build ctx via the same helper test_decision_service.py uses for approved
# decisions (import or copy its minimal context factory).


def test_thin_stop_drop_reports_reason(minimal_ctx_factory):
    ctx = minimal_ctx_factory(entry=100.0, anchor_distance_pct=0.01)  # razor stop
    sig, why = SignalBuilder().build_or_reason(ctx, [])
    assert sig is None
    assert why == "thin stop"


def test_inverted_levels_drop_reports_reason(minimal_ctx_factory):
    ctx = minimal_ctx_factory(inverted=True)
    sig, why = SignalBuilder().build_or_reason(ctx, [])
    assert sig is None
    assert why.startswith("inverted signal")


def test_service_block_reason_includes_builder_drop(minimal_ctx_factory):
    """GATE_REJECTED with empty block_reasons was unauditable (cert E5)."""
    svc = DecisionService()
    ctx = minimal_ctx_factory(entry=100.0, anchor_distance_pct=0.01)
    # Force all gates passed by using the same gate-passing context the
    # approval tests use; only the builder drop differs.
    dec = svc.evaluate(ctx)
    assert dec.reason == "GATE_REJECTED"
    assert any(r.startswith("SIGNAL_BUILDER:") for r in dec.block_reasons)
```

Reuse `minimal_ctx_factory` patterns from `tests/quant/decision/test_decision_service.py` — import its builder if importable, else replicate its construction inline (copy, do not reference).

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_signal_drop_reasons.py -q`
Expected: FAIL — no `build_or_reason`

- [ ] **Step 3: Implement**

Rename `build` internals: `build_or_reason(self, ctx, pipeline_results, model_label="Triple-A") -> tuple[Signal | None, str]`. Same body; every early `return None` becomes `return None, "<reason>"`:

- gates failed → `None, "gates failed"` (line 78-79; unreachable via service, kept for direct callers)
- no direction → `None, "no direction"`
- no bar → `None, "no bar"`
- inverted (keep the warning log at lines 110-114, then) → `None, f"inverted signal: direction={direction} entry={entry} sl={sl} tp={tp}"`
- thin stop → `None, "thin stop"`
- success → `signal, ""`

Then:

```python
    def build(self, ctx, pipeline_results, model_label="Triple-A"):
        """Back-compat wrapper — prefer build_or_reason for auditability."""
        sig, _why = self.build_or_reason(ctx, pipeline_results, model_label)
        return sig
```

In `decision_service.py:79-87`:

```python
            sig, drop_why = SignalBuilder().build_or_reason(ctx, results, model_label=label)
            if sig is not None:
                return QuantDecision(True, sig, label, "", results, model_label=label)
            return QuantDecision(
                False, None, "GATE_REJECTED", "", results,
                blocked + (f"SIGNAL_BUILDER: {drop_why}",),
            )
```

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/quant/certification/ -q`
Expected: PASS. Existing `test_signal_builder_guards.py` assertions on `build()` stay green via the wrapper.

- [ ] **Step 5: Commit**

```bash
git add quant/decision/signal_builder.py quant/decision/decision_service.py tests/quant/certification/test_signal_drop_reasons.py
git commit -m "fix: signal-builder drops carry SIGNAL_BUILDER reasons into block_reasons"
```

---

### Task 6: Balance-threshold unification

**Files:**
- Modify: `quant/amt/market/state_engine.py:72,78`
- Test: `tests/quant/amt/` — locate the state-engine test file with glob (`tests/**/test_state_engine*.py` or similar); extend it.

- [ ] **Step 1: Write the failing test**

```python
def test_balance_ratio_threshold_matches_named_constant():
    """Cert defect: BALANCE_RATIO_THRESHOLD=0.55 imported but literal 0.5 used."""
    from quant.contracts.constants import BALANCE_RATIO_THRESHOLD
    from quant.amt.market.state_engine import detect_market_state
    # balance_ratio between 0.5 and 0.55 must classify IMBALANCED per the
    # named constant, not slip through as BALANCED via the stale literal.
    res = detect_market_state(
        price=100.0, poc=100.0, vah=101.0, val=99.0, tick_size=0.05,
        has_displacement=False, has_acceptance=True,
        balance_ratio=BALANCE_RATIO_THRESHOLD - 0.001)
    assert res.state.value == "IMBALANCED"
    assert f"({BALANCE_RATIO_THRESHOLD - 0.001:.2f})" in res.trigger
```

(MarketState enum value spelling: check `quant/contracts/enums.py` — assert against the enum member, not a raw string, if that is the file's style.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest <that test file> -q`
Expected: FAIL — classified BALANCED

- [ ] **Step 3: Fix**

In `state_engine.py`, replace both literals at lines 72 and 78:

```python
    if has_displacement or not inside_session_va or balance_ratio < BALANCE_RATIO_THRESHOLD:
        ...
        if balance_ratio < BALANCE_RATIO_THRESHOLD:
```

(`BALANCE_RATIO_THRESHOLD` is already imported at lines 21-25.)

- [ ] **Step 4: Verify + commit**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/ -q -k "state or golden"`
Expected: PASS

```bash
git add quant/amt/market/state_engine.py tests/quant/
git commit -m "fix: use BALANCE_RATIO_THRESHOLD constant instead of stale 0.5 literal"
```

---

### Task 7: Kill-switch — pyramids never execute under LiveOMS

**Files:**
- Modify: `quant/execution/oms.py` (PaperOMS class head)
- Modify: `quant/execution/live_oms.py` (LiveOMS class head)
- Modify: `quant/position_manager.py` (top of `check_pyramid`, line 223)
- Test: create `tests/quant/certification/test_live_pyramids_disabled.py`

**Interfaces:**
- Produces: class attribute `supports_pyramids: bool` on both IOMS implementations; PositionManager consults it via `getattr` (default False = fail-safe).

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/certification/test_live_pyramids_disabled.py
"""Cert defect E9: LiveOMS.add_pyramid creates ghost positions — nothing ever
submits a broker order for pyramids. Until that path exists end-to-end,
pyramids MUST be impossible under LiveOMS."""

from unittest.mock import MagicMock

from quant.position_manager import PositionManager


def _pm_with(oms):
    return PositionManager(
        oms=oms, exits=MagicMock(is_risk_free=lambda p: True),
        risk=MagicMock(can_trade=lambda: (True, "")),
        emit_fn=lambda e: None, symbol="X", market="NSE",
        contract_expiry=None, tick_size=0.05,
    )


def _bar(open_=100.0, close=100.0):
    from quant.bars import Bar
    return Bar(time="1756200000", open=open_, high=max(open_, close) + 5,
               low=min(open_, close) - 5, close=close, volume=1000)


def _dto():
    return {"legLvn": 100.0, "absorptionSide": "SELL_ABSORBED"}


def _base_position(size=10):
    from quant.decision.signal_builder import Signal
    from quant.execution.order import Order, Position
    sig = Signal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0,
                 rr=2.0, model_label="T", symbol="X", timestamp="1756200000")
    return Position(order=Order(signal=sig, quantity=size),
                    open_price=100.0, open_time="1756200000", size=size)


def test_live_oms_declares_no_pyramid_support():
    from quant.execution.live_oms import LiveOMS
    assert getattr(LiveOMS, "supports_pyramids", False) is False


def test_paper_oms_declares_pyramid_support():
    from quant.execution.oms import PaperOMS
    assert PaperOMS.supports_pyramids is True


def test_check_pyramid_refuses_on_unsupporting_oms():
    oms = MagicMock()
    del oms.supports_pyramids  # simulate LiveOMS / unknown port impl
    pm = _pm_with(oms)
    pm.check_pyramid(_dto(), _bar(), _base_position(), bar_index=50)
    oms.add_pyramid.assert_not_called()


def test_unknown_oms_defaults_to_no_pyramids():
    pm = _pm_with(object())  # bare object: no capability declared
    pm.check_pyramid(_dto(), _bar(), _base_position(), bar_index=50)
    assert pm.pyramid_count == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_live_pyramids_disabled.py -q`
Expected: FAIL — attributes missing, `check_pyramid` proceeds (mock `add_pyramid` gets called / count increments)

- [ ] **Step 3: Implement**

`quant/execution/oms.py` — inside `class PaperOMS`:

```python
    # Pyramid add-ons are fully simulated here (linked Position + fills).
    supports_pyramids = True
```

`quant/execution/live_oms.py` — inside `class LiveOMS`:

```python
    # ponytail: add_pyramid() builds a tracking-only Position while NO broker
    # order is ever submitted for pyramids (ghost exposure). Disabled until
    # submit-path exists end-to-end; flip True when PyramidFilled flows prove
    # broker orders behind every add-on.
    supports_pyramids = False
```

`quant/position_manager.py` — first lines of `check_pyramid` (before the max-count check):

```python
        # Fail-safe: an OMS that does not declare pyramid support (live broker
        # path) never gets add-ons — see certification review defect E9.
        if not getattr(self._oms, "supports_pyramids", False):
            return
```

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/ tests/quant/certification/ tests/system/ -q`
Expected: PASS. `test_pyramid_oms.py` / `test_pyramid_integration.py` use PaperOMS — unaffected.

- [ ] **Step 5: Commit**

```bash
git add quant/execution/oms.py quant/execution/live_oms.py quant/position_manager.py tests/quant/certification/test_live_pyramids_disabled.py
git commit -m "fix: disable pyramid add-ons under LiveOMS until broker submission exists (ghost exposure)"
```

---

### Task 8: Base-SL ratchet on pyramid fill

**Files:**
- Modify: `quant/position_manager.py` (`__init__`, `manage_exit` tail, `check_pyramid` tail)
- Modify: `quant/runtime.py:868-873` (`_check_pyramid`)
- Test: create `tests/quant/certification/test_base_sl_ratchet.py`

**Interfaces:**
- Produces: `PositionManager.base_override: Position | None` — the ratcheted base position, consumed-and-cleared by `manage_exit` return and `runtime._check_pyramid`.

- [ ] **Step 1: Write the failing test**

Build on the fixtures from Task 7's test file (import them: `from tests.quant.certification.test_live_pyramids_disabled import _pm_with, _bar, _dto, _base_position` — refactor those helpers to module-level functions they already are):

```python
def test_pyramid_add_ratchets_base_sl_and_preserves_identity():
    from dataclasses import replace as dc_replace
    oms = MagicMock()
    oms.supports_pyramids = True
    oms.lot_size = 1
    oms.add_pyramid.side_effect = lambda base, entry_price, new_sl, size, time, pyramid_level: (
        dc_replace(base, size=size, pyramid_level=pyramid_level, is_pyramid=True)
    )
    pm = _pm_with(oms)
    base = _base_position(size=10)
    pm.check_pyramid(_dto(), _bar(close=100.0), base, bar_index=50)
    assert pm.base_override is not None
    ratcheted = pm.base_override
    assert ratcheted._id == base._id, "trail state keyed by _id must survive"
    assert ratcheted.order.signal.sl > base.order.signal.sl  # tightened for long
    assert ratcheted.size == base.size                        # base, not the add-on


def test_manage_exit_returns_ratcheted_base():
    oms = MagicMock()
    oms.supports_pyramids = True
    oms.lot_size = 1
    oms.add_pyramid.side_effect = lambda base, entry_price, new_sl, size, time, pyramid_level: (
        dc_replace(base, size=size, pyramid_level=pyramid_level, is_pyramid=True)
    )
    pm = _pm_with(oms)
    pm._exits.evaluate = MagicMock(return_value=__import__(
        "quant.execution.exits", fromlist=["ExitDecision"]).ExitDecision(False, "", 100.0))
    base = _base_position(size=10)
    out = pm.manage_exit(_dto(), _bar(), base, bar_index=50,
                         entry_bar_index=48, entry_time_epoch=0.0)
    assert out is not None and out.order.signal.sl > base.order.signal.sl


def test_ratchet_only_tightens_never_widens():
    # LVN below current SL for a long -> no widening
    oms = MagicMock()
    oms.supports_pyramids = True
    oms.lot_size = 1
    oms.add_pyramid.return_value = _base_position(size=5)
    pm = _pm_with(oms)
    base = _base_position(size=10)  # sl=99.0
    pm._get_amt_dto = lambda: {"legLvn": 97.0, "absorptionSide": "SELL_ABSORBED"}
    pm.check_pyramid({"legLvn": 97.0, "absorptionSide": "SELL_ABSORBED"},
                     _bar(close=100.0), base, bar_index=50)
    assert pm.base_override is None  # 97-shelf stop would widen -> skipped
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_base_sl_ratchet.py -q`
Expected: FAIL — `base_override` attribute missing

- [ ] **Step 3: Implement**

`PositionManager.__init__` additions:

```python
        # Ratcheted base position produced by the latest pyramid fill.
        # Consumed (and cleared) by manage_exit's return or runtime._check_pyramid.
        self.base_override = None
        # Reserved rupee risk per open pyramid add-on, keyed by position _id.
        self._pyramid_open_risk: dict = {}
        # Shared portfolio authority (optional) — pyramids reserve real risk.
        self.portfolio_risk = portfolio_risk
```

with constructor parameter `portfolio_risk=None` appended (Task 9 wires it; declare now).

`check_pyramid` — after the successful `add_pyramid` and bookkeeping (lines 297-304), before the final emit:

```python
        # Spec §13.2 SL ratchet: pull the BASE stop to the new shelf so
        # base + add-ons are net positive together. Only tighten, never widen.
        cur_sl = float(position.order.signal.sl)
        if (long and new_sl > cur_sl) or (not long and new_sl < cur_sl):
            from dataclasses import replace as _dc_replace
            ratcheted = _dc_replace(
                position,
                order=_dc_replace(position.order,
                                  signal=_dc_replace(position.order.signal, sl=new_sl)),
            )
            # _id survives dataclasses.replace -> ExitEngine trail state intact
            self.base_override = ratcheted
            self._emit(StopMoved(symbol=self.symbol, time=bar.time,
                                 old_sl=cur_sl, new_sl=float(new_sl),
                                 reason="PYRAMID_RATCHET"))
```

`manage_exit` tail (lines 196-200):

```python
        else:
            if position is not None and self._exits.is_risk_free(position):
                self.check_pyramid(amt_dto, bar, position, bar_index)
            survived = self.base_override if self.base_override is not None else position
            self.base_override = None
            return survived
```

and reset at method start (after line 93): `self.base_override = None`.

`runtime._check_pyramid` (lines 868-873):

```python
    def _check_pyramid(self, amt_dto: dict, bar) -> None:
        pm = self._get_position_manager()
        pm.check_pyramid(amt_dto, bar, self._position, self._bar_index)
        # Sync pyramid state back
        self._pyramid_positions = pm.pyramid_positions
        self._pyramid_count = pm.pyramid_count
        if pm.base_override is not None:
            self._position = pm.base_override
            pm.base_override = None
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/ tests/quant/execution/ tests/system/test_fabio_behavior_trace.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/position_manager.py quant/runtime.py tests/quant/certification/test_base_sl_ratchet.py
git commit -m "feat: base-SL ratchets to LVN shelf on pyramid fill (spec 13.2), identity preserved"
```

---

### Task 9: Pyramids reserve real portfolio risk

**Files:**
- Modify: `quant/position_manager.py` (constructor wired in Task 8; reservation in `check_pyramid`, release in the pyramid-close loop lines 171-177)
- Modify: `quant/runtime.py` (pass `portfolio_risk` into PositionManager; DELETE the dead double-booking block at lines 812-815)
- Test: extend `tests/quant/certification/test_base_sl_ratchet.py` or new `tests/quant/certification/test_pyramid_portfolio_risk.py`

**Interfaces:**
- Consumes: `PortfolioRiskAuthority.can_accept(r) -> (bool, str)`, `.register_open(r) -> bool`, `.record_close(r, pnl)` (quant/execution/portfolio_risk.py:38-50).

- [ ] **Step 1: Write the failing test**

```python
def test_pyramid_reserves_and_releases_portfolio_risk():
    from quant.execution.portfolio_risk import PortfolioRiskAuthority
    auth = PortfolioRiskAuthority(starting_equity=100_000)
    oms = MagicMock()
    oms.supports_pyramids = True
    oms.lot_size = 1
    oms.add_pyramid.side_effect = (
        lambda base, entry_price, new_sl, size, time, pyramid_level:
        dc_replace(base, size=size, pyramid_level=pyramid_level, is_pyramid=True)
    )
    pm = _pm_with(oms)
    pm.portfolio_risk = auth
    base = _base_position(size=10)
    pm.check_pyramid(_dto(), _bar(), base, bar_index=50)
    assert pm.pyramid_count == 1
    expected = abs(100.0 - pm.pyramid_positions[0].order.signal.sl) * max(1.0, 5.0)
    assert auth.open_risk >= expected - 0.01
    # Close everything like a full exit does:
    fill = MagicMock()
    fill.pnl = 12.0
    pyr = pm.pyramid_positions[0]
    pm._exits.pop_trail = lambda p: None
    pm._oms.close = MagicMock(return_value=fill)
    pm.last_fill = None
    pm.manage_exit({}, _bar(), base, bar_index=60,
                   entry_bar_index=48, entry_time_epoch=0.0)
    assert auth.open_risk < 0.01, "pyramid risk released on close"


def test_pyramid_refused_when_portfolio_cap_hit():
    from quant.execution.portfolio_risk import PortfolioRiskAuthority
    auth = PortfolioRiskAuthority(starting_equity=100_000,
                                  max_portfolio_risk_pct=0.0000001)
    oms = MagicMock()
    oms.supports_pyramids = True
    oms.lot_size = 1
    pm = _pm_with(oms)
    pm.portfolio_risk = auth
    pm.check_pyramid(_dto(), _bar(), _base_position(size=10), bar_index=50)
    assert pm.pyramid_count == 0
    oms.add_pyramid.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_pyramid_portfolio_risk.py -q`
Expected: FAIL — no reservation happens

- [ ] **Step 3: Implement**

In `check_pyramid`, reserve BEFORE constructing the add-on (insert before the `try:` at line 284):

```python
        add_risk = abs(price - new_sl) * max(1.0, pyramid_size)
        reserved = False
        if self.portfolio_risk is not None:
            ok, why = self.portfolio_risk.can_accept(add_risk)
            if not ok:
                logger.info("🛑 [PYRAMID RISK] %s refused: %s", self.symbol, why)
                return
            if not self.portfolio_risk.register_open(add_risk):
                logger.info("🛑 [PYRAMID RISK] %s refused at register", self.symbol)
                return
            reserved = True
```

and in the existing `except ValueError` branch (lines 293-295), release the reservation:

```python
        except ValueError as exc:
            if reserved and self.portfolio_risk is not None:
                self.portfolio_risk.record_close(add_risk, 0.0)
            logger.debug("⏩ [PYRAMID SKIP] %s: %s", self.symbol, exc)
            return
```

After success (line 298 area): `self._pyramid_open_risk[pyramid_pos._id] = add_risk`.

Release in the pyramid-close loop (inside `for pyr_pos in self.pyramid_positions:` at line 171, before emitting PositionClosed):

```python
                risk_i = self._pyramid_open_risk.pop(pyr_pos._id, 0.0)
                if self.portfolio_risk is not None:
                    self.portfolio_risk.record_close(risk_i, float(pyr_fill.pnl))
```

In `runtime.py`:
- `_get_position_manager` (lines 772-785): add `portfolio_risk=self._portfolio_risk,` to the constructor call.
- DELETE lines 812-815 (`if pm.last_pyramid_pnl:` block) — realized P&L for pyramids is now booked exactly once, inside the manager. Keep `last_pyramid_pnl` accumulation (line 177) for logging.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/ tests/quant/certification/ tests/quant/test_portfolio_risk_guard.py tests/lifecycle_races.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/position_manager.py quant/runtime.py tests/quant/certification/
git commit -m "fix: pyramid add-ons reserve and release real portfolio risk; single-source P&L booking"
```

---

### Task 10: Injectable date for contract-expiry parsing

**Files:**
- Modify: `quant/session_gates.py` (`parse_contract_expiry`, body at lines 88-95)
- Test: extend the session-gates test file (glob `tests/**/test_session_gate*.py`)

- [ ] **Step 1: Write the failing test**

```python
def test_parse_contract_expiry_accepts_injected_today():
    """Determinism edge: year resolution used datetime.now(). Replay/certs
    must pin the clock."""
    from datetime import date
    from quant.session_gates import parse_contract_expiry
    # '26 DEC' resolved from 2026-12-31 must land in 2027
    got = parse_contract_expiry("NIFTY 26 DEC 25000 CE",
                                today=date(2026, 12, 31))
    assert got == date(2027, 12, 26)
    # past month/day within the injected year resolves to that year
    got2 = parse_contract_expiry("CRUDEOIL 17 AUG 7450 CALL",
                                 today=date(2026, 8, 1))
    assert got2 == date(2027, 8, 17)  # Aug 17 already passed Aug 1? No—Aug 17 > Aug 1
    assert got2 == date(2026, 8, 17)
```

(Correct the second assertion during implementation — Aug 17 is AFTER Aug 1, so it resolves to `date(2026, 8, 17)`. Keep exactly one correct expectation.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest <session-gates test> -q`
Expected: FAIL — unexpected keyword `today`

- [ ] **Step 3: Implement**

Signature gains `today: date | None = None`; body line 88 becomes:

```python
    today = today or datetime.now(tz=_IST).date()
```

No caller changes (default preserves behavior). Engine construction in replay/cert paths can later pin the date; `# ponytail:` note: wiring an explicit clock through QuantEngine.__init__ deferred until a test demands it.

- [ ] **Step 4: Verify + commit**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/ -q -k "session or gate"`
Expected: PASS

```bash
git add quant/session_gates.py tests/quant/
git commit -m "fix: parse_contract_expiry accepts injected today (determinism edge)"
```

---

### Task 11: Certification battery runner + `make parity`

**Files:**
- Create: `tests/quant/certification/run_battery.py`
- Modify: `Makefile` (.PHONY + parity target)

**Interfaces:**
- Consumes: `load_ticks`, `replay_twice`, `first_divergence` from Tasks 1-2.
- Produces: `docs/reviews/certification-results-<YYYYMMDD>.md`; CLI exit 0 iff all S13 sessions deterministic.

- [ ] **Step 1: Implement runner**

```python
# tests/quant/certification/run_battery.py
"""Certification battery over recorded journals.

S13: 2-engine payload-exact replay per journal (hard fail).
S11: StopMoved coverage stats (informational until Task 3 ages into data).
S9:  sizing sanity — actual size <= equity*pct/risk-distance per trade.

Usage: PYTHONPATH=backend:. python -m tests.quant.certification.run_battery \
           [--journals-dir backend/journals] [--limit 5]

# ponytail: S2 market-state accuracy waits for a labeled ground-truth corpus;
# S12 OMS matrix lives in brokers/tests. This runner certifies what journals
# can actually prove today.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from datetime import datetime

from tests.quant.certification.journal_replay import load_ticks, replay_twice
from tests.quant.certification.trace_compare import first_divergence


def s13_determinism(paths: list[str]) -> list[tuple[str, bool, str]]:
    out = []
    for p in paths:
        try:
            ticks, iv = load_ticks(p)
            t1, t2 = replay_twice(ticks, "CERT", iv)
            div = first_divergence(t1, t2)
            out.append((os.path.basename(p), div is None, div or f"{len(t1)} events exact"))
        except Exception as exc:  # noqa: BLE001 - battery reports, not crashes
            out.append((os.path.basename(p), False, f"harness error: {exc}"))
    return out


def s11_stop_moves(trace) -> dict:
    moves = [e for e in trace if type(e).__name__ == "StopMoved"]
    return {
        "count": len(moves),
        "reasons": sorted({e.reason for e in moves}),
        "unexplained": sum(1 for e in moves if not e.reason),
    }


def s9_sizing_sanity(trace) -> dict:
    """For every PositionOpened, find the last RiskUpdated before it and check
    quantity <= equity * pct / risk_distance (+lot slack)."""
    checked = violations = 0
    last_equity, last_pct = 0.0, 0.005
    for e in trace:
        name = type(e).__name__
        if name == "RiskUpdated":
            last_equity = float(getattr(e.risk, "equity", 0.0) or 0.0)
            last_pct = float(getattr(e.risk, "risk_per_trade_pct", 0.005) or 0.005)
        elif name == "PositionOpened":
            sig = e.position.order.signal
            risk_dist = abs(float(sig.entry) - float(sig.sl))
            qty = abs(float(e.position.size))
            if risk_dist <= 0 or qty <= 0:
                continue
            checked += 1
            ceiling = last_equity * last_pct / risk_dist * 1.001 + 1.0  # +1 lot snap slack
            if qty > ceiling:
                violations += 1
    return {"checked": checked, "violations": violations}


def write_report(results_dir: str, rows, stats) -> str:
    os.makedirs(results_dir, exist_ok=True)
    path = os.path.join(
        results_dir, f"certification-results-{datetime.now():%Y%m%d}.md")
    lines = ["# Certification Results", "",
             f"_Generated {datetime.now():%Y-%m-%d %H:%M} by run_battery_", "",
             "## S13 Replay Determinism", "",
             "| Journal | Deterministic | Detail |", "|---|---|---|"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d} |" for n, ok, d in rows]
    lines += ["", "## S11 Stop-Move Audit", "",
              f"- moves: {stats['s11']['count']}, unexplained: "
              f"{stats['s11']['unexplained']}, reasons: {stats['s11']['reasons']}"]
    lines += ["", "## S9 Sizing Sanity", "",
              f"- trades checked: {stats['s9']['checked']}, "
              f"over-sized: {stats['s9']['violations']}"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--journals-dir", default="backend/journals")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--results-dir", default="docs/reviews")
    args = ap.parse_args(argv)
    paths = sorted(glob.glob(os.path.join(args.journals_dir, "*.jsonl")))
    if not paths:
        print("no journals found"); return 2
    rows = s13_determinism(paths[-args.limit:])
    stats = {}
    if rows:
        ticks, iv = load_ticks(os.path.join(args.journals_dir, rows[0][0]))
        t1, _ = replay_twice(ticks, "CERT", iv)
        stats["s11"] = s11_stop_moves(t1)
        stats["s9"] = s9_sizing_sanity(t1)
    path = write_report(args.results_dir, rows, stats)
    ok = all(ok for _, ok, _ in rows)
    print(f"{'PASS' if ok else 'FAIL'} — report: {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Makefile target**

Update `.PHONY` (line 1) to include `parity`; append:

```make
# Certification parity gate: golden suites + journal-replay determinism battery.
parity:
	PYTHONPATH=backend:. $(PYTHON) -m pytest tests/quant/test_golden_tape.py tests/quant/test_golden_replay.py tests/quant/test_decide_golden.py tests/quant/certification/ -q --no-header
	PYTHONPATH=backend:. $(PYTHON) -m tests.quant.certification.run_battery --limit 5
```

- [ ] **Step 3: Run the battery**

Run: `make parity`
Expected: PASS on recorded days; `docs/reviews/certification-results-20260826.md` written. Any FAIL row is a certification finding — investigate before proceeding (wall-clock-keyed divergence vs genuine math drift).

- [ ] **Step 4: Full regression sweep**

Run: `make test && make lint`
Expected: all suites green (~2,700 baseline), ruff clean. Behavior-change diffs vs baseline (fewer Triple-A approvals from Task 4) show up only in trade counts, not test failures — if a test fails because it asserted the inflated behavior, fix the test per Task 4 Step 4 discipline and name it in the commit.

- [ ] **Step 5: Commit**

```bash
git add tests/quant/certification/run_battery.py Makefile docs/reviews/certification-results-*.md
git commit -m "feat: certification battery (S13 determinism, S11 stop-audit, S9 sizing) + make parity gate"
```

---

## Self-Review Notes

- Spec coverage: master-plan W1 → Tasks 1-3, 11 (corpus backfill deliberately deferred — 66 recorded days exist and are enough to prove the harness; backfill is a follow-up). W2 → Task 11 (S9/S11/S13 subset; remaining steps require the labeled corpus and are marked deferred). W4 → Tasks 4-10. Review-transcript authoring (W3) intentionally excluded — it consumes this plan's generated results and gets its own plan.
- Type consistency: `StopMoved(old_sl, new_sl, reason)` used identically in Tasks 3, 8. `build_or_reason` signature consistent between Tasks 1(no)/5. `supports_pyramids` consistent between Tasks 7, 8 fixtures. `base_override` lifecycle defined in Task 8 and consumed in runtime.
- Deferred with rationale: corpus ground-truth labeling (needs human AMT judgment), live-vs-replay full parity (needs tick-grade journals — ceiling noted in journal_ticks.py), Upstox/OMS state-machine expansion (separate plan).

## Execution Handoff

Two options: subagent-driven (fresh worker per task, review between tasks) or inline batch execution with checkpoints.
