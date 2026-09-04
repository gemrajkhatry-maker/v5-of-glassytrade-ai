# quantv2 Production-Readiness Implementation Plan (futures first, staged)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make quantv2 production-ready for direct/futures instruments on its own Dhan client: close the 7 pre-broker Important items, complete AMT (Triple-A + Second Drive + VA_FADE scale), add session clock/halts/cooldown, lot registry, Dhan WS feed + REST broker with reconciliation, and a standalone runner with paper-live flag.

**Architecture:** Tasks 1–5 harden the existing spine (time-stop, close-retry, store validation, snapshot guard, live-port contract). Tasks 6–9 complete AMT so all setups can fire and pin one full-loop test. Tasks 10–16 add the production shell: session clock, risk halts, lot registry, Dhan clients, runner. Every task keeps the zero-v1-import gate and full `pytest tests/quantv2/ -v` green.

**Tech Stack:** Python stdlib only, pytest. No new deps (Dhan WS/REST behind injectable transports so unit tests need no network).

**Staging:** This plan covers Phase A (futures/direct symbols). Phase B (option selection + underlying AMT + signal translation) is a separate follow-up plan — explicitly out of scope here.

## Global Constraints

- v1 `quant/` frozen; `quantv2/` must never import v1 (existing `test_no_v1_imports.py` gate stays green).
- Stdlib only; no network in unit tests (transports are injected fakes).
- APPROVED only after submit; every rejection carries a reason; RR >= 1.5 + monotonic.
- One main-bar trigger; exits bar-close + engine-clock time/force-exit checks.
- Full `pytest tests/quantv2/ -v` green at every task end; frequent commits.

---

### Task 1: TIME_STOP in engine (clock owner)

**Files:**
- Modify: `quantv2/exits.py` (`evaluate_exit` gains `elapsed_min: float | None = None`)
- Modify: `quantv2/engine.py` (positioned path computes elapsed from bar.time vs `position.opened_at`)
- Test: `tests/quantv2/test_exits.py` (append), `tests/quantv2/test_engine.py` (append)

**Interfaces:**
- Consumes: `ExitConfig.time_stop_min` (exists, unused today).
- Produces: TIME_STOP exit reason reachable; `evaluate_exit(pos, bar, trail, cfg, elapsed_min=None) -> tuple[ExitDecision, dict]`.

- [ ] **Step 1: Write the failing test** (append to `tests/quantv2/test_exits.py`)

```python
from quantv2.exits import evaluate_exit

def test_time_stop_fires_after_limit():
    cfg = ExitConfig(time_stop_min=30, trail_ticks=4, tick=0.05)
    pos = Position(pid="p9", symbol="X", side="LONG", qty=10.0, entry=100.0, sl=95.0, tp=110.0, setup="T", opened_at="t")
    b = Bar(time="t31", open=100.0, high=100.5, low=99.9, close=100.2)
    d, _ = evaluate_exit(pos, b, {}, cfg, elapsed_min=31.0)
    assert (d.should_exit, d.reason) == (True, "TIME_STOP")
    d2, _ = evaluate_exit(pos, b, {}, cfg, elapsed_min=10.0)
    assert d2.should_exit is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_exits.py::test_time_stop_fires_after_limit -v`
Expected: FAIL (`evaluate_exit` has no `elapsed_min` param)

- [ ] **Step 3: Write minimal implementation** (in `evaluate_exit`, before the side branches)

```python
    if elapsed_min is not None and cfg.time_stop_min > 0 and elapsed_min >= cfg.time_stop_min:
        return ExitDecision(True, "TIME_STOP", bar.close), {"peak": peak, "be": prev_be}
```

In `quantv2/engine.py` positioned path, compute elapsed and pass it:

```python
        elapsed_min = self._elapsed_min(bar.time, self.position.opened_at)
        d, self.trail = evaluate_exit(self.position, bar, self.trail, self.exit_cfg, elapsed_min=elapsed_min)
```

Helper on Engine (ISO timestamps; malformed → None so TIME_STOP never false-fires):

```python
    @staticmethod
    def _elapsed_min(now_iso: str, opened_iso: str) -> float | None:
        from datetime import datetime
        try:
            t0 = datetime.fromisoformat(opened_iso)
            t1 = datetime.fromisoformat(now_iso)
            return (t1 - t0).total_seconds() / 60.0
        except (ValueError, TypeError):
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/exits.py quantv2/engine.py tests/quantv2/test_exits.py tests/quantv2/test_engine.py
git commit -m "feat(quantv2): enforce TIME_STOP via engine clock"
```

### Task 2: close-retry semantics

**Files:**
- Modify: `quantv2/engine.py` (wrap `oms.close` in try/except; keep position on raise)
- Modify: `quantv2/coordinator.py` (`eod_flatten` per-symbol try/except, count successes only)
- Test: `tests/quantv2/test_engine.py`, `tests/quantv2/test_coordinator.py` (append)

**Interfaces:**
- Produces: on close raise, `on_bar` returns `Decision(False, "EXIT_RETRY")` and keeps position/trail; `eod_flatten` never aborts mid-loop.

- [ ] **Step 1: Write the failing test** (append to `tests/quantv2/test_engine.py`)

```python
from quantv2.engine import Engine
from quantv2.oms import PaperOMS, Position
from quantv2.types import Bar

class FailingCloseOMS(PaperOMS):
    def close(self, pos, price, reason):
        raise RuntimeError("broker down")

def test_close_raise_keeps_position():
    eng = Engine(symbol="X", interval_sec=60, oms=FailingCloseOMS(), equity=100000.0)
    eng.position = Position(pid="p1", symbol="X", side="LONG", qty=1.0, entry=100.0, sl=99.0, tp=102.0, setup="T", opened_at="t")
    d = eng.on_bar(Bar(time="2026-09-04T10:01:00+05:30", open=99.0, high=100.0, low=98.0, close=98.5))
    assert d.approved is False and d.reason == "EXIT_RETRY" and eng.position is not None
```

And in `tests/quantv2/test_coordinator.py`:

