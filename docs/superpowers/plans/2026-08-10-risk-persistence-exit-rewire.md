# Risk Persistence + Exit Rewire + Smalls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use `- [ ]` checkboxes for tracking.

**Goal:** Fix every non-broker finding from the project review with the smallest working diff — no new abstractions.

**Architecture:** Extend the existing `quant/` deterministic engine in place. Persist risk via the existing `storage.kv_set` port; teach the lean live `ExitEngine` (which works on `execution.order.Position`, not the rich `contracts.entities.Position`) just enough to handle spread blowout + trailing + session-aware time stops, so the rich-but-unreachable `exit_rules.py` isn't re-plumbed through a Position adapter we don't need.

**Tech Stack:** Python 3.14, `quant/`, `backend/app/infrastructure/storage/database.py` (`kv_set`/`kv_get` already exist), pytest.

## Global Constraints

- Ponytail (full): reuse existing helpers and ports; no new dependencies; `ponytail:` comments mark deliberate simplifications.
- Skip all broker-side findings (`brokers/broker/dhan/*` catch-alls, live OMS, idempotency) — user opted out.
- Never widen a stop-loss; moves must be monotonic (long: SL only rises; short: SL only falls).
- Tests live in `quant/tests/` next to the modules under test (match existing style).
- `asyncio`-free `quant/` runs today — the engine is sync; no new event loops.

---

### Task 1: Persist SessionRisk to the KV store

**Files:**
- Modify: `quant/execution/risk.py` (add `load`/`snapshot` + optional storage port)
- Modify: `quant/runtime.py:198, 505` (wire load-at-start + save-on-record)
- Test: `quant/tests/test_risk_persistence.py`

**Interfaces:**
- Consumes: `storage.kv_set(key: str, value: Any) -> None` and `storage.kv_get(key: str) -> str | None` from `backend/app/infrastructure/storage/database.py:848,912` (port already used by `session_levels.py`).
- Produces: `SessionRisk.load(storage, symbol, date) -> SessionRisk` (classmethod), `SessionRisk.snapshot() -> dict`, plus a `_save()` call inside `record_trade`.

- [ ] **Step 1: Failing test**

```python
import json
from quant.execution.risk import SessionRisk

class MemKV:
    def __init__(self): self.m = {}
    def kv_set(self, k, v): self.m[k] = v
    def kv_get(self, k): return self.m.get(k)

def test_risk_persists_across_restarts():
    kv = MemKV()
    r1 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10")
    r1.record_trade(-1000.0)  # one loss
    r1.record_trade(-2000.0)  # daily loss -3000 -> halted (3% of 1M)

    # Simulate restart: new instance over same KV
    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10")
    assert r2.state().daily_pnl == -3000.0
    assert r2.state().consecutive_losses == 2
    assert r2.state().halted is True
    # And no more trades accepted
    r2.record_trade(-5000.0)
    assert r2.state().daily_pnl == -3000.0  # unchanged

def test_new_session_date_resets_state():
    kv = MemKV()
    r1 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-10")
    r1.record_trade(-1000.0)
    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-08-11")  # next day
    assert r2.state().daily_pnl == 0.0
    assert r2.state().halted is False
```

- [ ] **Step 2: Run, expect FAIL (`AttributeError: storage`)**

  Run: `pytest quant/tests/test_risk_persistence.py -v`

- [ ] **Step 3: Implement**

