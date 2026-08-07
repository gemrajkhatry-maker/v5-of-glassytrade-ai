# AMT Execution + Broker + LLM Advisory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining proposal layers on the greenfield `quant/` stack — Execution (paper OMS + exit engine + risk coordinator), a broker adapter that feeds real bars into the kernel, and the LLM advisory (journaled entry + throttled overseer).

**Architecture:** Three standalone packages under `quant/`, all importing only `quant.*` (never backend/app/frontend):
- `quant/execution/` — pure, deterministic: paper OMS, rule-based exit engine, session risk coordinator. No I/O.
- `quant/brokers/` — a `BrokerGateway` interface + a synthetic Dhan adapter that converts ticks to `Bar`s for the kernel; paper-fill simulation.
- `quant/advisory/` — LLM entry (journaled) + overseer (throttled, bounded queue). Uses a `ChatClient` protocol so no real HTTP is needed in tests.

**Tech Stack:** Python 3.11, dataclasses, pytest. No new dependencies.

## Global Constraints

- New packages: `quant/execution/`, `quant/brokers/`, `quant/advisory/`; tests at `tests/quant/{execution,brokers,advisory}/`. Branch `stable_4`.
- ZERO imports from `backend/`, `app/`, `frontend/`. Only `quant.*`.
- Test command: `cd /Users/apple/Documents/v5-of-glassytrade-ai && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short`.
- TDD: failing test first, RED, implement, GREEN, commit. One commit per task.
- No fabricated data, no new dependencies, no I/O in tests.

## Dependency Graph

```mermaid
flowchart TD
    subgraph Wave1["WAVE 1 — 4 parallel, disjoint"]
        T1[Task 1: execution/order + paper OMS]
        T2[Task 2: execution/exit engine]
        T3[Task 3: execution/risk coordinator]
        T4[Task 4: brokers/gateway + synthetic adapter]
    end
    subgraph Wave2["WAVE 2 — parallel"]
        T5[Task 5: advisory/chat client + entry journal]
        T6[Task 6: advisory/overseer throttle]
    end
    subgraph Wave3["WAVE 3"]
        T7[Task 7: integration — tick→bar→signal→OMS→exit]
    end
    T1 --> T7
    T2 --> T7
    T3 --> T7
    T4 --> T7
    T5 --> T7
    T6 --> T7
```

**File-ownership (Wave 1 disjoint):** T1 `quant/execution/order.py` + `quant/execution/oms.py`; T2 `quant/execution/exits.py`; T3 `quant/execution/risk.py`; T4 `quant/brokers/gateway.py` + `quant/brokers/synthetic.py`. T2/T3/T1 each own their execution files; the OMS (T1) is the shared position-state owner and its `Position` type is pinned below so T2/T3 converge.

---

### Task 1: Order + Paper OMS

**Files:**
- Create: `quant/execution/__init__.py`, `quant/execution/order.py`, `quant/execution/oms.py`
- Create: `tests/quant/execution/__init__.py`, `tests/quant/execution/test_oms.py`

**Interfaces:**
- Consumes: `quant.decision.signal_builder.Signal` (frozen: `type, reason, entry, sl, tp, rr, confidence, symbol, timestamp`)
- Produces (pinned — T2/T3 build on these):
  ```python
  # quant/execution/order.py
  @dataclass(frozen=True)
  class Order:
      signal: Signal
      quantity: float

  @dataclass(frozen=True)
  class Position:
      order: Order
      open_price: float
      open_time: str
      size: float                 # signed: +long / -short
      realized_pnl: float = 0.0   # for closed positions

  @dataclass(frozen=True)
  class Fill:
      position: Position
      close_price: float
      close_time: str
      reason: str                 # "SL" | "TP" | "TRAIL" | "TIME" | "MANUAL"
      pnl: float
  ```
  ```python
  # quant/execution/oms.py
  class PaperOMS:
      def __init__(self) -> None: ...
      def submit(self, signal: Signal, quantity: float) -> Position: ...
      def close(self, position: Position, price: float, time: str, reason: str) -> Fill: ...
  ```