```python
def test_eod_flatten_survives_close_raise():
    from quantv2.oms import Position

    class NoCloseOMS(PaperOMS):
        def close(self, pos, price, reason):
            raise RuntimeError("down")

    c = Coordinator(risk_cap=100000.0)
    bad = Engine(symbol="A", interval_sec=60, oms=NoCloseOMS(), equity=100000.0)
    good = Engine(symbol="B", interval_sec=60, oms=PaperOMS(), equity=100000.0)
    c.add(bad)
    c.add(good)
    bad.position = Position(pid="p1", symbol="A", side="LONG", qty=1.0, entry=100.0, sl=99.0, tp=102.0, setup="T", opened_at="t")
    good.position = Position(pid="p2", symbol="B", side="LONG", qty=1.0, entry=100.0, sl=99.0, tp=102.0, setup="T", opened_at="t")
    c.on_tick("A", 0, 100.0, 1.0, 0.0)
    c.on_tick("B", 0, 100.0, 1.0, 0.0)
    n = c.eod_flatten()
    assert n == 1 and good.position is None and bad.position is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/quantv2/test_engine.py::test_close_raise_keeps_position tests/quantv2/test_coordinator.py::test_eod_flatten_survives_close_raise -v`
Expected: FAIL (raise propagates today)

- [ ] **Step 3: Write minimal implementation**

Engine positioned-exit block:

```python
            if d.should_exit:
                try:
                    self.oms.close(self.position, d.price, d.reason)
                except Exception:
                    return Decision(False, "EXIT_RETRY")
                self.position = None
                self.trail = {}
                self.open_risk = 0.0
                return Decision(False, f"EXITED_{d.reason}")
```

Coordinator `eod_flatten` loop body:

```python
        for symbol, eng in self.engines.items():
            if eng.position is None:
                continue
            try:
                eng.oms.close(eng.position, self._last.get(symbol, eng.position.entry), reason)
            except Exception:
                continue
            eng.position = None
            eng.trail = {}
            eng.open_risk = 0.0
            n += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/engine.py quantv2/coordinator.py tests/quantv2/test_engine.py tests/quantv2/test_coordinator.py
git commit -m "feat(quantv2): close-retry keeps position, EOD survives raise"
```

### Task 3: store validation (fail-closed restore + halted flag)

**Files:**
- Modify: `quantv2/store.py` (`restore` non-dict → `{}`)
- Modify: `quantv2/coordinator.py` (`load_state` per-symbol schema guard; corrupt symbol → fresh + halted)
- Test: `tests/quantv2/test_store.py` (append)

**Interfaces:**
- Produces: `restore` never returns non-dict; `load_state` marks corrupt symbols `can_trade=False` (fresh + halted); valid symbols restore normally.

- [ ] **Step 1: Write the failing test** (append to `tests/quantv2/test_store.py`)

```python
from quantv2.coordinator import Coordinator
from quantv2.engine import Engine
from quantv2.oms import PaperOMS

def test_corrupt_store_halts_symbol_only(tmp_path):
    p = str(tmp_path / "state.json")
    with open(p, "w") as f:
        f.write('{"X": {"position": {"bad": 1}, "open_risk": 1.0, "trail": {}}}')
    c = Coordinator()
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    c.load_state(restore(p))
    assert c.engines["X"].position is None and c.engines["X"].can_trade is False

def test_restore_non_dict_returns_empty(tmp_path):
    p = str(tmp_path / "state.json")
    with open(p, "w") as f:
        f.write('["not", "a", "dict"]')
    assert restore(p) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/quantv2/test_store.py -v`
Expected: FAIL (`Position(**p)` raises TypeError today; `restore` returns the list)

- [ ] **Step 3: Write minimal implementation**

`store.py` `restore` tail:

```python
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
```

(read into `data` variable first). `coordinator.py` `load_state`:

```python
    def load_state(self, state: dict) -> None:
        from quantv2.oms import Position
        for symbol, s in state.items():
            eng = self.engines.get(symbol)
            if eng is None:
                continue
            if not isinstance(s, dict):
                eng.can_trade = False
                continue
            p = s.get("position")
            try:
                eng.position = Position(**p) if p else None
                eng.open_risk = float(s.get("open_risk", 0.0))
                eng.trail = dict(s.get("trail", {}))
            except (TypeError, ValueError):
                eng.position = None
                eng.open_risk = 0.0
                eng.trail = {}
                eng.can_trade = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/store.py quantv2/coordinator.py tests/quantv2/test_store.py
git commit -m "feat(quantv2): validated restore, corrupt halts symbol"
```

### Task 4: last_decision mid-bar guard + pipeline approved+None guard

**Files:**
- Modify: `quantv2/coordinator.py` (record only non-None)
- Modify: `quantv2/pipeline.py` (submit returning None → SUBMIT_FAILED)
- Test: `tests/quantv2/test_broker_snapshot.py`, `tests/quantv2/test_pipeline.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/quantv2/test_broker_snapshot.py`)

```python
def test_midbar_tick_keeps_last_decision():
    from quantv2.engine import Engine
    from quantv2.oms import PaperOMS
    from quantv2.coordinator import Coordinator
    c = Coordinator()
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    closed = c.on_tick("X", 60, 100.0, 1.0, 0.0)
    c.on_tick("X", 90, 100.1, 1.0, 0.0)
    assert c.engines["X"].last_decision is closed
```

And in `tests/quantv2/test_pipeline.py`:

```python
def test_none_submit_rejects():
    class NoneOMS:
        def submit(self, signal, qty):
            return None
    b = Bar(time="t", open=100.0, high=101.0, low=98.0, close=100.0, volume=5.0)
    ctx = Context(symbol="X", bar=b, tick=0.05, vah=101.0, val=99.0, poc=100.8, cvd_slope=0.3,
                  extra={"triple_phase": "AGGRESSION", "triple_signal": "LONG", "acceptance": True})
    d = decide(ctx, session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0, oms=NoneOMS())
    assert d.approved is False and d.reason == "SUBMIT_FAILED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/quantv2/test_broker_snapshot.py::test_midbar_tick_keeps_last_decision tests/quantv2/test_pipeline.py::test_none_submit_rejects -v`
Expected: FAIL (guard missing)

- [ ] **Step 3: Write minimal implementation**

Coordinator `on_tick`:

```python
        out = eng.on_tick(ts, price, volume, delta)
        if out is not None:
            eng.last_decision = out
        return out
```

Pipeline submit block:

```python
    try:
        pos = oms.submit(sig, qty)
    except Exception:
        return Decision(False, "SUBMIT_FAILED")
    if pos is None:
        return Decision(False, "SUBMIT_FAILED")
    return Decision(True, setup, sig, pos)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/coordinator.py quantv2/pipeline.py tests/quantv2/test_broker_snapshot.py tests/quantv2/test_pipeline.py
git commit -m "feat(quantv2): snapshot guard, none-submit guard"
```

### Task 5: live-port contract + typed Decision.position