```python
# quant/execution/risk.py
import json
import threading
from dataclasses import dataclass
from datetime import date as _date
from typing import Any


@dataclass(frozen=True)
class RiskState:
    daily_pnl: float
    consecutive_losses: int
    halted: bool
    halt_reason: str
    risk_per_trade_pct: float


class SessionRisk:
    """Crash-safe intraday risk. Persists (daily_pnl, consecutive_losses,
    halted, halt_reason) to a kv store keyed by (symbol, session_date) so a
    process restart re-arms to the same budget, not a fresh one.
    ponytail: single global lock per SessionRisk, per-account locks if we ever
    run more than a handful of engines in one process."""

    _KEY_TEMPLATE = "daily_risk:{symbol}:{date}"

    def __init__(self, starting_equity: float = 1_000_000.0,
                 base_risk_pct: float = 0.01,
                 max_daily_loss_pct: float = 0.03,
                 max_consecutive_losses: int = 3,
                 storage: Any | None = None,
                 symbol: str = "",
                 date: str | None = None) -> None:
        self._equity = starting_equity
        self._base_risk_pct = base_risk_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._storage = storage
        self._symbol = symbol
        self._date = date or _date.today().isoformat()
        self._lock = threading.Lock()
        # Defaults; load() may overwrite.
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._halted = False
        self._halt_reason = ""
        self._load()

    # -- persistence ---------------------------------------------------

    def _key(self) -> str:
        return self._KEY_TEMPLATE.format(symbol=self._symbol, date=self._date)

    def _load(self) -> None:
        if self._storage is None:
            return
        try:
            raw = self._storage.kv_get(self._key())
            if raw is None:
                return
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            self._daily_pnl = float(data["daily_pnl"])
            self._consecutive_losses = int(data["consecutive_losses"])
            self._halted = bool(data["halted"])
            self._halt_reason = str(data["halt_reason"])
        except Exception:
            # ponytail: corrupt/absent state => start flat, do NOT inherit a
            # phantom halt. Better to trade one session fresh than never.
            return

    def _save(self) -> None:
        if self._storage is None:
            return
        self._storage.kv_set(self._key(), {
            "daily_pnl": self._daily_pnl,
            "consecutive_losses": self._consecutive_losses,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
        })

    # -- public API ------------------------------------------------------

    def record_trade(self, pnl: float) -> RiskState:
        with self._lock:
            if self._halted:  # refuse to count trades after halt
                return self.state()
            self._daily_pnl += pnl
            if pnl > 0.0:
                self._consecutive_losses = 0
            else:
                self._consecutive_losses += 1
            if self._daily_pnl <= -self._max_daily_loss_pct * self._equity:
                self._halted = True
                self._halt_reason = "daily loss limit reached"
            elif self._consecutive_losses >= self._max_consecutive_losses:
                self._halted = True
                self._halt_reason = "max consecutive losses reached"
            self._save()
            return self.state()

    def state(self) -> RiskState:
        with self._lock:
            return RiskState(
                daily_pnl=self._daily_pnl,
                consecutive_losses=self._consecutive_losses,
                halted=self._halted,
                halt_reason=self._halt_reason,
                risk_per_trade_pct=self._risk_per_trade_pct(),
            )

    def position_size(self, entry: float, sl: float) -> float:
        if entry == sl:
            return 0.0
        risk_amount = self._equity * self._risk_per_trade_pct()
        return risk_amount / abs(entry - sl)

    def _risk_per_trade_pct(self) -> float:
        floor = self._base_risk_pct * 0.25
        shrunk = self._base_risk_pct * (0.5 ** self._consecutive_losses)
        return max(shrunk, floor)
```

- [ ] **Step 4: Wire into runtime**

```python
# quant/runtime.py  — around line 188, after self._session_levels is set:
risk_storage = getattr(self._session_levels, "_storage", None)  # ponytail: reach through — session_levels owns the storage port today
self._risk = SessionRisk(storage=risk_storage, symbol=self.symbol, date=self._session_date)
```
And in `_manage_exit` (`runtime.py:505`), confirm the existing call `self._risk.record_trade(fill.pnl)` now persists via `_save()`.

- [ ] **Step 5: Verify**

  Run: `pytest quant/tests/test_risk_persistence.py -v`  (expect 2 PASS)

- [ ] **Step 6: Commit**

  `git add quant/execution/risk.py quant/runtime.py quant/tests/test_risk_persistence.py && git commit -m "fix(risk): persist SessionRisk to kv_store so restarts don't wipe daily-loss budget"`

---

### Task 2: Live ExitEngine — spread blowout + trailing + session time stop

**Files:**
- Modify: `quant/execution/exits.py` (Track A)
- Modify: `quant/runtime.py:490-506` `_manage_exit` (Track B)
- Test: `quant/tests/test_exits_trailing.py`, `quant/tests/test_exits_spread.py`