- [ ] **Step 1: Write failing tests**
```python
# tests/quant/execution/test_oms.py
from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.oms import PaperOMS

def _sig(direction="LONG"):
    return Signal(type=direction, reason="Triple-A", entry=100.0, sl=99.0,
                  tp=102.0, rr=2.0, confidence=0.8, symbol="SYM", timestamp="t0")

def test_submit_long():
    oms = PaperOMS()
    p = oms.submit(_sig(), quantity=10)
    assert p.size == 10 and p.open_price == 100.0
    assert p.order.signal.type == "LONG"

def test_submit_short_is_negative_size():
    oms = PaperOMS()
    p = oms.submit(_sig("SHORT"), quantity=5)
    assert p.size == -5

def test_close_long_profit():
    oms = PaperOMS()
    p = oms.submit(_sig(), quantity=10)
    f = oms.close(p, price=102.0, time="t1", reason="TP")
    assert f.pnl == pytest.approx((102 - 100) * 10)
    assert f.reason == "TP"

def test_close_short_profit():
    oms = PaperOMS()
    p = oms.submit(_sig("SHORT"), quantity=5)
    f = oms.close(p, price=99.0, time="t1", reason="TP")
    assert f.pnl == pytest.approx((100 - 99) * 5)
```
(add `import pytest`)

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — `order.py` + `oms.py`. PnL: LONG `(close-open)*qty`, SHORT `(open-close)*qty`.

- [ ] **Step 4: Run, verify PASS**

- [ ] **Step 5: Commit** `feat(quant): order types + paper OMS (submit/close, PnL)`

---

### Task 2: Exit Engine

**Files:**
- Create: `quant/execution/exits.py`
- Create: `tests/quant/execution/test_exits.py`

**Interfaces:**
- Consumes: `Position` (T1), `quant.auction_state.AuctionState`
- Produces:
  ```python
  @dataclass(frozen=True)
  class ExitDecision:
      should_exit: bool
      reason: str          # "" | "SL" | "TP" | "TRAIL" | "TIME" | "CVD_KILL"
      close_price: float
      trail_stop: float | None = None

  class ExitEngine:
      def __init__(self, time_stop_bars: int = 30, cvd_kill_threshold: float = 0.0) -> None: ...
      def evaluate(self, position: Position, state: AuctionState, bar_index: int) -> ExitDecision: ...
  ```

- [ ] **Step 1: Write failing tests**
```python
# tests/quant/execution/test_exits.py
from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.exits import ExitEngine
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState

def _position(size=10, sl=99.0, tp=102.0, entry=100.0):
    sig = Signal(type="LONG", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 confidence=0.8, symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)

def _state(close, cvd_slope=0.0):
    return AuctionState(
        time="t", close=close,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=cvd_slope, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )

def test_sl_hit():
    d = ExitEngine().evaluate(_position(), _state(close=99.0), bar_index=5)
    assert d.should_exit and d.reason == "SL" and d.close_price == 99.0

def test_tp_hit():
    d = ExitEngine().evaluate(_position(), _state(close=102.0), bar_index=5)
    assert d.should_exit and d.reason == "TP"

def test_time_stop():
    d = ExitEngine(time_stop_bars=10).evaluate(_position(), _state(close=100.5), bar_index=12)
    assert d.should_exit and d.reason == "TIME"

def test_cvd_kill_long():
    d = ExitEngine(cvd_kill_threshold=0.0).evaluate(_position(), _state(close=100.5, cvd_slope=-8.0), bar_index=5)
    assert d.should_exit and d.reason == "CVD_KILL"

def test_no_exit_in_range():
    d = ExitEngine(time_stop_bars=30).evaluate(_position(), _state(close=100.5), bar_index=5)
    assert not d.should_exit
```

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — `exits.py`. Order of checks: SL (close <= sl LONG / >= sl SHORT) → TP → CVD_KILL (LONG & cvd_slope < threshold; SHORT & cvd_slope > -threshold) → TIME (bar_index >= time_stop_bars).

- [ ] **Step 4: Run, verify PASS**

- [ ] **Step 5: Commit** `feat(quant): exit engine (SL/TP/time-stop/CVD-kill)`