**Files:**
- Modify: `quantv2/broker.py` (add `BrokerPort` Protocol: `submit(signal, qty) -> Position` or raise)
- Modify: `quantv2/types.py` (`Decision.position: "Position | None"` via TYPE_CHECKING)
- Test: `tests/quantv2/test_broker_snapshot.py` (append contract test)

- [ ] **Step 1: Write the failing test** (append to `tests/quantv2/test_broker_snapshot.py`)

```python
def test_broker_port_contract():
    from quantv2.broker import BrokerPort
    from quantv2.oms import PaperOMS
    from quantv2.types import Signal
    class GoodPort:
        def submit(self, signal, qty):
            return PaperOMS().submit(signal, qty)
    port: BrokerPort = GoodPort()
    sig = Signal(type="LONG", entry=1.0, sl=0.9, tp=1.2, rr=2.0, setup="T", symbol="X", timestamp="t")
    assert port.submit(sig, 1).qty == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_broker_snapshot.py::test_broker_port_contract -v`
Expected: FAIL (no `BrokerPort`)

- [ ] **Step 3: Write minimal implementation**

`broker.py` (below `LiveNotEnabled`):

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class BrokerPort(Protocol):
    """Live broker port contract: submit MUST return a quantv2 Position or raise."""
    def submit(self, signal, qty: float): ...
```

`types.py` top:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from quantv2.oms import Position
```

and field: `position: "Position | None" = None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/broker.py quantv2/types.py tests/quantv2/test_broker_snapshot.py
git commit -m "feat(quantv2): BrokerPort contract, typed Decision.position"
```

### Task 6: AMT Triple-A machine (acceptance memory)

**Files:**
- Modify: `quantv2/amt.py` (add `_TripleA` tracker; emit `triple_phase/triple_signal/acceptance` into extra)
- Test: `tests/quantv2/test_amt.py` (append), plus contract test amt→detect

**Interfaces:**
- Produces: on a real bar stream, `SessionAMT.update` emits `extra["triple_phase"]`, `extra["triple_signal"]` ("LONG"/"SHORT"), `extra["acceptance"]` (bool) such that `setups.detect` returns `("TRIPLE_A", ...)`.

- [ ] **Step 1: Write the failing test** (append to `tests/quantv2/test_amt.py`)

```python
from quantv2.types import Bar
from quantv2.setups import detect
from quantv2.types import Context

def _bars():
    # absorption: heavy selling (delta<0) but price closes UP — buyers absorbed the sellers (bullish)
    return [
        Bar(time="t1", open=99.2, high=100.4, low=99.0, close=100.2, volume=100.0, delta=-60.0),
        Bar(time="t2", open=100.2, high=100.5, low=100.0, close=100.3, volume=20.0, delta=8.0),
        Bar(time="t3", open=100.3, high=100.6, low=100.1, close=100.5, volume=20.0, delta=9.0),
        Bar(time="t4", open=100.5, high=101.2, low=100.4, close=101.0, volume=60.0, delta=45.0),
        Bar(time="t5", open=101.0, high=101.3, low=100.9, close=101.1, volume=30.0, delta=12.0),
    ]

def test_triple_a_contract_reaches_detect():
    amt = SessionAMT(tick=0.05)
    for b in _bars():
        snap = amt.update(b)
    ctx = Context(symbol="X", bar=_bars()[-1], tick=0.05, **{k: snap[k] for k in ("vah", "val", "poc", "cvd_slope")}, extra=snap["extra"])
    hit = detect(ctx)
    assert hit is not None and hit[0] in ("TRIPLE_A", "INITIATIVE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_amt.py::test_triple_a_contract_reaches_detect -v`
Expected: FAIL (extra never contains triple keys → detect is None or INITIATIVE-only... INITIATIVE passes the `in` — tighten: also assert `snap["extra"].get("triple_phase") == "AGGRESSION"`; include that line in the test)

Add before the `hit =` line: `assert snap["extra"].get("triple_phase") == "AGGRESSION" and snap["extra"].get("triple_signal") == "LONG"` — now the test fails on the missing keys.

- [ ] **Step 3: Write minimal implementation**

In `amt.py`, add tracker class (complete, no placeholders):

```python
class _TripleA:
    """Absorption -> accumulation -> aggression -> acceptance (LONG or SHORT)."""

    def __init__(self, tick: float) -> None:
        self.tick = tick if tick > 0 else 0.05
        self.reset()

    def reset(self) -> None:
        self.phase = "WAITING"
        self.side = None
        self.level = 0.0
        self.acc = 0

    def update(self, bar: Bar) -> dict:
        out: dict = {}
        body_up = bar.close > bar.open
        if self.phase == "WAITING":
            # absorption: volume spike, delta against the close direction
            if bar.volume > 0 and bar.delta != 0:
                against = (bar.delta < 0 and body_up) or (bar.delta > 0 and not body_up)
                if against and abs(bar.delta) > 0.3 * bar.volume:
                    self.phase = "ABSORBING"
                    # absorption means the close's side won: continuation follows the body
                    self.side = "LONG" if body_up else "SHORT"
                    self.level = bar.low if self.side == "LONG" else bar.high
                    self.acc = 0
            out["triple_phase"] = "ABSORBING" if self.phase != "WAITING" else "WAITING"
            if self.phase != "WAITING":
                out["triple_signal"] = self.side
            return out
        if self.phase == "ABSORBING":
            stepped = (self.side == "LONG" and bar.close > bar.open and bar.delta > 0) or (
                self.side == "SHORT" and bar.close < bar.open and bar.delta < 0)
            self.acc = self.acc + 1 if stepped else 0
            if self.acc >= 2:
                self.phase = "ACCUMULATED"
            out["triple_phase"] = "ABSORBING"
            out["triple_signal"] = self.side
            return out
        if self.phase == "ACCUMULATED":
            strong = bar.volume > 0 and abs(bar.delta) > 0.3 * bar.volume
            broke_up = self.side == "LONG" and strong and bar.close > max(bar.open, self.level)
            broke_dn = self.side == "SHORT" and strong and bar.close < min(bar.open, self.level)
            if broke_up or broke_dn:
                self.phase = "AGGRESSION"
                out["triple_phase"] = "AGGRESSION"
                out["triple_signal"] = self.side
                out["acceptance"] = False
                return out
            out["triple_phase"] = "ABSORBING"
            out["triple_signal"] = self.side
            return out
        # AGGRESSION: acceptance = this bar holds beyond the absorption extreme
        held = bar.close >= self.level if self.side == "LONG" else bar.close <= self.level
        if held:
            out["triple_phase"] = "AGGRESSION"
            out["triple_signal"] = self.side
            out["acceptance"] = True
        else:
            self.reset()
        return out
```