**Interfaces:**
- Consumes: existing `get_session_time_stop(market_state, session_phase, is_expiry, time_to_close)` from `quant/execution/exit_rules.py:540`; `OrderBook` from `quant.execution.order` (already used as `_last_depth`).
- Produces: extended `ExitDecision` (same dataclass, now with actual trailing assignment) and `ExitEngine.evaluate(...)` accepting `best_bid`/`best_ask`/`market_state`/`session_phase`/`is_expiry`/`time_to_close` keyword args.

**Why not rewire `exit_rules.py`?** Those helpers mutate the rich `contracts.entities.Position` (`breakeven_set`, `peak_profit`, cushion FSM); runtime's live Position is the lean `execution.order.Position`. Ponytail: the live path needs ~30 lines of new logic, not an adapter layer. `exit_rules.py` stays, untouched.

- [ ] **Step 1: Failing tests**

```python
# quant/tests/test_exits_spread.py
from quant.execution.exits import ExitEngine
from quant.execution.order import Order, Position
from quant.decision.signal_builder import Signal
from quant.auction_state import AuctionState
# TODO: use existing test helpers to build a minimal state

def test_spread_blowout_exits_long():
    # LONG position, entry 100, SL 95, TP 110, premium = entry.
    sig = Signal("LONG", "test", 100.0, 95.0, 110.0, 2.0, 0.7, "N", "t")
    pos = Position(order=Order(sig, 1.0), open_price=100.0, open_time="t", size=1)
    eng = ExitEngine(time_stop_bars=10_000)
    state = ...  # close 102, cvd_slope 0
    dec = eng.evaluate(pos, state, bar_index=0,
                       best_bid=98.0, best_ask=102.0)  # spread 4 = 4% of 100
    assert dec.should_exit
    assert dec.reason == "SPREAD_BLOWOUT"

def test_no_blowout_without_depth():
    eng = ExitEngine(time_stop_bars=10_000)
    dec = eng.evaluate(pos, state, bar_index=0)
    assert not dec.should_exit
```

```python
# quant/tests/test_exits_trailing.py
def test_trailing_activates_after_1r_and_is_monotonic():
    # long, entry 100, sl 95, tp 110 => risk 5, 1R profit = price 105
    # first bar at 105 -> trail_to = 100 (breakeven). second bar 107 -> trail_to = 102.
    # third bar 103 -> no change (never widen for a trailing stop on a long).
```

- [ ] **Step 2: Run, expect FAIL (TypeError: unexpected keyword arg `best_bid`)**

- [ ] **Step 3: Implement `ExitEngine` changes**

```python
# quant/execution/exits.py  (append to the same file)
from quant.execution.exit_rules import get_session_time_stop

@dataclass
class _Trail:
    active: bool = False
    stop: float | None = None

class ExitEngine:
    def __init__(self, time_stop_bars: int = 30, cvd_kill_threshold: float = float("inf"),
                 trail_giveback_pct: float = 0.30,
                 spread_max_pct: float = 0.03) -> None:
        self.time_stop_bars = time_stop_bars
        self.cvd_kill_threshold = cvd_kill_threshold
        self.trail_giveback_pct = trail_giveback_pct
        self.spread_max_pct = spread_max_pct
        self._trail: dict[int, _Trail] = {}

    def evaluate(self, position, state, bar_index,
                 bar_high=None, bar_low=None,
                 best_bid=None, best_ask=None,
                 market_state="", session_phase="",
                 is_expiry=False, time_to_close: float = 0.0,
                 entry_time_epoch: float = 0.0,
                 now_epoch: float = 0.0):
        close = float(state.close)
        long = position.size > 0
        sl = float(position.order.signal.sl)
        tp = float(position.order.signal.tp)
        low = close if bar_low is None else bar_low
        high = close if bar_high is None else bar_high

        # 1) Spread blowout — exit immediately if depth dried up.
        if best_bid and best_ask and close > 0:
            spread_pct = (best_ask - best_bid) / close
            if spread_pct >= self.spread_max_pct:
                mid = (best_bid + best_ask) / 2
                return ExitDecision(True, "SPREAD_BLOWOUT", mid)

        # 2) SL / TP (unchanged)
        if long and low <= sl:
            return ExitDecision(True, "SL", close)
        if not long and high >= sl:
            return ExitDecision(True, "SL", close)
        if long and high >= tp:
            return ExitDecision(True, "TP", close)
        if not long and low <= tp:
            return ExitDecision(True, "TP", close)

        # 3) CVD kill (unchanged)
        slope = float(state.order_flow.cvd_slope)
        if long and slope < -self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)
        if not long and slope > self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)

        # 4) Trailing (activates once profit >= 1R)
        pid = id(position)
        risk = abs(float(position.order.signal.entry) - sl)
        profit = (close - position.open_price) if long else (position.open_price - close)
        if risk > 0 and profit >= risk:
            tr = self._trail.setdefault(pid, _Trail(active=True))
            giveback = self.trail_giveback_pct * profit
            candidate = close - giveback if long else close + giveback
            # never widen: long trail only rises, short trail only falls
            if tr.stop is None or (long and candidate > tr.stop) or (not long and candidate < tr.stop):
                tr.stop = max(candidate, sl if long else -sl)  # never trail below original SL
            if long and low <= tr.stop:
                return ExitDecision(True, "TRAIL", close, trail_stop=tr.stop)
            if not long and high >= tr.stop:
                return ExitDecision(True, "TRAIL", close, trail_stop=tr.stop)

        # 5) Session-aware time stop (falls back to old bar count when no
        #    session context was supplied)
        if session_phase and time_to_close > 0 and entry_time_epoch and now_epoch:
            max_hold = get_session_time_stop(market_state, session_phase, is_expiry, time_to_close)
            if (now_epoch - entry_time_epoch) >= max_hold:
                return ExitDecision(True, "TIME", close)
        elif bar_index >= self.time_stop_bars:
            return ExitDecision(True, "TIME", close)

        return ExitDecision(False, "", close)
```