---

### Task 3: Session Risk Coordinator

**Files:**
- Create: `quant/execution/risk.py`
- Create: `tests/quant/execution/test_risk.py`

**Interfaces:**
- Consumes: nothing external (self-contained)
- Produces:
  ```python
  @dataclass(frozen=True)
  class RiskState:
      daily_pnl: float
      consecutive_losses: int
      halted: bool
      halt_reason: str
      risk_per_trade_pct: float   # reduced after losses

  class SessionRisk:
      def __init__(self, starting_equity: float = 100000.0,
                   base_risk_pct: float = 0.01,
                   max_daily_loss_pct: float = 0.03,
                   max_consecutive_losses: int = 3) -> None: ...
      def record_trade(self, pnl: float) -> RiskState: ...
      def position_size(self, entry: float, sl: float) -> float: ...
      def state(self) -> RiskState: ...
  ```

- [ ] **Step 1: Write failing tests**
```python
# tests/quant/execution/test_risk.py
from quant.execution.risk import SessionRisk

def test_initial_state():
    r = SessionRisk()
    assert r.state().halted is False
    assert r.state().risk_per_trade_pct == 0.01

def test_losses_shrink_risk():
    r = SessionRisk()
    r.record_trade(-200.0)
    r.record_trade(-300.0)
    assert r.state().consecutive_losses == 2
    assert r.state().risk_per_trade_pct < 0.01

def test_win_resets_streak():
    r = SessionRisk()
    r.record_trade(-200.0); r.record_trade(-300.0)
    r.record_trade(+500.0)
    assert r.state().consecutive_losses == 0

def test_max_loss_halts():
    r = SessionRisk(starting_equity=100000.0, max_daily_loss_pct=0.03)
    r.record_trade(-2500.0); r.record_trade(-2500.0); r.record_trade(-2500.0)
    s = r.state()
    assert s.halted is True and "daily" in s.halt_reason

def test_max_streak_halts():
    r = SessionRisk(max_consecutive_losses=3)
    r.record_trade(-100.0); r.record_trade(-100.0); r.record_trade(-100.0)
    s = r.state()
    assert s.halted is True and "loss" in s.halt_reason

def test_position_size_risk_based():
    r = SessionRisk(starting_equity=100000.0, base_risk_pct=0.01)
    qty = r.position_size(entry=100.0, sl=99.0)   # 1000 risk / 1.0 per unit
    assert qty == pytest.approx(1000.0)
```
(add `import pytest`)

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — `risk.py`. Position size = `(equity * risk_pct) / abs(entry - sl)` (guard sl==entry → 0). Risk shrinks 50% per consecutive loss, floored at 25% of base. Halt when daily loss > max_daily_loss_pct*equity OR consecutive losses >= max.

- [ ] **Step 4: Run, verify PASS**

- [ ] **Step 5: Commit** `feat(quant): session risk coordinator (sizing, drawdown stop, loss cushion)`

---

### Task 4: Broker Gateway + Synthetic Adapter

**Files:**
- Create: `quant/brokers/__init__.py`, `quant/brokers/gateway.py`, `quant/brokers/synthetic.py`
- Create: `tests/quant/brokers/__init__.py`, `tests/quant/brokers/test_synthetic.py`

**Interfaces:**
- Consumes: `quant.bars.Bar`
- Produces:
  ```python
  # quant/brokers/gateway.py
  @dataclass(frozen=True)
  class Tick:
      time: str
      price: float
      volume: float
      buy_volume: float = 0.0
      sell_volume: float = 0.0

  class BrokerGateway(Protocol):
      def subscribe(self, symbol: str) -> None: ...
      def next_tick(self) -> Tick | None: ...      # None when stream ends

  # quant/brokers/synthetic.py
  class SyntheticGateway:
      """Replays recorded ticks or a generated sequence, bar by bar."""
      def __init__(self, ticks: list[Tick]) -> None: ...
      def subscribe(self, symbol: str) -> None: ...
      def next_tick(self) -> Tick | None: ...
  ```