Wire into `SessionAMT.update`: construct `self.triple = _TripleA(tick)` in `__init__`; in `update()` after the cvd computation: `extra.update(self.triple.update(bar))`.

Note for implementer: the `acceptance` flag must be present on the AGGRESSION-hold bar (the test's `t5`), so `setups._triple_a` (requires phase AGGRESSION + signal + acceptance truthy) fires on t5.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS (if the t5 acceptance doesn't arm, adjust the acceptance check to `bar.close > self.level` for LONG / `< for SHORT` — level is the absorption extreme, t5 close 100.4 > 99.2 holds trivially; keep the test's intent, not bar-by-bar gaming)

- [ ] **Step 5: Commit**

```bash
git add quantv2/amt.py tests/quantv2/test_amt.py
git commit -m "feat(quantv2): triple-A acceptance machine"
```

### Task 7: AMT Second-Drive tracker

**Files:**
- Modify: `quantv2/amt.py` (add `_SecondDrive` tracker; emit `is_second_drive/rejection/rejection_high/direction`)
- Test: `tests/quantv2/test_amt.py` (append)

**Interfaces:**
- Produces: `extra["is_second_drive"]=True` with `rejection=True`, `rejection_high=True`, `direction="SHORT"` when a second, weaker approach to a resistance is rejected (mirror for support/LONG).

- [ ] **Step 1: Write the failing test** (append to `tests/quantv2/test_amt.py`)

```python
def test_second_drive_rejected_short():
    amt = SessionAMT(tick=0.05)
    bars = [
        Bar(time="d1", open=100.0, high=100.9, low=99.9, close=100.8, volume=30.0, delta=20.0),  # drive 1 up (high 100.9)
        Bar(time="d2", open=100.8, high=100.9, low=100.0, close=100.1, volume=20.0, delta=-12.0),  # rejected: leg_rng 0.9
        Bar(time="d3", open=100.1, high=100.85, low=100.0, close=100.3, volume=15.0, delta=-10.0),  # weaker (0.85), pokes 100.8+, rejected
    ]
    for b in bars:
        snap = amt.update(b)
    x = snap["extra"]
    assert x.get("is_second_drive") is True and x.get("rejection") is True and x.get("direction") == "SHORT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_amt.py::test_second_drive_rejected_short -v`
Expected: FAIL (keys absent)

- [ ] **Step 3: Write minimal implementation**

```python
class _SecondDrive:
    """D1 rejected at extreme -> D2 weaker approach rejected -> tradeable fade."""

    def __init__(self, tick: float) -> None:
        self.tick = tick if tick > 0 else 0.05
        self.extreme: float | None = None
        self.d1_rejected = False
        self.leg_rng = 0.0

    def update(self, bar: Bar) -> dict:
        out: dict = {}
        rng = bar.high - bar.low
        if self.extreme is None:
            return out
        if not self.d1_rejected:
            # rejection of D1: poke the extreme, close back well inside
            poked = bar.high >= self.extreme - self.tick
            back = bar.close < self.extreme - 2 * self.tick
            if poked and back:
                self.d1_rejected = True
                self.leg_rng = rng
            return out
        weaker = rng < self.leg_rng
        poked = bar.high >= self.extreme - 2 * self.tick
        rejected = bar.close < self.extreme - 2 * self.tick
        if weaker and poked and rejected:
            out["is_second_drive"] = True
            out["rejection"] = True
            out["rejection_high"] = True
            out["direction"] = "SHORT"
            self.extreme = None
            self.d1_rejected = False
        return out
```

Wire: `self.sd = _SecondDrive(tick)`; maintain `self.sd.extreme = max(...)` rolling day high in `update` before calling `self.sd.update(bar)`; merge dict into extra (`extra.update(self.sd.update(bar))`). Note: set `sd.extreme` to the rolling high BEFORE the current bar's poke detection (use previous bar's high as the extreme reference): in `update`, capture `prev_high = self.day_high` then update day_high, then `self.sd.extreme = prev_high`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/amt.py tests/quantv2/test_amt.py
git commit -m "feat(quantv2): second-drive tracker"
```

### Task 8: CVD scale fix (VA_FADE reachable)

**Files:**
- Modify: `quantv2/amt.py` (slope normalization: divide by `0.2 * sum(vols[-6:])` instead of full sum)
- Test: `tests/quantv2/test_amt.py` (append contract test)

**Interfaces:**
- Produces: `cvd_slope` magnitudes that can exceed the ±0.2 gates on ordinary flow (strong 6-bar flow ≈ 0.5–1.5), so `setups._va_fade` fires.

- [ ] **Step 1: Write the failing test** (append to `tests/quantv2/test_amt.py`)

```python
def test_cvd_scale_reaches_va_fade():
    amt = SessionAMT(tick=0.05)
    levels = [100.0, 100.1, 100.2, 100.3, 100.4]
    bars = [Bar(time=f"v{i}", open=100.0, high=100.5, low=99.9, close=levels[i % 5], volume=10.0, delta=2.0) for i in range(20)]
    dump1 = Bar(time="v20", open=99.6, high=99.7, low=99.4, close=99.5, volume=10.0, delta=4.0)
    dump2 = Bar(time="v21", open=99.55, high=99.6, low=99.35, close=99.55, volume=10.0, delta=4.0)
    for b in bars:
        snap = amt.update(b)
    amt.update(dump1)  # first dump fires INITIATIVE DOWN (priority); fade is judged on the second
    snap = amt.update(dump2)
    assert snap["cvd_slope"] >= 0.2
    from quantv2.setups import detect
    from quantv2.types import Context
    ctx = Context(symbol="X", bar=dump2, tick=0.05, vah=snap["vah"], val=snap["val"], poc=snap["poc"], cvd_slope=snap["cvd_slope"], extra=snap["extra"])
    assert detect(ctx) == ("VA_FADE", "LONG")
```

Math note (verified by hand): profile from closes [99.35..100.4] puts `val ≈ 100.0`, `poc ≈ 100.03`; dump2 close 99.55 < val and < poc; prev close 99.5 also < val so no INITIATIVE on dump2; slope ≈ 14 / (0.2×60) ≈ 1.17 ≥ 0.2. The first dump exists precisely because INITIATIVE outranks VA_FADE in `detect` — a fresh break below VAL is a break, the SECOND bar below VAL with positive delta is the fade.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_amt.py::test_cvd_scale_reaches_va_fade -v`
Expected: FAIL (slope ≈ 1e-2 → below 0.2; detect returns None/other)