- [ ] **Step 4: Wire `_manage_exit`**

```python
# quant/runtime.py  — replace lines 490-499 body of _manage_exit:
def _manage_exit(self, state, bar) -> None:
    held_bars = self._bar_index - self._entry_bar_index
    if self._session_force_exit(bar.time, market=self._market, contract_expiry=self._contract_expiry):
        exit_dec = ExitDecision(True, "SESSION_CLOSE", float(state.close))
    else:
        depth = self._last_depth
        best_bid = depth.bids[0].price if depth and depth.bids else None
        best_ask = depth.asks[0].price if depth and depth.asks else None
        info = get_session_info(bar.time, market=self._market)
        exit_dec = self._exits.evaluate(
            self._position, state, bar_index=held_bars,
            bar_high=float(bar.high), bar_low=float(bar.low),
            best_bid=best_bid, best_ask=best_ask,
            market_state=str(state.market_state), session_phase=str(getattr(info, "phase", "")),
            is_expiry=bool(getattr(info, "is_expiry", False)),
            time_to_close=float(getattr(info, "time_to_close_s", 0.0)),
            entry_time_epoch=float(getattr(self, "_entry_time_epoch", 0.0)),
            now_epoch=bar.time.timestamp() if hasattr(bar.time, "timestamp") else 0.0,
        )
    if exit_dec.should_exit:
        fill = self._oms.close(self._position, exit_dec.close_price, bar.time, exit_dec.reason)
        self._exits._trail.pop(id(self._position), None)  # clear trailing state
        self._position = None
        self._emit(PositionClosed(symbol=self.symbol, time=bar.time, fill=fill))
        risk = self._risk.record_trade(fill.pnl)
        self._emit(RiskUpdated(symbol=self.symbol, time=bar.time, risk=risk))
```
(Also stash `_entry_time_epoch = bar.time.timestamp()` in `_open_position` — one line.)

- [ ] **Step 5: Verify** — `pytest quant/tests/test_exits_spread.py quant/tests/test_exits_trailing.py -v`

- [ ] **Step 6: Commit** — `git add quant/execution/exits.py quant/runtime.py quant/tests/test_exits_*.py && git commit -m "feat(exit): live ExitEngine gains spread blowout, trailing stop, session-aware time stop"`

---

### Task 3: Fail-closed on startup reconciliation in live mode

**Files:** Modify `backend/app/main.py:357-362` · Test `backend/tests/unit/test_startup_reconciliation.py`

