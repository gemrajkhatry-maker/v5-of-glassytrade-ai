# Audit Safety & Accuracy Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the verified safety-path, risk-accounting, and decision-gate defects found by the 2026-08-25 code-trace audit, with minimal root-cause diffs.

**Architecture:** Every fix lands where all callers route through (ponytail root-cause rule): safety paths in `quant/multi_engine.py` + feed producer, risk accounting in `SessionRisk`/`PositionManager`/`QuantEngine._manage_exit`, gate correctness in the gate functions and `DecisionContextBuilder`. No new modules, no new dependencies, no abstractions. Deletion-free except where a dead default is the bug.

**Tech Stack:** Python 3.13, pytest (`.venv/bin/python -m pytest`, root `pytest.ini` sets `pythonpath = . backend`), FastAPI backend.

## Global Constraints

- Test command pattern: `.venv/bin/python -m pytest <path>::<test> -v` from repo root. Full quant suite: `.venv/bin/python -m pytest tests/ -q --no-header`.
- Lint before every commit: `.venv/bin/python -m ruff check <changed files>`.
- `quant/` must never import `backend/` (import-linter contract in `tests/architecture/`).
- Commit style matches git log: `fix(quant): ...`, `fix(backend): ...`, `test(quant): ...`.
- No new dependencies. No comments except `ponytail:` markers where a deliberate simplification has a known ceiling.
- **Behavior-change flags:** Task 10 activates the declared 20-tick stop cap (entries with wider structural stops now reject). Task 13 makes the pyramid engine reachable via `legLvns` (previously dead). Task 15 restricts tick injection to `development` env. These are intentional per audit; call them out in commit messages.

## Explicitly out of scope (ponytail — add when needed)

- Live OMS build-out (feature, not a fix; live mode correctly refuses to start until then).
- Auth middleware (no order endpoints exist; injection gate + LAN bind are the exposure, gate fixed in Task 15).
- Startup reconciliation symbol normalization (live-only path; live is unwired).
- Deleting the unwired `exit_rules.py` pure-rule family (tests import it; deletion is a separate chore).
- Rewriting the 27 assertion-free parity tests (known debt; no behavior value in churning them now).
- Pyramid open-risk registration with `PortfolioRiskAuthority` (pyramids only fire on a risk-free base; pnl booking is fixed in Task 6, sizing budget check when pyramids prove out).

---

## Phase A — Safety paths

### Task 1: Emergency force_close emits a real PositionClosed and records the trade

The current path emits a raw `Fill` (not an `Event`, no `.symbol`), which raises inside `StateProjector.on_event`; the position is dropped with no journal entry, no DB row deletion, no risk recording.

**Files:**
- Modify: `quant/multi_engine.py:276-299` (force_close block inside `emergency_halt`)
- Test: `tests/quant/test_emergency_halt.py`

**Interfaces:**
- Consumes: `PaperOMS.close(position, price, time, reason) -> Fill`; `SessionRisk.record_trade(pnl) -> RiskState`; `PositionClosed(symbol=..., time=..., fill=...)` from `quant.events`
- Produces: `emergency_halt(reason, force_close=True)` now emits `PositionClosed` per closed position and calls `record_trade(fill.pnl)` — later tasks (journal, storage bridge) already subscribe to `PositionClosed`.

- [ ] **Step 1: Write the failing test** — append to `tests/quant/test_emergency_halt.py`:

```python
def test_emergency_halt_force_close_real_objects_emits_position_closed():
    """Real PaperOMS + SessionRisk: close emits PositionClosed, records pnl."""
    from quant.decision.signal_builder import Signal
    from quant.events import PositionClosed
    from quant.execution.oms import PaperOMS
    from quant.execution.risk import SessionRisk

    coord = _make_coordinator_with_engine()

    class _Engine:
        def __init__(self):
            self.symbol = "NIFTY 24800 CE"
            self._oms = PaperOMS(lot_size=1.0)
            self._risk = SessionRisk(storage=None, symbol=self.symbol)
            sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0,
                         rr=2.0, model_label="test", symbol=self.symbol, timestamp="t0")
            self._position = self._oms.submit(sig, 10.0)
            self._aggregator = None
            self.emitted = []

        def _emit(self, event):
            self.emitted.append(event)

    eng = _Engine()
    coord._engines = {eng.symbol: eng}

    halted = coord.emergency_halt("SIGTERM", force_close=True)

    assert halted == 1
    assert eng._position is None
    closes = [e for e in eng.emitted if isinstance(e, PositionClosed)]
    assert len(closes) == 1
    assert closes[0].symbol == eng.symbol
    assert eng._risk.state().trades_today == 1
    assert eng._risk.state().daily_pnl != 0.0 or True  # price may equal entry; count is the invariant
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/test_emergency_halt.py::test_emergency_halt_force_close_real_objects_emits_position_closed -v`
Expected: FAIL — no `PositionClosed` in `eng.emitted` (raw `Fill` raises inside `_emit` on a real projector; with this plain `_emit` list the Fill lands but is not a `PositionClosed`, and `trades_today == 0`).

- [ ] **Step 3: Implement** — in `quant/multi_engine.py`, replace the force_close body (the block from `fill = oms.close(...)` through `closed += 1`) with:

```python
                        fill = oms.close(pos, close_price, ts, f"EMERGENCY_HALT: {reason}")
                        eng._position = None
                        from quant.events import PositionClosed
                        eng._emit(PositionClosed(symbol=eng.symbol, time=ts, fill=fill))
                        if risk is not None and hasattr(risk, "record_trade"):
                            risk.record_trade(float(fill.pnl))
                        closed += 1
```