- [ ] **Step 3: Write minimal implementation** (one line in `SessionAMT.update`)

```python
        norm = cvd_slope / max(1.0, 0.2 * (sum(self.vols[-6:]) or 1.0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS (profile math: 21 bars ≈ [99.5..100.4], val ≈ 99.9 < 99.5? — verify: dump close 99.5 must be < val AND < poc. With the 0.05 tick and closes at 100.0 except one 99.5, buckets: lo≈99.5, w≈0.18; the 99.5 close lands in bucket 0, mass 10 vs ~200 elsewhere → val = lower edge of 70% mass ≈ 99.68+; poc ≈ 100.0 bucket. close 99.5 < val ✓ < poc ✓ → VA_FADE LONG. If the profile puts val below 99.5 (can't — val ≥ lo = 99.5 and 99.5 is not < 99.5), adjust dump close to 99.4 and record the fix in the report.)

- [ ] **Step 5: Commit**

```bash
git add quantv2/amt.py tests/quantv2/test_amt.py
git commit -m "feat(quantv2): cvd slope scale matches setup gates"
```

### Task 9: full loop test (approve → hold → exit → EOD → restore)

**Files:**
- Create: `tests/quantv2/test_loop.py`

**Interfaces:**
- Consumes: everything so far. No production code changes expected — if code must change to make the loop work, that is a finding: fix minimally and report.

- [ ] **Step 1: Write the test**

```python
from quantv2.coordinator import Coordinator
from quantv2.engine import Engine
from quantv2.oms import PaperOMS
from quantv2.store import save, restore


def test_full_loop_approve_exit_eod_restore(tmp_path):
    c = Coordinator(risk_cap=1_000_000.0)
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0)
    c.add(eng)
    # 3 flat bars (no setup) then an INITIATIVE-UP bar (close breaks above forming VAH)
    for i in range(3):
        c.on_tick("X", 60 * i, 100.0 + 0.01 * i, 1.0, 0.0)
    # one bar worth of ticks: rising closes with strong delta
    for j in range(4):
        c.on_tick("X", 180 + 15 * j, 100.5 + 0.2 * j, 5.0, 3.0)
    approved = eng.last_decision
    assert approved is not None and approved.approved and approved.position is not None
    pos = eng.position
    # next bar: take-profit touch
    for j in range(4):
        c.on_tick("X", 240 + 15 * j, pos.tp + 0.05, 5.0, 3.0)
    assert eng.position is None
    # EOD flatten is a no-op now; save + restore into a fresh coordinator
    assert c.eod_flatten() == 0
    p = str(tmp_path / "s.json")
    save(c, p)
    c2 = Coordinator(risk_cap=1_000_000.0)
    c2.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    c2.load_state(restore(p))
    assert c2.engines["X"].position is None
    # engine still decides after restore
    out = c2.on_tick("X", 480, 101.0, 1.0, 0.0)
    assert out is None  # mid-bar, no crash
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/quantv2/test_loop.py -v`
Expected: EITHER PASS (loop coherent) or FAIL exposing a real integration gap. If FAIL: fix the minimal production cause (e.g. exit only evaluated on bar close — ensure the TP bar actually closes a bar; timestamps 240–300+15*3=285 within bucket 4 while 180–225 in bucket 3 — confirm bucket math), re-run. Record every fix in the report.

- [ ] **Step 3: Commit**

```bash
git add tests/quantv2/test_loop.py
git commit -m "test(quantv2): full approve-exit-eod-restore loop"
```

### Task 10: session clock (NSE)

**Files:**
- Create: `quantv2/clock.py`
- Create: `tests/quantv2/test_clock.py`
- Modify: `quantv2/engine.py` (optional `clock` param; sets `session_open`; force-exits SESSION_CLOSE)

**Interfaces:**
- Produces: `SessionClock(exchange="NSE")` with `is_open(epoch) -> bool`, `force_exit(epoch) -> bool` (NSE: open 09:15, force-exit 15:20, close 15:30 IST); Engine drives `self.session_open` per bar and force-exits positioned bars.

- [ ] **Step 1: Write the failing test**

```python
from quantv2.clock import SessionClock

def test_nse_phases():
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    c = SessionClock("NSE")
    open_ts = datetime(2026, 9, 4, 10, 0, tzinfo=IST).timestamp()
    early = datetime(2026, 9, 4, 9, 0, tzinfo=IST).timestamp()
    fe = datetime(2026, 9, 4, 15, 25, tzinfo=IST).timestamp()
    assert c.is_open(open_ts) is True and c.is_open(early) is False
    assert c.force_exit(fe) is True and c.force_exit(open_ts) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_clock.py -v`
Expected: FAIL (no module)

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))

class SessionClock:
    def __init__(self, exchange: str = "NSE", open_hm: tuple[int, int] = (9, 15), force_exit_hm: tuple[int, int] = (15, 20), close_hm: tuple[int, int] = (15, 30)) -> None:
        self.open_min = open_hm[0] * 60 + open_hm[1]
        self.fe_min = force_exit_hm[0] * 60 + force_exit_hm[1]
        self.close_min = close_hm[0] * 60 + close_hm[1]

    @staticmethod
    def _mod(epoch: float) -> int:
        dt = datetime.fromtimestamp(epoch, tz=_IST)
        return dt.hour * 60 + dt.minute

    def is_open(self, epoch: float) -> bool:
        m = self._mod(epoch)
        return self.open_min <= m < self.close_min

    def force_exit(self, epoch: float) -> bool:
        return self._mod(epoch) >= self.fe_min
```