- [ ] **Step 1: Test** — construct app with a fake `StartupReconciliation` that raises; assert `/health/ready` returns 503 and coordinator isn't started when `GLASSYTRADE_ENV=live`.
- [ ] **Step 2: Implement** — wrap the existing `except Exception` path: only mark the phase failed and `mark_startup_failed` when env is live; for other envs log + continue. Then gate `app.router.on_startup` live-mode coordinator start on `reconciliation_executed`.
- [ ] **Step 3: Verify** — pytest, expect live-mode readiness 503 on failure.
- [ ] **Step 4: Commit** — `git add backend/app/main.py backend/tests/unit/test_startup_reconciliation.py && git commit -m "fix(startup): fail-closed reconciliation in live mode"`

---

### Task 4: SL placement — 1-2 ticks inside the value-area edge

**Files:** Modify `quant/decision/signal_builder.py:96-100` (LONG) + `:113-116` (SHORT) · Test `quant/tests/test_signal_builder_sl.py`

- [ ] **Step 1: Test** — given `val=100`, `step=10`, tick=`0.05`, LONG signal must have `sl` in `[99.90, 99.95]` (1-2 ticks below VAL), not `90.0`.
- [ ] **Step 2: Implement**

```python
# In build(), LONG branch:
tick = 0.05  # ponytail: NSE options tick; promote to config when we trade a second instrument class
anchor = val if entry > val else nearest_level
sl = anchor - 2 * tick
# keep old fallback when the profile step is degenerate
if sl >= anchor:
    sl = anchor - step if step > 0 else anchor
```
(SHORT mirrors with `+ 2 * tick`.)

- [ ] **Step 3: Verify**  ·  **Step 4: Commit** `fix(signal): stop 1-2 ticks inside value-area edge instead of a full profile step outside`

---

### Task 5: Clean up divergence ND-3 (LLM temperature from config, not hardcoded)

**Files:** Modify `quant/runtime.py:773` · `quant/inference/mlx_inference_adapter.py` (accept `temperature` param if missing) · Test `quant/tests/test_llm_temperature.py`

- [ ] **Step 1: Test** — construct engine with `temperature_entry=0.5` in config; assert the value reaching `predict(...)` is 0.5, not 0.3.
- [ ] **Step 2: Implement** — read `os.getenv("LLM_TEMPERATURE_ENTRY", "0.3")` once in `__init__`; pass through. `ponytail: env var over DI plumbing for a single scalar; promote to DI if we ever tune per-session.`
- [ ] **Step 3: Verify**  ·  **Step 4: Commit** `fix(llm): honor YAML-configured entry temperature instead of hardcoded 0.3`

---

### Task 6: Bound the runtime event trace

**Files:** Modify `quant/runtime.py:202` · Test `quant/tests/test_trace_bounded.py`

- [ ] **Step 1: Test** — emit 20_000 fake events; assert `len(engine.events) <= 10_000`.
- [ ] **Step 2: Implement** — `from collections import deque`; `self._trace: deque[Event] = deque(maxlen=10_000)` (replace `list[Event] = []`); change `events` property to `tuple(self._trace)`. One-line diff on the writes path.
- [ ] **Step 3: Verify**  ·  **Step 4: Commit** `fix(runtime): cap event trace at 10k so long sessions don't grow heap unbounded`

---

### Task 7: Shutdown `_llm_executor` with the coordinator

**Files:** Modify `quant/coordinator.py:238-242` · Test `quant/tests/test_coordinator_shutdown.py`

- [ ] **Step 1: Test** — instantiate coordinator + engine, call `stop()`, assert `engine._llm_executor._shutdown` is True.
- [ ] **Step 2: Implement**

```python
def stop(self) -> None:
    self._stop.set()
    self._stop_engines()
    for eng in list(self._engines.values()):
        try:
            eng._llm_executor.shutdown(wait=False)
        except Exception:
            pass
    self._feed.close()
    self.started = False
```

- [ ] **Step 3: Verify**  ·  **Step 4: Commit** `fix(coordinator): shutdown per-engine LLM executors on stop()`

---

### Task 8: Run AMT on the underlying futures, not the option premium

**Severity:** CRITICAL — the engine currently computes POC/VAH/VAL/CVD/bubbles on the option's own tick stream, which has theta/IV/sparse-print distortion. Fabio's playbook computes auction structure on the *most liquid underlying* and uses the option only for execution.