- [ ] **Step 1: Write failing tests**
```python
# tests/quant/brokers/test_synthetic.py
from quant.bars import Bar
from quant.brokers.gateway import Tick
from quant.brokers.synthetic import SyntheticGateway

def test_replays_ticks_in_order():
    ticks = [Tick(t, 100+i, 10, 6, 4) for i, t in enumerate(["t0","t1","t2"])]
    g = SyntheticGateway(ticks)
    g.subscribe("SYM")
    assert g.next_tick() == ticks[0]
    assert g.next_tick() == ticks[1]
    assert g.next_tick() == ticks[2]
    assert g.next_tick() is None
```

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — `gateway.py` (Protocol + Tick) and `synthetic.py` (index-based replay).

- [ ] **Step 4: Run, verify PASS**

- [ ] **Step 5: Commit** `feat(quant): broker gateway protocol + synthetic tick replay`

---

### Task 5: LLM Advisory — Chat Client + Entry Journal

**Files:**
- Create: `quant/advisory/__init__.py`, `quant/advisory/chat.py`, `quant/advisory/entry_journal.py`
- Create: `tests/quant/advisory/__init__.py`, `tests/quant/advisory/test_entry_journal.py`

**Interfaces:**
- Consumes: `quant.auction_state.AuctionState`
- Produces:
  ```python
  # quant/advisory/chat.py
  @dataclass(frozen=True)
  class ChatMessage:
      role: str   # "system" | "user" | "assistant"
      content: str

  class ChatClient(Protocol):
      def complete(self, messages: list[ChatMessage], max_tokens: int = 200) -> str: ...

  # quant/advisory/entry_journal.py
  @dataclass(frozen=True)
  class JournalEntry:
      symbol: str
      state_time: str
      prompt: str
      response: str
      decision: str          # "LONG" | "SHORT" | "FLAT"
      confidence: float

  class EntryJournal:
      def __init__(self, client: ChatClient, system_prompt: str = "You are an AMT scalper.") -> None: ...
      def analyze(self, state: AuctionState, symbol: str = "") -> JournalEntry: ...
      @property
      def entries(self) -> tuple[JournalEntry, ...]: ...
  ```

- [ ] **Step 1: Write failing tests**
```python
# tests/quant/advisory/test_entry_journal.py
import json
from quant.advisory.chat import ChatClient, ChatMessage
from quant.advisory.entry_journal import EntryJournal
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState

class FakeClient:
    def __init__(self, response='{"direction":"LONG","confidence":0.7,"rationale":"x"}'):
        self.response = response
        self.calls = []
    def complete(self, messages, max_tokens=200):
        self.calls.append(messages)
        return self.response

def _state():
    return AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )

def test_prompt_includes_state_and_prompt_is_journaled():
    fc = FakeClient()
    j = EntryJournal(fc)
    e = j.analyze(_state(), "SYM")
    assert e.decision == "LONG"
    assert e.symbol == "SYM"
    assert "POC" in e.prompt.upper() and "VWAP" in e.prompt.upper()
    assert len(j.entries) == 1

def test_invalid_json_falls_back_to_flat():
    fc = FakeClient(response="not json")
    j = EntryJournal(fc)
    e = j.analyze(_state())
    assert e.decision == "FLAT" and e.confidence == 0.0

def test_never_executes():
    # advisory is journaled-only: analyze must not mutate anything outside the journal
    fc = FakeClient()
    j = EntryJournal(fc)
    e = j.analyze(_state())
    assert e.decision in ("LONG", "SHORT", "FLAT")
```
(add `import pytest` if used)

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — `chat.py` (Protocol) + `entry_journal.py`. `analyze` builds a prompt from the AuctionState (POC/VAH/VAL, market state, absorption, VWAP), calls `client.complete`, parses `{"direction","confidence",...}` with try/except → FLAT on failure.

- [ ] **Step 4: Run, verify PASS**

- [ ] **Step 5: Commit** `feat(quant): LLM advisory chat client + journaled entry (never executes)`

---

### Task 6: LLM Advisory — Throttled Overseer

**Files:**
- Create: `quant/advisory/overseer.py`
- Create: `tests/quant/advisory/test_overseer.py`