Engine: `__init__(..., clock: SessionClock | None = None)` storing it; in `on_bar` first line: `if self.clock is not None: self.session_open = self.clock.is_open(<epoch from bar.time>)` (reuse `_elapsed_min`-style ISO parse, add `_epoch(iso)` helper returning None on failure → treat None as open). In the positioned path BEFORE evaluate_exit: `if self.clock and epoch and self.clock.force_exit(epoch): close at bar.close, reason SESSION_CLOSE` (respect Task 2 retry wrap).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/clock.py quantv2/engine.py tests/quantv2/test_clock.py
git commit -m "feat(quantv2): NSE session clock + force exit"
```

### Task 11: session risk (daily loss, max trades, cooldown)

**Files:**
- Create: `quantv2/session_risk.py`
- Create: `tests/quantv2/test_session_risk.py`
- Modify: `quantv2/engine.py` (optional `risk` param; feed fills; compute `cooldown_s`; `can_trade` from risk)

**Interfaces:**
- Produces: `RiskLimits(daily_loss_limit, max_trades, cooldown_sec)`, `SessionRisk.record_fill(pnl, now)`, `.can_trade(now) -> tuple[bool, str]` (reasons DAILY_LOSS / MAX_TRADES / None), `.cooldown_s(now) -> float`. Engine records closed-fill pnl and gates entries.

- [ ] **Step 1: Write the failing test**

```python
from quantv2.session_risk import RiskLimits, SessionRisk

def test_halt_and_cooldown():
    r = SessionRisk(RiskLimits(daily_loss_limit=100.0, max_trades=3, cooldown_sec=60))
    r.record_fill(-10.0, now=1000.0)
    ok, why = r.can_trade(1010.0)
    assert ok is False and why == "COOLDOWN"
    ok, _ = r.can_trade(1070.0)
    assert ok is True
    r.record_fill(-95.0, now=2000.0)
    ok, why = r.can_trade(3000.0)
    assert ok is False and why == "DAILY_LOSS"

def test_max_trades_halt():
    r = SessionRisk(RiskLimits(daily_loss_limit=1e9, max_trades=2, cooldown_sec=0))
    r.record_fill(1.0, now=0.0)
    r.record_fill(1.0, now=0.0)
    ok, why = r.can_trade(1.0)
    assert ok is False and why == "MAX_TRADES"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_session_risk.py -v`
Expected: FAIL (no module)

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class RiskLimits:
    daily_loss_limit: float = 5000.0
    max_trades: int = 20
    cooldown_sec: float = 300.0

class SessionRisk:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self.realized = 0.0
        self.trades = 0
        self.halt: str | None = None
        self.cooldown_until = 0.0

    def record_fill(self, pnl: float, now: float) -> None:
        self.realized += pnl
        self.trades += 1
        if pnl < 0:
            self.cooldown_until = now + self.limits.cooldown_sec
        if self.realized <= -abs(self.limits.daily_loss_limit):
            self.halt = "DAILY_LOSS"
        elif self.trades >= self.limits.max_trades:
            self.halt = "MAX_TRADES"

    def can_trade(self, now: float) -> tuple[bool, str]:
        if self.halt is not None:
            return False, self.halt
        if now < self.cooldown_until:
            return False, "COOLDOWN"
        return True, ""

    def cooldown_s(self, now: float) -> float:
        return max(0.0, self.cooldown_until - now)
```

Engine wiring: `__init__(..., risk: SessionRisk | None = None)`; capture fill in positioned exit (`fill = self.oms.close(...)` → `if self.risk: self.risk.record_fill(fill.pnl, epoch)`); in `on_bar` entry path: if risk present → `ok, why = self.risk.can_trade(epoch)`; if not ok → `Decision(False, why)`; else pass `can_trade=True, cooldown_s=self.risk.cooldown_s(epoch)` into decide.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/session_risk.py quantv2/engine.py tests/quantv2/test_session_risk.py
git commit -m "feat(quantv2): session risk halts and cooldown"
```

### Task 12: lot registry

**Files:**
- Create: `quantv2/lots.py`
- Create: `tests/quantv2/test_lots.py`

**Interfaces:**
- Produces: `load_lots(path) -> dict` (JSON `{symbol: {lot_size, tick_size}}`), `lot_of(registry, symbol, default_lot=1.0, default_tick=0.05) -> tuple[float, float]`.

- [ ] **Step 1: Write the failing test**

```python
from quantv2.lots import load_lots, lot_of

def test_lot_lookup(tmp_path):
    p = str(tmp_path / "lots.json")
    with open(p, "w") as f:
        f.write('{"NIFTY28AUGFUT": {"lot_size": 75, "tick_size": 0.05}}')
    reg = load_lots(p)
    assert lot_of(reg, "NIFTY28AUGFUT") == (75.0, 0.05)
    assert lot_of(reg, "MISSING") == (1.0, 0.05)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_lots.py -v`
Expected: FAIL (no module)

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations
import json

def load_lots(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

def lot_of(registry: dict, symbol: str, default_lot: float = 1.0, default_tick: float = 0.05) -> tuple[float, float]:
    e = registry.get(symbol) or {}
    lot = float(e.get("lot_size") or default_lot)
    tick = float(e.get("tick_size") or default_tick)
    return (max(1.0, lot), max(0.0001, tick))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/lots.py tests/quantv2/test_lots.py
git commit -m "feat(quantv2): lot and tick registry"
```

### Task 13: Dhan feed client (transport-injectable)

**Files:**
- Create: `quantv2/dhan_feed.py`
- Create: `tests/quantv2/test_dhan_feed.py`

**Interfaces:**
- Consumes: `Coordinator.on_tick`, `SessionClock`.
- Produces: `TickTransport` Protocol (`frames() -> iterator of dict`, blocking per frame), `DhanFeed(coordinator, security_ids: dict[symbol→id], transport, clock=None)` with `handle_frame(msg) -> int` (ticks delivered) and `run()` loop. Frame shape: `{"symbol": ..., "ltp": ..., "volume": ...}`; delta via tick rule (sign of price change × traded qty) — documented approximation. Reconnect/backoff owned by transport; feed just iterates.

- [ ] **Step 1: Write the failing test**

```python
from quantv2.dhan_feed import DhanFeed
from quantv2.coordinator import Coordinator
from quantv2.engine import Engine
from quantv2.oms import PaperOMS

class FakeTransport:
    def __init__(self, frames):
        self._frames = list(frames)
    def frames(self):
        return iter(self._frames)

def test_feed_routes_ticks():
    c = Coordinator()
    c.add(Engine(symbol="NF", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    feed = DhanFeed(c, {"NF": 1333}, FakeTransport([
        {"security_id": 1333, "ltp": 100.0, "volume": 1.0},
        {"security_id": 1333, "ltp": 100.5, "volume": 2.0},
    ]))
    n = feed.run_once()
    assert n == 2 and c.engines["NF"]._bucket is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_dhan_feed.py -v`
Expected: FAIL (no module)

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations
from typing import Protocol

class TickTransport(Protocol):
    def frames(self): ...