**Files:**
- Modify `quant/runtime.py` (`__init__`, `_on_bar_closed`, `_manage_exit`)
- Modify `quant/coordinator.py` (subscribe engine to both feeds, or accept a second gateway)
- Possibly modify `quant/ws_adapter.py` or broker gateway to expose an underlying feed
- Test `quant/tests/test_underlying_feed.py`

**Interfaces:**
- Consumes: existing `self._gateway` (`subscribe(symbol)` / `next_tick()`); the broker already multiplexes symbols per engine.
- Produces: a per-engine `self._underlying_symbol` (derived from `self.symbol` via a small symbol-splitting helper) plus `self._underlying_gateway`. The analyzer runs on underlying ticks; `_manage_exit`/`Position` still price off option ticks for fills/SL/TP.

- [ ] **Step 1: Failing test**

```python
def test_amt_uses_underlying_ticks_when_option_symbol():
    # Engine for "CRUDEOIL 17 AUG 7450 CALL" gets ticks for BOTH
    # "CRUDEOIL" futures and the option. AMT analyzer state must reflect
    # futures ticks only; fills use option ticks.
    ...
```

- [ ] **Step 2: Run, expect FAIL** — currently every tick feeds `self._aggregator.add_tick(tick)` regardless of source.

- [ ] **Step 3: Implement**

```python
# In __init__:
self._underlying_symbol = self._derive_underlying_symbol(self.symbol)
# If a second gateway is available, subscribe it; otherwise (single-feed
# deployments) fall back to deriving from the option tick but log a warning.
self._underlying_gateway = underlying_gateway  # may be None -> fallback

def _derive_underlying_symbol(self, symbol: str) -> str:
    """Map 'CRUDEOIL 17 AUG 7450 CALL' -> 'CRUDEOIL'; 'NIFTY 24500 CE' -> 'NIFTY'.
    Falls back to the first whitespace token — same as the existing _underlying()."""
    return (symbol or "").split()[0] if symbol else ""
```