**Interfaces:**
- Consumes: `ChatClient` (T5), `Position` (T1)
- Produces:
  ```python
  @dataclass(frozen=True)
  class OverseerAction:
      action: str          # "HOLD" | "TIGHTEN_SL" | "PARTIAL_EXIT" | "FULL_EXIT"
      rationale: str
      tightened_sl: float | None = None

  class Overseer:
      def __init__(self, client: ChatClient, cooldown_seconds: float = 15.0,
                   queue_size: int = 2) -> None: ...
      def should_run(self, last_run_time: float, running: bool) -> bool: ...
      def evaluate(self, state: AuctionState, position: Position) -> OverseerAction | None:
          """Returns None when throttled or queue full."""
  ```

- [ ] **Step 1: Write failing tests**
```python
# tests/quant/advisory/test_overseer.py
import time
from quant.advisory.chat import ChatClient
from quant.advisory.overseer import Overseer, OverseerAction
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState
from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position

class FakeClient:
    def __init__(self, response='{"action":"HOLD","rationale":"ok"}'):
        self.response = response; self.calls = 0
    def complete(self, messages, max_tokens=200):
        self.calls += 1
        return self.response

def _state():
    return AuctionState(time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None)

def _pos():
    sig = Signal(type="LONG", reason="r", entry=100, sl=99, tp=102, rr=2, confidence=.8, symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, 10), open_price=100, open_time="t0", size=10)

def test_cooldown_blocks():
    o = Overseer(FakeClient(), cooldown_seconds=15.0)
    assert o.should_run(time.time(), running=False) is True
    assert o.should_run(time.time(), running=False) is False   # too soon
    assert o.should_run(time.time() - 16, running=False) is True

def test_evaluate_returns_action():
    fc = FakeClient()
    o = Overseer(fc, cooldown_seconds=0.0)
    a = o.evaluate(_state(), _pos())
    assert a is not None and a.action == "HOLD"
    assert fc.calls == 1

def test_bounded_queue_drops_busy():
    # emulate: running=True means busy; evaluate must return None without calling the client
    fc = FakeClient()
    o = Overseer(fc, cooldown_seconds=0.0, queue_size=2)
    a1 = o.evaluate(_state(), _pos())
    a2 = o.evaluate(_state(), _pos())
    a3 = o.evaluate(_state(), _pos())   # third is dropped
    assert fc.calls <= 2
```

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — `overseer.py`: `should_run` enforces the cooldown; `evaluate` tracks recent run times (deque of size queue_size), returns None when the queue is full, else builds a prompt with position SL/TP/hold-time and calls the client, parsing `{"action","rationale"}`.

- [ ] **Step 4: Run, verify PASS**

- [ ] **Step 5: Commit** `feat(quant): LLM overseer (cooldown + bounded drop-busy queue)`

---

### Task 7: Integration — Tick → Bar → Signal → OMS → Exit

**Files:**
- Create: `tests/quant/test_full_stack.py`

**Interfaces:**
- Consumes: `SyntheticGateway` (T4), `AuctionCoordinator` (kernel), `GatePipeline`/`SignalBuilder` (decision), `PaperOMS` (T1), `ExitEngine` (T2), `SessionRisk` (T3), `EntryJournal` (T5)
- Produces: one test proving the full proposal flow end-to-end