class DhanFeed:
    def __init__(self, coordinator, security_ids: dict[str, int], transport, clock=None) -> None:
        self.coordinator = coordinator
        self.by_id = {int(v): k for k, v in security_ids.items()}
        self.transport = transport
        self.clock = clock
        self._last_price: dict[str, float] = {}

    def handle_frame(self, msg: dict) -> int:
        sid = msg.get("security_id")
        symbol = self.by_id.get(int(sid)) if sid is not None else msg.get("symbol")
        if symbol is None or symbol not in self.coordinator.engines:
            return 0
        price = float(msg.get("ltp") or 0.0)
        vol = float(msg.get("volume") or 0.0)
        if price <= 0:
            return 0
        prev = self._last_price.get(symbol)
        self._last_price[symbol] = price
        if prev is None:
            delta = 0.0
        else:
            # tick rule: direction of price change carries the signed volume
            delta = (1.0 if price > prev else (-1.0 if price < prev else 0.0)) * vol
        ts = float(msg.get("ts") or 0.0)
        self.coordinator.on_tick(symbol, ts, price, vol, delta)
        return 1

    def run_once(self) -> int:
        n = 0
        for frame in self.transport.frames():
            n += self.handle_frame(frame)
        return n
```

(`run()` long-loop + reconnect is runner/Task 15 territory; keep feed pure.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/dhan_feed.py tests/quantv2/test_dhan_feed.py
git commit -m "feat(quantv2): transport-injectable Dhan tick feed"
```

### Task 14: Dhan REST broker + reconciliation

**Files:**
- Create: `quantv2/dhan_broker.py`
- Create: `tests/quantv2/test_dhan_broker.py`

**Interfaces:**
- Consumes: `BrokerPort` (Task 5), `Signal`, `Position`.
- Produces: `RestPort` Protocol (`place(order: dict) -> dict`, `orders() -> list`, `positions() -> list`), `DhanBroker(rest, product="MIS")` implementing `submit(signal, qty) -> Position` (places MARKET order, then polls `orders()` until filled or raises `SubmitError`), `reconcile(positions, broker_positions) -> list[str]` (mismatch descriptions, empty = clean).

- [ ] **Step 1: Write the failing test**

```python
from quantv2.dhan_broker import DhanBroker, SubmitError, reconcile
from quantv2.types import Signal
import pytest

class FakeRest:
    def __init__(self):
        self.placed = []
        self._fills = []
    def place(self, order: dict) -> dict:
        self.placed.append(order)
        return {"orderId": f"o{len(self.placed)}", "orderStatus": "PENDING"}
    def orders(self):
        return self._fills

def test_submit_polls_to_filled():
    rest = FakeRest()
    b = DhanBroker(rest)
    sig = Signal(type="LONG", entry=100.0, sl=99.0, tp=102.0, rr=2.0, setup="T", symbol="NF", timestamp="t")
    rest._fills = [{"orderId": "o1", "orderStatus": "TRADED", "filledQty": 75, "averageTradedPrice": 100.1}]
    pos = b.submit(sig, 75.0)
    assert pos.qty == 75.0 and pos.entry == 100.1 and pos.side == "LONG"

def test_unfilled_raises():
    rest = FakeRest()
    b = DhanBroker(rest, poll_attempts=1)
    sig = Signal(type="LONG", entry=100.0, sl=99.0, tp=102.0, rr=2.0, setup="T", symbol="NF", timestamp="t")
    with pytest.raises(SubmitError):
        b.submit(sig, 75.0)

def test_reconcile_reports_mismatch():
    class P:
        def __init__(self, symbol, qty):
            self.symbol = symbol
            self.qty = qty
    out = reconcile([P("NF", 75)], [P("NF", 150)])
    assert out and "NF" in out[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_dhan_broker.py -v`
Expected: FAIL (no module)

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations
import time
from typing import Protocol
from quantv2.oms import Position
from quantv2.types import Signal

class SubmitError(Exception):
    pass

class RestPort(Protocol):
    def place(self, order: dict) -> dict: ...
    def orders(self) -> list: ...

_SIDE = {"LONG": "BUY", "SHORT": "SELL"}

class DhanBroker:
    def __init__(self, rest: RestPort, product: str = "MIS", poll_attempts: int = 20, poll_delay: float = 0.25) -> None:
        self.rest = rest
        self.product = product
        self.poll_attempts = poll_attempts
        self.poll_delay = poll_delay

    def submit(self, signal: Signal, qty: float) -> Position:
        order = {
            "securityId": signal.symbol,
            "transactionType": _SIDE[signal.type],
            "quantity": int(qty),
            "orderType": "MARKET",
            "productType": self.product,
        }
        resp = self.rest.place(order)
        oid = resp.get("orderId")
        if not oid:
            raise SubmitError(f"no orderId: {resp}")
        for _ in range(self.poll_attempts):
            for o in self.rest.orders():
                if o.get("orderId") == oid and o.get("orderStatus") == "TRADED":
                    return Position(
                        pid=str(oid), symbol=signal.symbol, side=signal.type,
                        qty=float(o.get("filledQty") or qty),
                        entry=float(o.get("averageTradedPrice") or signal.entry),
                        sl=signal.sl, tp=signal.tp, setup=signal.setup, opened_at=signal.timestamp,
                    )
            time.sleep(self.poll_delay)
        raise SubmitError(f"order {oid} not filled in {self.poll_attempts} polls")

def reconcile(ours: list, theirs: list) -> list[str]:
    a = {getattr(p, "symbol", None): float(getattr(p, "qty", 0.0)) for p in ours}
    b = {getattr(p, "symbol", None): float(getattr(p, "qty", 0.0)) for p in theirs}
    out = []
    for sym in sorted(set(a) | set(b)):
        if a.get(sym, 0.0) != b.get(sym, 0.0):
            out.append(f"{sym}: ours={a.get(sym, 0.0)} broker={b.get(sym, 0.0)}")
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/dhan_broker.py tests/quantv2/test_dhan_broker.py
git commit -m "feat(quantv2): Dhan REST broker, fill poll, reconcile"
```

### Task 15: runner (composition root + paper-live flag + EOD watchdog)

**Files:**
- Create: `quantv2/runner.py`
- Create: `tests/quantv2/test_runner.py`

**Interfaces:**
- Consumes: Coordinator, Engine, DhanFeed, BrokerAdapter, SessionClock, SessionRisk, store, snapshot.
- Produces: `RunnerConfig` (symbols, interval_sec, risk_cap, equity, risk limits, lots path, mode "paper"|"live", store path, state interval), `Runner.build(config) -> Runner`, `Runner.step(frame: dict) -> int` (one transport frame through feed), `Runner.tick_watchdog(now) -> None` (EOD flatten + halt all when clock says force-exit), `Runner.save_state()`, `Runner.snapshot() -> dict`. No infinite loop in code (runner loop lives in `__main__` / operator scripts) — keeps it testable.

- [ ] **Step 1: Write the failing test**

```python
from quantv2.runner import Runner, RunnerConfig