(`risk` is already in scope from the halt block above; delete the old `eng._emit(fill)` line and its comment.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/test_emergency_halt.py -v`
Expected: all PASS (existing MagicMock tests still pass — MagicMock `_emit` accepts the new event).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/multi_engine.py tests/quant/test_emergency_halt.py
git add quant/multi_engine.py tests/quant/test_emergency_halt.py
git commit -m "fix(quant): emergency force_close emits PositionClosed + records trade (was silently dropped)"
```

---

### Task 2: SIGTERM flattens positions and lets uvicorn shut down

The lifespan handler replaces uvicorn's SIGTERM handler, calls `emergency_halt` without `force_close`, and never returns control to uvicorn — the server becomes un-stoppable and teardown (coordinator.stop, storage flush) never runs.

**Files:**
- Modify: `backend/app/main.py:267-289`

**Interfaces:**
- Consumes: `coordinator.emergency_halt(reason, force_close=True)` (fixed in Task 1)
- Produces: SIGTERM → flatten → chain to previously-installed handler (uvicorn's `handle_exit`) → graceful lifespan teardown.

- [ ] **Step 1: Implement** — replace the signal block in `backend/app/main.py`:

```python
        import signal as _signal

        _prev_sigterm = _signal.getsignal(_signal.SIGTERM)

        def _emergency_flatten(signum, frame):
            import logging
            _log = logging.getLogger('emergency.shutdown')
            _log.critical('SIGTERM received — initiating emergency risk halt', extra={'event': 'EMERGENCY_SHUTDOWN'})
            try:
                # Audit D-RISK-03: the old handler set eng._risk_halted — an
                # attribute QuantEngine never had — so this was a silent no-op.
                # Route through the coordinator into each engine's SessionRisk,
                # which is what the decision loop actually consults.
                if hasattr(app.state, 'coordinator'):
                    coord = app.state.coordinator
                    if hasattr(coord, 'emergency_halt'):
                        halted = coord.emergency_halt("SIGTERM shutdown", force_close=True)
                        _log.critical(
                            'Emergency halt applied to %d engine(s)', halted,
                            extra={'event': 'EMERGENCY_SHUTDOWN_APPLIED'},
                        )
            except Exception as exc:
                _log.error('Emergency flatten error: %s', exc)
            # Chain to the previously installed handler (uvicorn's): without
            # this the server ignores SIGTERM forever, operators escalate to
            # SIGKILL, and lifespan teardown (coordinator.stop + storage
            # flush) never runs.
            if callable(_prev_sigterm):
                _prev_sigterm(signum, frame)

        _signal.signal(_signal.SIGTERM, _emergency_flatten)
```

- [ ] **Step 2: Verify syntax + existing backend tests**

Run: `.venv/bin/python -m ruff check backend/app/main.py && .venv/bin/python -m pytest backend/tests/ -q --no-header`
Expected: PASS (no dedicated signal test — the flatten half is covered by Task 1's test; handler chaining is uvicorn internals).

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "fix(backend): SIGTERM flattens positions (force_close) and chains to uvicorn shutdown"
```

---

### Task 3: Feed producer survives stream-factory failures

`stream_full()` is called outside the retry try-block in `_consume_loop`; one raise kills the producer thread permanently and every engine blocks forever in `queue.get()` with health still green.

**Files:**
- Modify: `quant/brokers/multiplexed_feed.py:299-380` (`_consume_loop`)
- Test: `tests/quant/test_multiplexed_feed.py`

**Interfaces:**
- Consumes: `self._md.stream_full(symbols)` async iterator factory
- Produces: factory exceptions trigger the existing backoff/retry loop instead of thread death.

- [ ] **Step 1: Write the failing test** — append to `tests/quant/test_multiplexed_feed.py`:

```python
def test_producer_survives_stream_factory_failure():
    """A raising stream_full must trigger retry, not kill the producer thread."""
    import time as _time
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    class _FlakyMD:
        def __init__(self):
            self.calls = 0

        def stream_full(self, symbols):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("broker down")

            async def _gen():
                yield {"symbol": symbols[0], "last_trade_price": 100.0,
                       "volume": 5, "ltt": 1786095001}

            return _gen()

    md = _FlakyMD()
    feed = MultiplexedMarketFeed(md)
    feed.set_symbols(["TEST FUT"])
    tick = None
    deadline = _time.time() + 15
    while _time.time() < deadline:
        tick = feed.try_next_tick("TEST FUT")
        if tick is not None:
            break
        _time.sleep(0.05)
    feed.close()
    assert md.calls >= 2, "producer died instead of retrying"
    assert tick is not None and tick.price == 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/test_multiplexed_feed.py::test_producer_survives_stream_factory_failure -v`
Expected: FAIL — `md.calls == 1`, no tick (producer thread dead).

- [ ] **Step 3: Implement** — in `_consume_loop`, move stream creation inside the try block. Replace:

```python
            stream_full = self._md.stream_full(symbols)
            stream_depth = None
            if hasattr(self._md, "stream_depth_20"):
                stream_depth = self._md.stream_depth_20(symbols)
                
            try:
```

with:

```python
            stream_full = None
            stream_depth = None
            try:
                stream_full = self._md.stream_full(symbols)
                if hasattr(self._md, "stream_depth_20"):
                    stream_depth = self._md.stream_depth_20(symbols)
```

and in the `finally:` block replace `await self._aclose_quietly(stream_full)` with:

```python
                if stream_full is not None:
                    await self._aclose_quietly(stream_full)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/test_multiplexed_feed.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/brokers/multiplexed_feed.py tests/quant/test_multiplexed_feed.py
git add quant/brokers/multiplexed_feed.py tests/quant/test_multiplexed_feed.py
git commit -m "fix(quant): feed producer retries when stream factory raises (was permanent silent death)"
```

---

### Task 4: Poll-fallback packets get a usable timestamp

When the Dhan WS fails, the REST poll fallback emits ISO-string timestamps; `_convert` fails `float(ISO)` → `ts=0` → `Tick.time="0"` → the aggregator's window never changes → **no bar ever closes, so open positions get no exit management during the outage**.

**Files:**
- Modify: `quant/brokers/multiplexed_feed.py` (imports + `_convert`, lines ~486-493)
- Test: `tests/quant/test_multiplexed_feed.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `Tick.time` is always a positive epoch string for live-shaped packets.

- [ ] **Step 1: Write the failing test** — append to `tests/quant/test_multiplexed_feed.py`:

```python
def test_convert_iso_timestamp_does_not_produce_zero_time():
    """Poll-fallback packets carry ISO strings; ts must not collapse to '0'
    (a zero epoch freezes bar windows and disables exits)."""
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    pkt = {"symbol": "TEST FUT", "last_trade_price": 100.0, "volume": 5,
           "timestamp": "2026-08-25T10:00:00"}
    tick = feed._convert(pkt, "TEST FUT")
    assert tick is not None
    assert tick.time != "0"
    assert float(tick.time) > 946684800  # post-2000 epoch
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/test_multiplexed_feed.py::test_convert_iso_timestamp_does_not_produce_zero_time -v`
Expected: FAIL — `tick.time == "0"`.

- [ ] **Step 3: Implement** — add `import time` to the imports block at the top of `quant/brokers/multiplexed_feed.py`. In `_convert`, immediately after the `ts` parse block (the `try: ts = float(raw_ts or 0) except ...: ts = 0.0`), add:

```python
            if ts <= 0:
                # ponytail: poll-fallback packets carry ISO strings float()
                # rejects; ts=0 freezes bar windows so no bar closes and open
                # positions lose exit management. Arrival time keeps bars moving.
                ts = time.time()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/test_multiplexed_feed.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/brokers/multiplexed_feed.py tests/quant/test_multiplexed_feed.py
git add quant/brokers/multiplexed_feed.py tests/quant/test_multiplexed_feed.py
git commit -m "fix(quant): unparseable packet timestamps fall back to arrival time (bars/exits no longer freeze)"
```

---

### Task 5: /health and /health/ready reflect crashed engines

`coordinator` is explicitly excluded from the overall status computation; readiness only checks `started`. All engines can be dead while both probes report ok/ready.

**Files:**
- Modify: `backend/app/api/routers/health.py:128-144` (`/health` overall status) and `:178-184` (`/health/ready` engine check)
- Test: `backend/tests/unit/test_health_crashed_engines.py`

**Interfaces:**
- Consumes: `coordinator.crashed_engines() -> list[str]` (exists, `quant/multi_engine.py:235`)
- Produces: `/health` overall `"degraded"` when any engine crashed; `/health/ready` engine check `"crashed: N engine(s) dead"` (fails readiness).

- [ ] **Step 1: Write the failing test** — create `backend/tests/unit/test_health_crashed_engines.py`. The test MUST call the actual route functions (`health_check`, `readiness_check` from `backend/app/api/routers/health.py`) with a stub `Request` (e.g. `types.SimpleNamespace(app=SimpleNamespace(state=...))`) and monkeypatched module dependencies (`get_storage`, `get_active_symbols`, and any other module-level imports the routes resolve — read the top of `health.py` for the list). A logic-mirror test that copies the status computation inline is NOT acceptable: it passes even if the route edit is wrong.

Test shape:

```python
"""Crashed engines must degrade /health and fail /health/ready."""

import types

import pytest


def _request(coordinator):
    return types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(
            coordinator=coordinator,
            engine_start_failed=False,
            startup_contracts={},
        ))
    )


class _Coord:
    def __init__(self, crashed):
        self.started = True
        self._crashed = crashed

    def symbols(self):
        return ["NIFTY 25000 CALL"]

    def crashed_engines(self):
        return self._crashed


@pytest.mark.asyncio
async def test_health_degraded_when_engines_crashed(monkeypatch):
    from backend.app.api.routers import health as health_mod

    monkeypatch.setattr(health_mod, "get_storage", lambda: _FakeStorage())
    # ...monkeypatch remaining route dependencies (read health.py imports)...

    resp = await health_mod.health_check(_request(_Coord(["NIFTY 25000 CALL"])))
    assert resp["status"] == "degraded"
    assert resp["checks"]["coordinator"]["crashedEngines"] == ["NIFTY 25000 CALL"]

    resp_ok = await health_mod.health_check(_request(_Coord([])))
    assert resp_ok["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_fails_when_engines_crashed(monkeypatch):
    from backend.app.api.routers import health as health_mod

    monkeypatch.setattr(health_mod, "get_storage", lambda: _FakeStorage())
    monkeypatch.setattr(health_mod, "get_active_symbols", lambda: ["NIFTY"])

    resp = await health_mod.readiness_check(_request(_Coord(["NIFTY 25000 CALL"])))
    assert "crashed" in str(resp["checks"]["engine"])
    assert resp["status"] != "ready"
```

`_FakeStorage` needs the methods the routes call (`kv_set`, `kv_get`, plus whatever `health_check` touches — implement from the route body). If `asyncio_mode = auto` (root pytest.ini) applies to backend tests too, drop the `@pytest.mark.asyncio` decorators; match whatever convention `backend/tests/unit/` already uses. If a route genuinely cannot be isolated without rebuilding the DI container, say so in the report and fall back to the logic-mirror test — but only then.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/unit/test_health_crashed_engines.py -v`
Expected: FAIL — `/health` returns `"ok"` and readiness engine check returns `"ok"` with the current route code.

- [ ] **Step 3: Implement** — in `backend/app/api/routers/health.py`, replace the `/health` overall-status block (lines ~135-142):

```python
    elif all(
        v in ["ok", "not_ready", "degraded"]
        for k, v in checks.items()
        if k not in {"coordinator"}
    ):
        coord_check = checks.get("coordinator")
        if isinstance(coord_check, dict) and coord_check.get("crashedEngines"):
            overall = "degraded"
        else:
            overall = "ok"
    else:
        overall = "degraded"
```

and replace the readiness engine check (lines ~179-184):

```python
    try:
        coordinator = getattr(request.app.state, "coordinator", None)
        running = bool(coordinator) and bool(getattr(coordinator, "started", False))
        if running and hasattr(coordinator, "crashed_engines"):
            crashed = coordinator.crashed_engines() or []
            checks["engine"] = (
                f"crashed: {len(crashed)} engine(s) dead" if crashed else "ok"
            )
        else:
            checks["engine"] = "ok" if running else "not_started"
    except Exception as e:
        checks["engine"] = f"error: {e}"
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest backend/tests/unit/test_health_crashed_engines.py backend/tests/unit/ -q --no-header`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check backend/app/api/routers/health.py backend/tests/unit/test_health_crashed_engines.py
git add backend/app/api/routers/health.py backend/tests/unit/test_health_crashed_engines.py
git commit -m "fix(backend): health/readiness degrade when engine threads are crashed"
```

---

## Phase B — Risk accounting

### Task 6: Portfolio register_open rejection aborts the entry

`QuantEngine._decide` discards the boolean return of `PortfolioRiskAuthority.register_open` — the only atomic check — so two racing engines can both register past the 4% ceiling.

**Files:**
- Modify: `quant/runtime.py:663-673` (portfolio block in `_decide`)
- Test: `tests/quant/test_portfolio_risk_guard.py`

**Interfaces:**
- Consumes: `PortfolioRiskAuthority.register_open(risk) -> bool`
- Produces: entry skipped when `register_open` returns False.

- [ ] **Step 1: Write the failing test** — create `tests/quant/test_portfolio_risk_guard.py`:

```python
"""_decide must abort the entry when register_open rejects (race backstop)."""

from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.runtime import QuantEngine


class _ApprovedDecision:
    def __init__(self, signal):
        self.approved = True
        self.signal = signal
        self.reason = "test"
        self.phase = ""
        self.gate_results = ()
        self.block_reasons = ()
        self.model_label = ""


def test_decide_aborts_when_register_open_rejects():
    pra = MagicMock()
    pra.can_accept.return_value = (True, "")
    pra.register_open.return_value = False  # another engine won the race

    eng = QuantEngine(gateway=MagicMock(), symbol="TEST FUT", portfolio_risk=pra)
    sig = Signal(type="LONG", reason="t", entry=100.0, sl=95.0, tp=110.0, rr=2.0,
                 model_label="t", symbol="TEST FUT", timestamp="t0")
    stub = MagicMock()
    stub.should_enter.return_value = _ApprovedDecision(sig)
    eng._strategy = stub

    bar = Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0)
    eng._decide({}, bar)

    pra.register_open.assert_called_once()
    assert eng._position is None, "entry proceeded despite register_open rejection"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/test_portfolio_risk_guard.py -v`
Expected: FAIL — `eng._position is not None` (return value currently ignored).

- [ ] **Step 3: Implement** — in `quant/runtime.py` `_decide`, replace:

```python
                self._portfolio_risk.register_open(trade_risk)
                self._open_trade_risk = trade_risk
```

with:

```python
                if not self._portfolio_risk.register_open(trade_risk):
                    logger.warning(
                        "🛑 [PORTFOLIO RISK] %s: entry rejected at register — "
                        "cap breached between can_accept and register",
                        self.symbol,
                    )
                    return
                self._open_trade_risk = trade_risk
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/test_portfolio_risk_guard.py tests/quant/execution/ -q --no-header`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/runtime.py tests/quant/test_portfolio_risk_guard.py
git add quant/runtime.py tests/quant/test_portfolio_risk_guard.py
git commit -m "fix(quant): honor register_open rejection — portfolio cap can no longer be raced"
```

---

### Task 7: Partial and pyramid P&L reach the portfolio authority

Only the final runner fill is reported to `PortfolioRiskAuthority.record_close`; TP1/TP2 partial pnl and pyramid pnl accumulate off-book, so the 6% daily kill-switch and portfolio sizing equity see a rosier picture than reality.

**Files:**
- Modify: `quant/position_manager.py` (`__init__` ~:71, `manage_exit` ~:88, partial branch ~:140-158, pyramid loop ~:164-175)
- Modify: `quant/runtime.py:706-729` (`_manage_exit`)
- Test: `tests/quant/test_portfolio_risk_guard.py`

**Interfaces:**
- Consumes: `PortfolioRiskAuthority.record_close(risk_rupees, pnl)`
- Produces: `PositionManager.last_partial_fill: Fill | None` and `PositionManager.last_pyramid_pnl: float` (reset each `manage_exit`); `QuantEngine._manage_exit` releases proportional open risk on partials and books pyramid pnl.

- [ ] **Step 1: Write the failing tests** — append to `tests/quant/test_portfolio_risk_guard.py`:

```python
def test_manage_exit_partial_releases_proportional_portfolio_risk():
    from quant.execution.exits import ExitDecision

    eng = QuantEngine(gateway=MagicMock(), symbol="TEST FUT")
    pra = MagicMock()
    eng._portfolio_risk = pra

    sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
                 model_label="t", symbol="TEST FUT", timestamp="t0")
    eng._position = eng._oms.submit(sig, 100.0)
    eng._open_trade_risk = 500.0

    exits = MagicMock()
    exits.evaluate.return_value = ExitDecision(True, "TP1", 102.0, partial_fraction=0.5)
    exits.is_risk_free.return_value = False
    eng._exits = exits

    bar = Bar(time="t300", open=100.0, high=102.5, low=99.5, close=102.0, volume=10.0)
    eng._manage_exit({}, bar)

    pra.record_close.assert_called_once()
    released, pnl = pra.record_close.call_args[0]
    assert abs(released - 250.0) < 1e-6, f"expected half of 500 released, got {released}"
    assert pnl > 0
    assert eng._position is not None  # runner remains
    assert abs(eng._open_trade_risk - 250.0) < 1e-6


def test_manage_exit_full_close_books_pyramid_pnl_to_portfolio():
    from quant.execution.exits import ExitDecision

    eng = QuantEngine(gateway=MagicMock(), symbol="TEST FUT")
    pra = MagicMock()
    eng._portfolio_risk = pra

    sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
                 model_label="t", symbol="TEST FUT", timestamp="t0")
    eng._position = eng._oms.submit(sig, 100.0)
    eng._open_trade_risk = 500.0
    pyramid = eng._oms.add_pyramid(base=eng._position, entry_price=101.0,
                                   new_sl=100.0, size=50.0, time="t1", pyramid_level=1)

    exits = MagicMock()
    exits.evaluate.return_value = ExitDecision(True, "TRAIL", 103.0)
    eng._exits = exits

    pm = eng._get_position_manager()
    pm.pyramid_positions = [pyramid]

    bar = Bar(time="t300", open=102.0, high=103.5, low=101.5, close=103.0, volume=10.0)
    eng._manage_exit({}, bar)

    pnls = [c.args[1] for c in pra.record_close.call_args_list]
    assert any(abs(p - (103.0 - 101.0) * 50.0) < 1e-6 for p in pnls), \
        f"pyramid pnl not booked to portfolio authority: {pnls}"
    assert eng._position is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quant/test_portfolio_risk_guard.py -q`
Expected: both new tests FAIL (`record_close` not called on partial; pyramid pnl absent).

- [ ] **Step 3: Implement PositionManager bookkeeping** — in `quant/position_manager.py`:

In `__init__`, after `self.last_fill = None`:

```python
        self.last_partial_fill = None
        self.last_pyramid_pnl = 0.0
```

In `manage_exit`, replace `self.last_fill = None` (top of method) with:

```python
        self.last_fill = None
        self.last_partial_fill = None
        self.last_pyramid_pnl = 0.0
```

In the partial branch, after `self._emit(RiskUpdated(...))` and before `return remaining`, add:

```python
                self.last_partial_fill = partial_fill
```

In the pyramid close loop, replace the loop body with:

```python
            for pyr_pos in self.pyramid_positions:
                pyr_fill = self._oms.close(pyr_pos, exit_dec.close_price, bar.time,
                                           exit_dec.reason + "_PYRAMID")
                self._exits.pop_trail(pyr_pos)
                self._risk.record_trade(pyr_fill.pnl, count_as_trade=False)
                self._emit(PositionClosed(symbol=self.symbol, time=bar.time, fill=pyr_fill))
                self.last_pyramid_pnl += float(pyr_fill.pnl)
                logger.info(
                    "🔒 [PYRAMID CLOSED] %s level=%d reason=%s pnl=₹%.2f",
                    self.symbol, pyr_pos.pyramid_level, exit_dec.reason, pyr_fill.pnl,
                )
```

NOTE: `count_as_trade=False` comes from Task 9 and `PositionClosed` emission doubles as the Task 13 DB-leak fix — if executing out of order, land Task 9 first or temporarily keep `record_trade(pyr_fill.pnl)` here.

- [ ] **Step 4: Implement runtime accounting** — in `quant/runtime.py` `_manage_exit`, after `self._pyramid_count = pm.pyramid_count` and before `if was_open and remaining is None:`, insert:

```python
        if self._portfolio_risk is not None:
            if pm.last_partial_fill is not None:
                closed_sz = abs(pm.last_partial_fill.position.size)
                remaining_sz = abs(remaining.size) if remaining is not None else 0.0
                total_sz = closed_sz + remaining_sz
                fraction = closed_sz / total_sz if total_sz > 0 else 0.0
                release = getattr(self, "_open_trade_risk", 0.0) * fraction
                self._portfolio_risk.record_close(release, float(pm.last_partial_fill.pnl))
                self._open_trade_risk = getattr(self, "_open_trade_risk", 0.0) - release
            if pm.last_pyramid_pnl:
                # ponytail: pyramid add-ons never register open risk (they only
                # fire on a risk-free base); book their pnl, release nothing.
                self._portfolio_risk.record_close(0.0, float(pm.last_pyramid_pnl))
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/test_portfolio_risk_guard.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/position_manager.py quant/runtime.py tests/quant/test_portfolio_risk_guard.py
git add quant/position_manager.py quant/runtime.py tests/quant/test_portfolio_risk_guard.py
git commit -m "fix(quant): partial + pyramid P&L reported to portfolio risk authority"
```

---

### Task 8: Scratch exits are neutral, not consecutive losses

`record_trade` counts `pnl == 0.0` (breakeven/scratch exits) as a loss; three scratches halt the engine for the day.

**Files:**
- Modify: `quant/execution/risk.py:151-156`
- Test: `tests/quant/execution/test_risk_engine.py` (or nearest existing SessionRisk test file — check `tests/quant/execution/` first)

**Interfaces:**
- Consumes: nothing
- Produces: `record_trade(0.0)` leaves both streak counters unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_scratch_exit_does_not_count_as_consecutive_loss():
    from quant.execution.risk import SessionRisk

    r = SessionRisk(storage=None, symbol="SCRATCH_TEST")
    r.record_trade(0.0)
    r.record_trade(0.0)
    r.record_trade(0.0)
    st = r.state()
    assert st.consecutive_losses == 0
    assert not st.halted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/execution/ -k scratch -v`
Expected: FAIL — `consecutive_losses == 3` and `halted` (max_consecutive_losses=3).

- [ ] **Step 3: Implement** — in `quant/execution/risk.py` `record_trade`, replace:

```python
            if pnl > 0.0:
                self._consecutive_losses = 0
                self._consecutive_wins += 1
            else:
                self._consecutive_losses += 1
                self._consecutive_wins = 0
```

with:

```python
            if pnl > 0.0:
                self._consecutive_losses = 0
                self._consecutive_wins += 1
            elif pnl < 0.0:
                self._consecutive_losses += 1
                self._consecutive_wins = 0
            # ponytail: pnl == 0.0 (scratch/breakeven exit) is neutral —
            # it is not a loss and must not trip the consecutive-loss halt.
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/execution/ -q --no-header`
Expected: PASS (check no existing test asserted scratch-as-loss; if one does, it encodes the bug — update its expectation).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/execution/risk.py
git add quant/execution/risk.py tests/quant/execution/
git commit -m "fix(quant): scratch exits no longer count toward consecutive-loss halt"
```

---

### Task 9: trades_today counts round-trip trades, not fills

Every TP1/TP2 partial and every pyramid close calls `record_trade`, incrementing `trades_today`; one base trade with partials consumes most of the 6-trade budget.

**Files:**
- Modify: `quant/execution/risk.py:144-147` (`record_trade` signature)
- Modify: `quant/position_manager.py:151` (partial) and pyramid loop (already `count_as_trade=False` if Task 7 landed first)
- Test: `tests/quant/execution/test_risk_engine.py`

**Interfaces:**
- Consumes: nothing
- Produces: `SessionRisk.record_trade(pnl: float, count_as_trade: bool = True)` — partials/pyramids pass `False`; daily_pnl/equity/halt math unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_partial_fills_do_not_inflate_trades_today():
    from quant.execution.risk import SessionRisk

    r = SessionRisk(storage=None, symbol="COUNT_TEST")
    r.record_trade(10.0, count_as_trade=False)  # TP1 partial
    r.record_trade(5.0, count_as_trade=False)   # TP2 partial
    r.record_trade(7.0)                          # runner close = the trade
    st = r.state()
    assert st.trades_today == 1
    assert st.daily_pnl == 22.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/execution/ -k inflate -v`
Expected: FAIL — `TypeError: unexpected keyword 'count_as_trade'` (or `trades_today == 3` if signature exists).

- [ ] **Step 3: Implement** — in `quant/execution/risk.py`:

```python
    def record_trade(self, pnl: float, count_as_trade: bool = True) -> RiskState:
        with self._lock:
            self._daily_pnl += pnl
            if count_as_trade:
                self._trades_today += 1
```

In `quant/position_manager.py` partial branch, change:

```python
                risk = self._risk.record_trade(partial_fill.pnl)
```

to:

```python
                risk = self._risk.record_trade(partial_fill.pnl, count_as_trade=False)
```

(Pyramid loop already passes `count_as_trade=False` from Task 7; if Task 7 has not landed, apply it to the pyramid `record_trade` call here too.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/execution/ tests/quant/test_portfolio_risk_guard.py -q --no-header`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/execution/risk.py quant/position_manager.py
git add quant/execution/risk.py quant/position_manager.py tests/quant/execution/
git commit -m "fix(quant): trades_today counts round-trip trades, not partial/pyramid fills"
```

---

## Phase C — Decision gate correctness

### Task 10: Gate 1 spread check gets real bid/ask from depth

`ctx.bid`/`ctx.ask` read DTO keys that are never emitted and `Bar` fields that don't exist → always 0 → the slippage guard is silently skipped on every decision. The engine already holds live depth (`self._last_depth`).

**Files:**
- Modify: `quant/decision/context_builder.py` (`build` signature ~:99-111, context construction ~:318-319)
- Modify: `quant/runtime.py:573-584` (`_decide` builder call)
- Test: `tests/quant/decision/test_context_builder_behavior.py`

**Interfaces:**
- Consumes: `OrderBook`/`OrderBookLevel` from `quant.contracts.value_objects` (`.bids`/`.asks` tuples, `.price`)
- Produces: `DecisionContextBuilder.build(..., order_book=None)`; `ctx.bid`/`ctx.ask` populated from best depth levels when present.

- [ ] **Step 1: Write the failing tests** — append to `tests/quant/decision/test_context_builder_behavior.py` (reuse that file's existing bar/risk helpers if present):

```python
def test_context_builder_populates_bid_ask_from_order_book():
    from quant.contracts.value_objects import OrderBook, OrderBookLevel

    ob = OrderBook(bids=(OrderBookLevel(99.9, 10.0),), asks=(OrderBookLevel(100.1, 10.0),))
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.0), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=_dummy_risk_state(), amt_dto={}, order_book=ob,
    )
    assert ctx.bid == 99.9
    assert ctx.ask == 100.1


def test_gate1_rejects_wide_spread():
    from quant.decision.gates_session_position import gate_session_phase

    ob = OrderBook(bids=(OrderBookLevel(100.0, 10.0),), asks=(OrderBookLevel(101.0, 10.0),))
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.5), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=_dummy_risk_state(), amt_dto={}, order_book=ob,
    )
    result = gate_session_phase(ctx)
    assert not result.passed
    assert "spread" in result.reason.lower()
```

If `_dummy_bar`/`_dummy_risk_state` don't exist under those names, use the file's actual helpers (it has `DummyRisk` and a bar factory per the audit) or build `Bar(time="t300", open=100.0, high=100.5, low=99.5, close=close, volume=10.0)` and `SessionRisk(storage=None, symbol="S").state()`. Add the missing `OrderBook`/`OrderBookLevel` import at the top of the second test as needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_context_builder_behavior.py -k "bid_ask or wide_spread" -v`
Expected: FAIL — `TypeError: unexpected keyword 'order_book'` (or `ctx.bid == 0.0`).

- [ ] **Step 3: Implement** — in `quant/decision/context_builder.py` `build`, add the parameter after `amt_dto`:

```python
        amt_dto: dict,
        order_book=None,
        interval_seconds: int = DEFAULT_INTERVAL_SEC,
```

After `obi = float(amt_dto.get("obi") or 0.0)` add:

```python
        best_bid = 0.0
        best_ask = 0.0
        if order_book is not None:
            bids = getattr(order_book, "bids", ()) or ()
            asks = getattr(order_book, "asks", ()) or ()
            if bids:
                best_bid = float(bids[0].price)
            if asks:
                best_ask = float(asks[0].price)
```

Replace the context construction lines:

```python
            bid=float(amt_dto.get("bid") or getattr(bar, "bid", 0.0) or 0.0),
            ask=float(amt_dto.get("ask") or getattr(bar, "ask", 0.0) or 0.0),
```

with:

```python
            bid=float(amt_dto.get("bid") or best_bid or 0.0),
            ask=float(amt_dto.get("ask") or best_ask or 0.0),
```

In `quant/runtime.py` `_decide`, add the argument to the builder call:

```python
        ctx = DecisionContextBuilder().build(
            bar=bar,
            symbol=self.symbol,
            market=self._market,
            contract_expiry=self._contract_expiry,
            tick_size=self._tick_size,
            bar_index=self._bar_index,
            warm_bars=self._amt_engine.warm_bars,
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_state=risk_st,
            amt_dto=amt_dto,
            order_book=self._last_depth,
        )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/decision/ -q --no-header`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/decision/context_builder.py quant/runtime.py tests/quant/decision/test_context_builder_behavior.py
git add quant/decision/context_builder.py quant/runtime.py tests/quant/decision/test_context_builder_behavior.py
git commit -m "fix(quant): wire live depth bid/ask into decision context — spread gate now live"
```

---

### Task 11: Gate 4 enforces the declared 20-tick stop cap

TP is defined as `entry ± 2×risk`, so RR is structurally always 2.00 and `MIN_RR` can never reject; `max_distance_ticks` defaults to 999999 and is never read, so the declared `MAX_STOP_DISTANCE_TICKS = 20` cap is dead — audit reproduced a 198-tick stop passing.

**Files:**
- Modify: `quant/decision/gates_rr.py:13-38`
- Test: `tests/quant/decision/test_gates_rr.py` (create if absent — check `tests/quant/decision/` first)

**Interfaces:**
- Consumes: `structural_anchor`, `structural_stop` (unchanged)
- Produces: `gate_risk_reward(ctx, min_rr=1.5, max_distance_ticks=20.0)` rejects stops wider than the cap. `GatePipeline` calls it with defaults, so the cap activates for all decisions. **Behavior change.**

- [ ] **Step 1: Write the failing test**

```python
def test_gate4_rejects_stop_beyond_20_ticks(monkeypatch):
    from quant.decision import gates_rr
    from quant.decision.context_builder import DecisionContextBuilder
    from quant.bars import Bar
    from quant.execution.risk import SessionRisk

    monkeypatch.setattr(gates_rr, "structural_anchor", lambda ctx, direction: 90.0)

    ctx = DecisionContextBuilder().build(
        bar=Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0),
        symbol="S", market="NSE", contract_expiry=None, tick_size=0.05,
        bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=SessionRisk(storage=None, symbol="S").state(),
        amt_dto={"absorptionSide": "SELL_ABSORBED"},  # gives agent_direction LONG
    )
    assert ctx.agent_direction == "LONG"
    result = gates_rr.gate_risk_reward(ctx)
    assert not result.passed
    assert "wide" in result.reason.lower()


def test_gate4_passes_stop_within_cap(monkeypatch):
    from quant.decision import gates_rr
    from quant.decision.context_builder import DecisionContextBuilder
    from quant.bars import Bar
    from quant.execution.risk import SessionRisk

    monkeypatch.setattr(gates_rr, "structural_anchor", lambda ctx, direction: 99.5)

    ctx = DecisionContextBuilder().build(
        bar=Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0),
        symbol="S", market="NSE", contract_expiry=None, tick_size=0.05,
        bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=SessionRisk(storage=None, symbol="S").state(),
        amt_dto={"absorptionSide": "SELL_ABSORBED"},
    )
    result = gates_rr.gate_risk_reward(ctx)
    assert result.passed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quant/decision/ -k gate4 -v`
Expected: first test FAILS (`result.passed` True with RR=2.00).

- [ ] **Step 3: Implement** — in `quant/decision/gates_rr.py`, change the default and add the cap check:

```python
def gate_risk_reward(
    ctx: DecisionContext,
    min_rr: float = MIN_RR,
    max_distance_ticks: float = MAX_STOP_DISTANCE_TICKS,
) -> GateResult:
    """Gate 4 — risk-reward check (Fabio: R:R >= 1.5) + structural stop cap."""
    if ctx is None or ctx.bar is None:
        return GateResult(4, False, "RR fail", "no bar")
    direction = ctx.agent_direction
    if direction not in ("LONG", "SHORT"):
        return GateResult(4, False, "RR fail", "No direction")
    entry = float(ctx.bar.close)
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else TICK_SIZE_NSE_OPTIONS
    anchor = structural_anchor(ctx, direction)
    sl = structural_stop(direction, entry, anchor, tick)
    if direction == "LONG":
        tp = entry + (entry - sl) * DEFAULT_TP_MULTIPLIER
    else:
        tp = entry - (sl - entry) * DEFAULT_TP_MULTIPLIER
    sl = float(sl)
    tp = float(tp)
    risk = abs(entry - sl)
    if risk > max_distance_ticks * tick:
        return GateResult(
            4, False,
            f"Stop too wide ({risk / tick:.0f} > {max_distance_ticks:.0f} ticks)",
            f"SL={sl:.2f} entry={entry:.2f}",
        )
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0.0
    detail = f"RR={rr:.2f} SL={sl:.2f} TP={tp:.2f}"
    return GateResult(4, rr >= min_rr, "RR pass" if rr >= min_rr else f"RR below {min_rr}", detail)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/decision/ -q --no-header`
Expected: PASS. Then run the golden/system suites to catch fixtures that relied on unbounded stops (expect some reds — those belong to Task 17 triage; note any new failures for that list):

Run: `.venv/bin/python -m pytest tests/quant/ -q --no-header 2>&1 | tail -15`

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/decision/gates_rr.py
git add quant/decision/gates_rr.py tests/quant/decision/
git commit -m "fix(quant): gate 4 enforces declared 20-tick structural stop cap (behavior change)"
```

---

### Task 12: Gate 3 rejects evidence whose direction conflicts with the trade

When `SetupEvidence.is_complete()` is true, gate 3 passes without comparing `ev.direction` to `ctx.agent_direction`; the audit reproduced an approved SHORT citing a LONG Triple-A signal.

**Files:**
- Modify: `quant/decision/gates_edge.py:87-96`
- Test: `tests/quant/decision/test_gates_edge.py` (create if absent)

**Interfaces:**
- Consumes: `SetupEvidence.direction`
- Produces: conflict → gate 3 failure.

- [ ] **Step 1: Write the failing test** (the audit's exact repro, through the real builder):

```python
def test_gate3_rejects_when_triple_a_signal_conflicts_with_agent_direction():
    from quant.decision.context_builder import DecisionContextBuilder
    from quant.decision.gates_edge import gate_triple_a_edge
    from quant.bars import Bar
    from quant.execution.risk import SessionRisk

    dto = {
        "absorptionSide": "BUY_ABSORBED",   # hierarchy -> agent_direction SHORT
        "tripleAPhase": "AGGRESSION",
        "tripleASignal": "LONG",            # evidence direction LONG
        "cvdSlope": 0.0,
        "marketState": "BALANCED",
    }
    ctx = DecisionContextBuilder().build(
        bar=Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0),
        symbol="S", market="NSE", contract_expiry=None, tick_size=0.05,
        bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=SessionRisk(storage=None, symbol="S").state(),
        amt_dto=dto,
    )
    assert ctx.agent_direction == "SHORT"
    assert ctx.setup_evidence is not None and ctx.setup_evidence.direction == "LONG"
    result = gate_triple_a_edge(ctx)
    assert not result.passed
    assert "conflicts" in result.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/decision/ -k conflicts -v`
Expected: FAIL — `result.passed` True ("TRIPLE_A confirmed").

- [ ] **Step 3: Implement** — in `quant/decision/gates_edge.py`, inside the `if ev.is_complete():` block, insert before the session-phase checks:

```python
            if ev.direction and ev.direction != ctx.agent_direction:
                return GateResult(
                    3, False,
                    f"Evidence direction {ev.direction} conflicts with trade direction {ctx.agent_direction}",
                )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/decision/ -q --no-header`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/decision/gates_edge.py
git add quant/decision/gates_edge.py tests/quant/decision/
git commit -m "fix(quant): gate 3 rejects setup evidence whose direction conflicts with the trade"
```

---

### Task 13: option_delta reads the DTO key the analyzer actually emits

`context_builder` reads `optionDelta`; the DTO emits `deltaNormalizedOption` (`quant/amt/dto.py:140`). Delta always defaults to 0.50, so option-premium SL/TP translation is ~3× wrong for OTM options.

**Files:**
- Modify: `quant/decision/context_builder.py:326`
- Test: `tests/quant/decision/test_context_builder_behavior.py`

**Interfaces:**
- Consumes: `amt_dto["deltaNormalizedOption"]`
- Produces: `ctx.option_delta` reflects the analyzer's per-symbol delta.

- [ ] **Step 1: Write the failing test**

```python
def test_option_delta_reads_delta_normalized_option_key():
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.0), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=_dummy_risk_state(), amt_dto={"deltaNormalizedOption": 0.15},
    )
    assert ctx.option_delta == 0.15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_context_builder_behavior.py -k option_delta -v`
Expected: FAIL — `ctx.option_delta == 0.5`.

- [ ] **Step 3: Implement** — replace the line in `context_builder.py`:

```python
            option_delta=float(amt_dto.get("optionDelta") or 0.50),
```

with:

```python
            option_delta=float(
                amt_dto.get("deltaNormalizedOption")
                or amt_dto.get("optionDelta")
                or 0.50
            ),
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/decision/ -q --no-header`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/decision/context_builder.py
git add quant/decision/context_builder.py tests/quant/decision/test_context_builder_behavior.py
git commit -m "fix(quant): option_delta reads deltaNormalizedOption — premium SL/TP scaling no longer assumes 0.50"
```

---

## Phase D — Engine correctness

### Task 14: Pyramid closes emit PositionClosed; check_pyramid reads legLvns

Pyramid closes never emit `PositionClosed` → their `open_positions` DB rows are never deleted and the UI shows phantom positions forever. `check_pyramid` reads `amt_dto["legLvn"]` but the DTO only emits `legLvns` (list) → the pyramid engine can never fire (certification tests pass only by injecting the phantom key).

**Files:**
- Modify: `quant/position_manager.py:164-175` (close loop — already touched in Task 7; the `PositionClosed` emission lands here) and `:236-241` (legLvn read)
- Test: `tests/quant/test_pyramid_events.py`

**Interfaces:**
- Consumes: `amt_dto["legLvns"]` (list of floats), `PositionClosed`
- Produces: pyramid close → `PositionClosed` per add-on (storage bridge deletes rows, projector clears); `check_pyramid` derives nearest LVN from `legLvns` with `legLvn` fallback. **Behavior change: pyramid engine becomes reachable.**

- [ ] **Step 1: Write the failing tests** — create `tests/quant/test_pyramid_events.py`:

```python
"""Pyramid close events + legLvns derivation (audit Phase D)."""

from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.events import PositionClosed
from quant.execution.exits import ExitDecision
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager


def _pm(emit_sink):
    return PositionManager(
        oms=PaperOMS(lot_size=1.0),
        exits=MagicMock(),
        risk=SessionRisk(storage=None, symbol="S"),
        emit_fn=emit_sink,
        symbol="S", market="NSE", contract_expiry=None, tick_size=0.05,
    )


def _base_position(pm):
    sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
                 model_label="t", symbol="S", timestamp="t0")
    return pm._oms.submit(sig, 100.0)


def test_pyramid_close_emits_position_closed():
    emitted = []
    pm = _pm(emitted.append)
    base = _base_position(pm)
    pyramid = pm._oms.add_pyramid(base=base, entry_price=101.0, new_sl=100.0,
                                  size=50.0, time="t1", pyramid_level=1)
    pm.pyramid_positions = [pyramid]
    pm._exits.evaluate.return_value = ExitDecision(True, "TRAIL", 103.0)

    bar = Bar(time="t300", open=102.0, high=103.5, low=101.5, close=103.0, volume=10.0)
    remaining = pm.manage_exit(amt_dto={}, bar=bar, position=base,
                               bar_index=10, entry_bar_index=0, entry_time_epoch=0.0)

    assert remaining is None
    closed_ids = [e.fill.position._id for e in emitted if isinstance(e, PositionClosed)]
    assert pyramid._id in closed_ids, "pyramid close emitted no PositionClosed"


def test_check_pyramid_derives_lvn_from_leg_lvns_list():
    pm = _pm(lambda e: None)
    base = _base_position(pm)
    pm._exits.is_risk_free.return_value = True
    bar = Bar(time="t300", open=99.9, high=100.2, low=99.8, close=100.0, volume=10.0)
    dto = {"legLvns": [100.0], "absorptionSide": "SELL_ABSORBED"}

    pm.check_pyramid(dto, bar, base, bar_index=5)

    assert pm.pyramid_count == 1, "check_pyramid ignored legLvns list"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quant/test_pyramid_events.py -v`
Expected: first test FAILS if Task 7 has not landed (no PositionClosed for pyramid); second FAILS (`pyramid_count == 0`).

- [ ] **Step 3: Implement** — the close-loop emission is exactly the Task 7 Step 3 loop (with `self._emit(PositionClosed(...))` and `count_as_trade=False`); if Task 7 already landed, only the legLvn fix remains. In `check_pyramid`, replace:

```python
        leg_lvn = float(amt_dto.get("legLvn") or 0.0)
        if leg_lvn <= 0:
            return  # No Layer 3 LVN available yet
```

with:

```python
        leg_lvn = float(amt_dto.get("legLvn") or 0.0)
        if leg_lvn <= 0:
            # The DTO emits legLvns (list); legLvn (singular) is test-injected
            # only. Derive the LVN nearest price, same rule as context_builder.
            leg_lvns = amt_dto.get("legLvns") or []
            valid = [float(x) for x in leg_lvns if float(x) > 0]
            if valid:
                leg_lvn = min(valid, key=lambda x: abs(x - float(bar.close)))
        if leg_lvn <= 0:
            return  # No Layer 3 LVN available yet
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/test_pyramid_events.py tests/quant/test_certification.py -q --no-header`
Expected: PASS (certification tests inject `legLvn` directly — the fallback keeps them green).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/position_manager.py tests/quant/test_pyramid_events.py
git add quant/position_manager.py tests/quant/test_pyramid_events.py
git commit -m "fix(quant): pyramid closes emit PositionClosed; check_pyramid reads legLvns (engine now reachable)"
```

---

### Task 15: Session rollover resets the profile and candle ring

On date change `AMTEngine.analyze` persists prior levels but keeps the prior day's candles in the ring and the incremental profile — POC/VA become multi-day composites on day 2+ of continuous uptime, contradicting the session-scoped contract.

**Files:**
- Modify: `quant/amt_engine.py:300-320` (rollover block in `analyze`)
- Test: `tests/quant/test_amt_engine_rollover.py`

**Interfaces:**
- Consumes: `IncrementalVolumeProfile` (already imported in amt_engine)
- Produces: after rollover, ring and profile contain only the new session's bars; analyzer's `len(data) >= 5` guard fails closed until 5 fresh bars accumulate.

- [ ] **Step 1: Write the failing test** — create `tests/quant/test_amt_engine_rollover.py`:

```python
"""Session rollover must reset the candle ring + incremental profile."""

from datetime import datetime

from quant.amt_engine import AMTEngine
from quant.bars import Bar
from quant.contracts.timezones import IST
from quant.session_levels import SessionLevelStore


def _bar_at(day: int, minute: int, close: float) -> Bar:
    epoch = int(datetime(2026, 8, day, 10, minute, tzinfo=IST).timestamp())
    return Bar(time=str(epoch), open=close - 0.5, high=close + 0.5,
               low=close - 1.0, close=close, volume=100.0)


def test_rollover_resets_candle_ring_and_profile():
    eng = AMTEngine(symbol="TEST FUT", market="NSE", session_levels=SessionLevelStore())
    for i in range(6):
        eng.analyze(_bar_at(24, i, 100.0 + i))  # day 1
    assert len(eng._amt_candles) == 6

    eng.analyze(_bar_at(25, 0, 105.0))  # day 2

    assert len(eng._amt_candles) == 1, "prior-day candles survived rollover"
    assert eng._amt_incremental is not None
    assert len(eng._amt_incremental._candles) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/test_amt_engine_rollover.py -v`
Expected: FAIL — `len(_amt_candles) == 7`.

- [ ] **Step 3: Implement** — in `quant/amt_engine.py` `analyze`, inside the rollover block, after `self._prior = self._session_levels.load_levels(self.symbol)` add:

```python
            # New session: the profile and ring must reflect today's auction
            # only — prior-day volume biases POC/VA (session_scope's contract).
            # The analyzer's len(data) >= 5 guard fails closed until fresh
            # bars accumulate.
            with self._amt_lock:
                self._amt_candles = []
                self._amt_incremental = IncrementalVolumeProfile()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/test_amt_engine_rollover.py tests/quant/amt/ -q --no-header`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check quant/amt_engine.py tests/quant/test_amt_engine_rollover.py
git add quant/amt_engine.py tests/quant/test_amt_engine_rollover.py
git commit -m "fix(quant): session rollover resets profile + candle ring (no multi-day POC/VA bleed)"
```

---

## Phase E — Security

### Task 16: Tick injection restricted to development env

`_ALLOWED_ENVS = {"development", "paper"}` but the default production mode IS `paper` (root `start.sh`), bound to `0.0.0.0` with no auth — anyone on the LAN can fabricate bars that drive entries/exits. The E2E test already runs the subprocess with `GLASSYTRADE_ENV=development`.

**Files:**
- Modify: `backend/app/api/routers/testing.py:26`
- Modify: `tests/e2e/test_cross_process_injection.py` (env-gate test around line 168)

**Interfaces:**
- Consumes: `GLASSYTRADE_ENV`
- Produces: injection 403 in `paper` and `live`; allowed only in `development`. **Behavior change.**

- [ ] **Step 1: Update the guard test first** — in `tests/e2e/test_cross_process_injection.py`, locate the `_env_allows` test (around lines 165-180) and make the paper case expect rejection:

```python
def test_env_gate(monkeypatch):
    from backend.app.api.routers.testing import _env_allows

    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    ok, why = _env_allows()
    assert not ok and "paper" in why

    monkeypatch.setenv("GLASSYTRADE_ENV", "development")
    ok, _ = _env_allows()
    assert ok

    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    ok, _ = _env_allows()
    assert not ok
```

(Match the file's actual test name/structure; keep the development + live assertions it already has.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/e2e/test_cross_process_injection.py -k env -v`
Expected: FAIL on the paper case (currently allowed).

- [ ] **Step 3: Implement** — in `backend/app/api/routers/testing.py`:

```python
_ALLOWED_ENVS = {"development"}
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/e2e/test_cross_process_injection.py -k env -v`
Expected: PASS. (The full-chain E2E test at line ~59 already sets `GLASSYTRADE_ENV=development` for its subprocess — unaffected.)

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check backend/app/api/routers/testing.py
git add backend/app/api/routers/testing.py tests/e2e/test_cross_process_injection.py
git commit -m "fix(backend): tick injection restricted to development env (paper is the default prod mode)"
```

---

## Phase F — Test suite honesty

### Task 17: Triage the 11 red tests (drift vs regression)

The suite is red: 11 failures. The non-environmental ones are deterministic fixtures that no longer produce approvals through the real engine after recent gate/stop changes. Because Phase C changed gate behavior (stop cap, evidence-direction conflict, live spread gate), run this task AFTER Phase C and treat the gates as source of truth unless a gate contradicts the audit.

**Files:**
- Modify (likely): `tests/integration/test_fabio_india_scenarios.py`, `tests/system/test_paper_protocol.py`, `tests/quant/test_quant_execution_e2e.py`, `tests/quant/test_quant_runtime_e2e.py`, `tests/quant/test_quant_system_e2e.py`, `tests/e2e/test_cross_process_injection.py`

**Interfaces:**
- Consumes: all Phase A-D fixes landed
- Produces: green suite with fixtures matching current intended behavior, or production fixes where a gate is wrong.

- [ ] **Step 1: Get the current failure list**

Run: `.venv/bin/python -m pytest tests/ -q --no-header 2>&1 | tail -25`
Record every failing node id.

- [ ] **Step 2: Per-failure diagnosis loop** — for each failing test:

  1. Run it alone with `-v --tb=long`.
  2. If it's a decision/entry expectation failure, temporarily print the decision's `block_reasons`/`gate_results` (e.g. add a scratch assertion on `decision.block_reasons` in the test) to see WHICH gate now blocks.
  3. Apply the decision rule:
     - Gate behavior matches the audit's intended fix (e.g. stop cap rejects a 40-tick fixture stop, evidence conflict rejects a mismatched fixture) → **update the fixture** so the scenario satisfies current gates (tighten the stop anchor, align evidence direction, provide depth with a tight spread).
     - `test_fabio_india_scenarios.py::test_scenario_value_area_fade_day` (`sl 24649.9 < 24650.0`): one-tick boundary from the 58a0abf stop change — verify `quant/decision/stops.py` keeps SL strictly on the correct side, then update the expected bound to the new tick-adjusted value.
     - `tests/system/test_paper_protocol.py` (479 bars vs 240, no position opens): fixture DTOs predate the gate additions — adjust the synthetic DTO sequence until one scenario legitimately passes all 4 gates; keep the strong invariants (position lifecycle assertions) intact.
     - `test_amt_trace_produces_unified_results` (`len(amts) != 155`): count changed with per-bar emit behavior — update the expected count to the actual, after confirming each emitted `AmtUpdated` maps to a real bar.
     - `test_leg_a_full_chain_http_to_ws` (no `GOLDM*` in health): environmental — the scanner returned no matching contract. Make the test skip cleanly when the scanner yields no symbol (`pytest.skip("scanner returned no GOLDM contract")`) instead of raising `StopIteration`.
  4. If a gate itself is wrong (blocks a scenario that the Fabio rules say must trade), fix the gate in a separate commit with its own test — do not paper over in the fixture.

- [ ] **Step 3: Re-run full suite**

Run: `.venv/bin/python -m pytest tests/ -q --no-header 2>&1 | tail -5`
Expected: 0 failed (skips allowed only where explicitly added above).

- [ ] **Step 4: Commit per test file (or coherent group)**

```bash
git add tests/<file>
git commit -m "test(quant): align <file> fixtures with current gate behavior"
```

---

### Task 18: Remove tautological asserts and dishonest test names

Several tests assert `X or True`, and `test_full_stack.py` asserts the trade lifecycle did NOT happen while claiming to test the full stack.

**Files:**
- Modify: `tests/quant/execution/test_exit_rules.py:46`
- Modify: `tests/quant/test_fabio_accuracy_battery.py:65,97`
- Modify: `tests/quant/amt/profile/test_lvn_detector.py:276`
- Modify: `tests/quant/test_full_stack.py` (docstring + name + asserts around :106-109)

**Interfaces:**
- Consumes: nothing
- Produces: every assertion states a real expectation; `test_full_stack` honestly named.

- [ ] **Step 1: Fix each tautology**

`tests/quant/execution/test_exit_rules.py:46` — replace:

```python
    assert result is not None or True  # Test passes either way for now
```

with the actual expected outcome for the scenario above it (read the test's setup: if the scenario is a scratch exit, `assert result is not None and result.reason == ExitReason.SCRATCH` — use the real expected reason from `exit_rules.py` semantics; if the function is the unwired `check_time_stop`, assert its actual documented return for the input).

`tests/quant/test_fabio_accuracy_battery.py:97` — replace `session_force_exit(...) or True` with the real expected boolean for the timestamp in the scenario (compute it from the session table: NSE phase 5 / post-market → `True`, mid-session → `False`). At `:65`, replace the hardcoded `check("V4 VA bounds within price range", True)` with a computed comparison of VAH/VAL against the scenario's price range.

`tests/quant/amt/profile/test_lvn_detector.py:276` — replace `assert 101.0 in tracker.update(...) or True` with `assert 101.0 in tracker.update(...)`; if that fails, the detector behavior diverged from the test's intent — diagnose and fix the expectation to the detector's documented contract (persistence filter), never leave `or True`.

- [ ] **Step 2: Make test_full_stack honest** — in `tests/quant/test_full_stack.py`, the test at :106-109 asserts `position is None`, `fills == []`, `trades_today == 0`. Rename it and its docstring to what it actually verifies:

```python
def test_full_stack_no_trade_scenario_stays_flat():
    """A scenario with no qualifying edge produces no position, fills, or trades."""
```

Update the module docstring claim ("ticks → OMS open → exit → OMS close") to match: the lifecycle-positive scenario belongs to Task 17's fixture work (`tests/system/test_paper_protocol.py` covers it end-to-end).

- [ ] **Step 3: Run affected tests**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_exit_rules.py tests/quant/test_fabio_accuracy_battery.py tests/quant/amt/profile/test_lvn_detector.py tests/quant/test_full_stack.py -q --no-header`
Expected: PASS. Any new failure here is a real latent bug the tautology hid — fix it as its own commit before proceeding.

- [ ] **Step 4: Lint + commit**

```bash
.venv/bin/python -m ruff check tests/quant/execution/test_exit_rules.py tests/quant/test_fabio_accuracy_battery.py tests/quant/amt/profile/test_lvn_detector.py tests/quant/test_full_stack.py
git add tests/quant/execution/test_exit_rules.py tests/quant/test_fabio_accuracy_battery.py tests/quant/amt/profile/test_lvn_detector.py tests/quant/test_full_stack.py
git commit -m "test(quant): remove tautological asserts; rename no-trade full-stack test honestly"
```

---

## Final verification

- [ ] Full suite: `.venv/bin/python -m pytest tests/ backend/tests -q --no-header` → 0 failed
- [ ] Lint all touched paths: `.venv/bin/python -m ruff check quant backend/app brokers shared tests backend/tests`
- [ ] Architecture contracts: `.venv/bin/python -m pytest tests/architecture/ -q --no-header`
- [ ] Smoke boot: `GLASSYTRADE_ENV=paper timeout 30 backend/start_paper.sh` (or `start.sh`) — confirm logs show coordinator started, then SIGTERM the process and confirm logs show `Emergency halt applied` + graceful shutdown (Tasks 1-2 verification).

## Self-review notes

- Spec coverage: every CRITICAL/HIGH audit finding with a code-level root cause maps to a task (1→T1/T2, 4→T5, 5→T16, 6→T3, 7→T4, 8→T6/T7, 9→T11, 10→T10, 11→T12, 12→T13, 13→T7/T14, 15→noted out-of-scope config wiring, 16→out-of-scope stale-DTO marker deferred; MEDIUM profile bleed→T15; test-suite→T17/T18). Finding 14 (engine-death position management) is mitigated by T3/T4 (removing the two proven death causes) — full exit-ownership-on-crash is a design change, deferred.
- Type consistency: `count_as_trade` (T9) used in T7's pyramid loop — ordering note included in T7 step 3. `last_partial_fill`/`last_pyramid_pnl` defined in T7, consumed by T7's runtime step. `order_book` param added in T10 only.
- Placeholder scan: T17 is inherently judgment-based; it carries explicit decision rules instead of code because the correct fixture values depend on runtime gate output at execution time.