In the run loop's tick consumption: if the tick's `symbol == self._underlying_symbol`, route to the AMT aggregator; if it matches `self.symbol`, use for OMS/fills/quotes. When only one feed exists, the option tick feeds both paths (today's behavior) but the warning is emitted once.

- [ ] **Step 4: Verify** — AMT analyzer levels (POC/VA) follow the futures ticks in test.
- [ ] **Step 5: Commit** — `feat(engine): run AMT on underlying futures when available, option only for execution`

---

### Task 9: Gate-enforce second-drive / failed-auction sequencing

**Severity:** HIGH — `drive_entry_valid: False` is exported on `AMTResult` and rendered in the prompt, but no gate uses it. A first-drive touch and a second-drive reclaim look identical to the deterministic engine.

**Files:**
- Modify `quant/decision/pipeline.py` (insert gate between 2 and 4)
- Modify `quant/decision/context.py` (carry `drive_entry_valid` / `is_second_drive` / `market_state`)
- Modify `quant/runtime.py` `_entry_prompt_data` (already populates `is_second_drive`) — plumb to `DecisionContext`
- Test `quant/tests/test_gate_failed_auction.py`

**Interfaces:**
- Consumes: `AMTResult.drive_number`, `AMTResult.drive_entry_valid` from `quant/amt/analyzer.py:1294-1295`.
- Produces: gate 3 `gate_failed_auction(ctx) -> GateResult`.

- [ ] **Step 1: Failing test** — signal with `drive_entry_valid=False` must fail gate 3 with reason naming the missing sequence.

- [ ] **Step 2: Implement**

```python
# quant/decision/gates_auction.py  (new)
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

def gate_failed_auction_sequence(ctx: DecisionContext) -> GateResult:
    """Fabio: in BALANCE we only take failed-auction reversion — there must
    be an outside-VA probe, a reclaim, and a return visit (second drive).
    A first-drive touch is not evidence; killer levels get one shot."""
    state = ctx.market_state
    # Continuation trades in IMBALANCE don't need a failed auction.
    if state not in ("BALANCE", "BALANCED"):
        return GateResult(gate=3, passed=True)
    if getattr(ctx, "drive_entry_valid", False):
        return GateResult(gate=3, passed=True)
    drive = getattr(ctx, "drive_number", 0) or 0
    return GateResult(
        gate=3, passed=False,
        reason=f"Failed-auction sequence incomplete (drive={drive}, entry_valid=False)",
    )
```

Renumber later gates 3→4, 4→5, 5→6 in `pipeline.py`; gate 6 stays `gate_llm_consensus`.

- [ ] **Step 3: Verify** — D1-touch signal blocks; D2-with-reclaim passes.
- [ ] **Step 4: Commit** — `feat(gates): enforce failed-auction sequence for balance-state entries`

---

### Task 10: Gate names — symbolic labels, not bare ints

**Files:** Modify `quant/decision/result.py`, all `gates_*.py`, any UI formatter reading `GateResult.gate` · Test `quant/tests/test_gate_names.py`

- [ ] **Step 1: Test** — `GateResult(3, True)` has `name == "FAILED_AUCTION_SEQUENCE"` etc.
- [ ] **Step 2: Implement** — add `GATE_NAMES = {1: "SESSION_PHASE", 2: "POSITION_COOLDOWN", 3: "FAILED_AUCTION_SEQUENCE", 4: "DIRECTION_PROBABILITY", 5: "TRIPLE_A_EDGE", 6: "RISK_REWARD", 7: "LLM_CONSENSUS"}` to `result.py`; add `name` property on `GateResult` (frozen dataclass, computed from int).
- [ ] **Step 3: Verify** — formatter/UI reads `gate_result.name` without a KeyError.
- [ ] **Step 4: Commit** — `refactor(gates): symbolic names for audit trail and UI`

---

### Task 11: Structured block_reasons on every decision

**Files:** Modify `quant/runtime.py` `_emit(DecisionProduced)` site + `quant/contracts/models.py` (decision metadata) · Test `quant/tests/test_decision_block_reasons.py`

- [ ] **Step 1: Test** — a blocked decision's metadata contains a `block_reasons: list[str]` with one entry per failed gate, naming the gate and its failure reason.
- [ ] **Step 2: Implement** — when the pipeline rejects, build `block_reasons = [f"{r.name}: {r.reason}" for r in results if not r.passed]` and attach to `DecisionProduced` via `signal.metadata`. No new event types.
- [ ] **Step 3: Verify**  ·  **Step 4: Commit** — `feat(decision): structured block_reasons on every emitted decision for UI/audit`

---

## Frontend/UI work (explicitly out of scope for this plan)

The reviewer's UI recommendations affect the frontend, not `quant/`:
- Deterministic **setup JSON contract** rendered verbatim.
- **Setup timeline** (`Outside VA -> reclaim -> pullback to LVN -> aggression -> entry`).
- **Profile source** label per decision.
- Gate labels **G1..G6 -> named**.
- Replace "aggression healthy" with quantitative evidence strings.

These should be a separate frontend plan consuming the backend additions from Tasks 9-11 (gate names, block reasons, drive state). No `frontend/` edits in this plan.

---

## Self-review summary

**Added after external review (verified against code):**
- Task 8: underlying-futures AMT — confirmed the engine currently subscribes/analyzes the option contract directly (`quant/runtime.py:235, 248`; `_underlying()` at :725 used only for NPOC keys).
- Task 9: failed-auction gate — confirmed `drive_entry_valid` never reaches `GatePipeline` (`quant/decision/pipeline.py:19-26`).
- Task 10: gate names — confirmed `GateResult.gate` is a bare `int` (`quant/decision/result.py`).
- Task 11: structured block_reasons — half-present in `GateResult.reason`, needs assembly on emission.
- Existing contradiction guard at `runtime.py:797-809` already satisfies the reviewer's "never let the LLM decide direction alone" — no task needed.

**Skipped (ponytail, add when):**
- Rich `exit_rules.py` rewire — adapter for `contracts.entities.Position` isn't justified when the lean live ExitEngine can be extended in place (Task 2). Add when cushion FSM matters.
- Full conviction-first LLM (Gap #1) — architectural rewrite, evaluate after paper-trading new exits.
- Docker/Alembic/pinning — release engineering, not correctness.
- Broker-side work, rate limiting, `_compute_delta` optimization — out of scope or has no user-visible symptom yet.
- Frontend redesign (setup JSON, timeline, profile source) — separate plan.