def test_runner_paper_step_and_watchdog():
    cfg = RunnerConfig(symbols=["NF"], interval_sec=60, mode="paper", equity=100000.0)
    r = Runner.build(cfg)
    n = r.step({"security_id": r.security_ids["NF"], "ltp": 100.0, "volume": 1.0, "ts": 60.0})
    assert n == 1
    r.tick_watchdog(15.5 * 3600 + 25 * 60)  # 15:25 IST as loose epoch (clock works on IST wall time)
    snap = r.snapshot()
    assert "NF" in snap and snap["NF"]["position"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_runner.py -v`
Expected: FAIL (no module)

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from quantv2.coordinator import Coordinator
from quantv2.engine import Engine
from quantv2.oms import PaperOMS
from quantv2.broker import BrokerAdapter
from quantv2.clock import SessionClock
from quantv2.session_risk import RiskLimits, SessionRisk
from quantv2.dhan_feed import DhanFeed
from quantv2.store import save
from quantv2.snapshot import snapshot
from quantv2.exits import ExitConfig

@dataclass
class RunnerConfig:
    symbols: list[str]
    interval_sec: int = 300
    mode: str = "paper"
    equity: float = 100000.0
    risk_cap: float = 100000.0
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    store_path: str = "quantv2_state.json"
    state_interval_s: float = 30.0

class Runner:
    def __init__(self, config: RunnerConfig, coordinator: Coordinator, feed: DhanFeed, clock: SessionClock, broker: BrokerAdapter) -> None:
        self.config = config
        self.coordinator = coordinator
        self.feed = feed
        self.clock = clock
        self.broker = broker
        self.halted = False
        self.security_ids = feed.by_id_inverted()
        self._since_save = 0.0

    @classmethod
    def build(cls, config: RunnerConfig, transport=None, security_ids: dict[str, int] | None = None) -> "Runner":
        clock = SessionClock()
        c = Coordinator(risk_cap=config.risk_cap)
        for sym in config.symbols:
            eng = Engine(symbol=sym, interval_sec=config.interval_sec, oms=PaperOMS(), equity=config.equity, clock=clock, risk=SessionRisk(config.risk_limits), exit_cfg=ExitConfig())
            c.add(eng)
        broker = BrokerAdapter(mode=config.mode, oms=PaperOMS(), live_port=None)
        feed = DhanFeed(c, security_ids or {s: i + 1 for i, s in enumerate(config.symbols)}, transport, clock=clock)
        return cls(config, c, feed, clock, broker)

    def step(self, frame: dict) -> int:
        return self.feed.handle_frame(frame)

    def tick_watchdog(self, now: float) -> None:
        if not self.halted and self.clock.force_exit(now):
            self.coordinator.eod_flatten("SESSION_CLOSE")
            self.halted = True
            for eng in self.coordinator.engines.values():
                eng.can_trade = False

    def maybe_save(self, dt: float) -> None:
        self._since_save += dt
        if self._since_save >= self.config.state_interval_s:
            self.save_state()
            self._since_save = 0.0

    def save_state(self) -> None:
        save(self.coordinator, self.config.store_path)

    def snapshot(self) -> dict:
        return snapshot(self.coordinator)
```

`DhanFeed` needs `by_id_inverted() -> dict[symbol→id]` (one-liner added in this task). `Engine.__init__` accepts `clock`/`risk` (already from Tasks 10/11). If the watchdog epoch test is awkward (clock uses IST minutes-of-day), the test may pass `now` as a real IST timestamp built via `datetime(..., tzinfo=IST).timestamp()` — adjust the test to that form rather than complicating the clock. Record whichever form the implementer uses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/runner.py quantv2/dhan_feed.py tests/quantv2/test_runner.py
git commit -m "feat(quantv2): production runner composition root"
```

### Task 16: observability (structured decision log)

**Files:**
- Create: `quantv2/journal.py`
- Create: `tests/quantv2/test_journal.py`

**Interfaces:**
- Produces: `Journal(path)` with `.log_decision(symbol, decision)`, `.log_fill(symbol, fill)`, `.lines() -> list[str]` (JSON-per-line, stdlib `logging`-free, file-appended); runner logs every non-None decision and every fill.

- [ ] **Step 1: Write the failing test**

```python
from quantv2.journal import Journal
from quantv2.types import Decision

def test_journal_roundtrip(tmp_path):
    j = Journal(str(tmp_path / "j.jsonl"))
    j.log_decision("X", Decision(False, "NO_EDGE"))
    j.log_decision("X", Decision(True, "TRIPLE_A"))
    lines = j.lines()
    assert len(lines) == 2 and '"TRIPLE_A"' in lines[1] and '"NO_EDGE"' in lines[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quantv2/test_journal.py -v`
Expected: FAIL (no module)

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations
import json
from dataclasses import asdict, is_dataclass

class Journal:
    def __init__(self, path: str) -> None:
        self.path = path

    def _write(self, record: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def log_decision(self, symbol: str, decision) -> None:
        self._write({"kind": "decision", "symbol": symbol, "reason": decision.reason, "approved": decision.approved})

    def log_fill(self, symbol: str, fill) -> None:
        self._write({"kind": "fill", "symbol": symbol, **{k: getattr(fill, k) for k in ("pid", "qty", "price", "pnl", "reason")}})

    def lines(self) -> list[str]:
        try:
            with open(self.path) as f:
                return [ln.strip() for ln in f if ln.strip()]
        except OSError:
            return []
```

Runner wiring: `Runner.build` accepts optional `journal`; `step` logs non-None decisions after routing; engine currently returns Decisions only — fill logging happens in `tick_watchdog`/EOD path only (paper close fills) — acceptable scope, note in report.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/quantv2/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantv2/journal.py quantv2/runner.py tests/quantv2/test_journal.py
git commit -m "feat(quantv2): decision journal"
```

## Phase B (follow-up plan, NOT this one)

Option selection, underlying-futures subscription + AMT, signal→option translation, expiry/halving sizing, WS snapshot endpoint, backend/FastAPI composition. Draft after paper-live green.