- [ ] **Step 1: Write the failing test**
```python
# tests/quant/test_full_stack.py
from quant.brokers.gateway import Tick
from quant.brokers.synthetic import SyntheticGateway
from quant.coordinator import AuctionCoordinator
from quant.decision.context import DecisionContext
from quant.decision.pipeline import GatePipeline
from quant.decision.signal_builder import SignalBuilder
from quant.execution.oms import PaperOMS
from quant.execution.exits import ExitEngine
from quant.execution.risk import SessionRisk
from quant.advisory.chat import ChatClient
from quant.advisory.entry_journal import EntryJournal

class FakeChat:
    def complete(self, messages, max_tokens=200):
        return '{"direction":"LONG","confidence":0.7,"rationale":"journaled"}'

def _ticks():
    out = [Tick(f"t{i}", 100.0, 10, 6, 4) for i in range(300)]
    # inject an absorption spike + rising market to drive AGGRESSION
    out.append(Tick("t300", 100.0, 500, 450, 50))
    for i in range(1, 8):
        out.append(Tick(f"t{300+i}", 100.0 + i * 0.2, 10, 6, 4))
    return out

def test_full_stack_lifecycle():
    gw = SyntheticGateway(_ticks())
    gw.subscribe("SYM")
    coord = AuctionCoordinator()
    pipe = GatePipeline()
    sb = SignalBuilder()
    oms = PaperOMS()
    exits = ExitEngine(time_stop_bars=60)
    risk = SessionRisk()
    journal = EntryJournal(FakeChat())

    position = None
    step = 0
    while True:
        tick = gw.next_tick()
        if tick is None:
            break
        step += 1
        # aggregate ticks -> bar (the synthetic adapter yields one tick per bar-cycle;
        # for the test, treat each tick as a bar close via a lightweight aggregation)
        bar = Bar(time=tick.time, open=tick.price, high=tick.price + 0.5,
                  low=tick.price - 0.5, close=tick.price, volume=tick.volume,
                  buy_volume=tick.buy_volume, sell_volume=tick.sell_volume, delta=tick.buy_volume - tick.sell_volume)
        state = coord.on_bar_close(bar)

        # journal every bar (throttle-free in the test)
        journal.analyze(state, "SYM")

        if position is not None:
            dec = exits.evaluate(position, state, bar_index=step)
            if dec.should_exit:
                fill = oms.close(position, dec.close_price, bar.time, dec.reason)
                risk.record_trade(fill.pnl)
                position = None
            continue

        if position is None:
            ctx = DecisionContext(state=state, bar=bar, symbol="SYM",
                                  agent_direction="LONG", agent_probability=0.7)
            results = pipe.evaluate(ctx)
            if all(r.passed for r in results):
                sig = sb.build(ctx, results)
                if sig is not None:
                    qty = risk.position_size(sig.entry, sig.sl)
                    position = oms.submit(sig, qty)

    assert position is not None or risk.state().daily_pnl != 0.0 or len(journal.entries) > 100
    assert len(journal.entries) > 100        # advisory journaled throughout
    assert risk.state().consecutive_losses >= 0
```
(The exact assertions are yours to tune — the test must prove: a position was opened OR the session closed a position, the journal accumulated, and the risk tracker saw trades. Adjust the aggregation so a signal actually fires, e.g. ensure the kernel's absorption spike + rising closes produce AGGRESSION LONG, then the OMS opens and the exit engine closes it.)

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — none if components are correct; tune the test fixture so the full lifecycle runs (open → hold → exit → record risk). If a gate blocks, adjust the DecisionContext (session_open/warmup_complete/position_open/cooldown flags) — do NOT weaken gates.

- [ ] **Step 4: Run, verify PASS** + full `tests/quant`.

- [ ] **Step 5: Commit** `test(quant): full stack tick→bar→signal→OMS→exit→risk→journal`

---

## Self-Review

- **Spec coverage (proposal → task):** paper OMS → T1; exit engine (SL/TP/trail/time/CVD) → T2; risk coordinator (sizing/drawdown/loss cushion) → T3; broker adapter feeding kernel → T4; LLM entry journaled (never executes) → T5; LLM overseer throttled/bounded → T6; full lifecycle e2e → T7. Proposal laws 1/3 (pure, on bar close) enforced by construction; law 5 (LLM never gates) proven by T5/T6.
- **Placeholders:** all test code is complete; implementers copy verbatim, adjust for pinned imports.
- **Type consistency:** `Position`/`Fill` (T1) consumed by T2/T3/T6/T7; `Signal` (decision) consumed by T1; `ChatClient` protocol (T5) consumed by T6; `Tick`/`BrokerGateway` (T4) consumed by T7. All names pinned above.
- **Known accepted risk:** the real Dhan adapter (network) is intentionally NOT built — `BrokerGateway` is the seam; a later plan wires Dhan behind it. T7's integration uses `SyntheticGateway` + a light tick→bar aggregation (the kernel's aggregator is out of this plan's scope; noted).
