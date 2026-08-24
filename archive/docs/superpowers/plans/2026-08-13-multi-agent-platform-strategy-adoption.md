# Multi-Agent Plan — Platform-first, Strategy-as-Plugin Adoption

**Date:** 2026-08-13
**Scope:** `quant/`, `backend/`, `brokers/`, `tests/`
**Source:** follows `docs/STRATEGY_ENGINE_SEPARATION.md` (strategy seam) and the
event-driven/DDD architecture proposal.
**Strategy:** build the infrastructure (engine) once as a stable platform, then
implement strategies on a *standard interface*. Strategy owns the **full trade
lifecycle** (entry + exit + sizing); the engine owns only plumbing.

---

## 0. The contract (locked before any agent starts)

### 0.1 Interface — full lifecycle, split by role (ISP)

```python
# quant/strategy.py  (the ONLY cross-agent contract — freeze first)
class EntryPolicy(Protocol):
    def evaluate(self, ctx: DecisionContext) -> QuantDecision: ...

class ExitPolicy(Protocol):
    def evaluate_exit(self, position, ctx: DecisionContext) -> ExitDecision: ...

class SizingPolicy(Protocol):
    def size(self, equity: float, signal: Signal, ctx: DecisionContext) -> float: ...

class Strategy(EntryPolicy, ExitPolicy, SizingPolicy, Protocol):
    name: str
```

- **Input** (`DecisionContext`): immutable auction snapshot + closed bar + session
  facts (position open, cooldown, risk halt, agent direction, equity, risk %, tick
  size). Contract-freeze adds `held_bars` (bars since entry) for the exit role.
- **Outputs**: `QuantDecision` (entry), `ExitDecision` (should_exit/close_price/reason),
  `float` quantity (sizing).

### 0.2 Defaults keep the engine byte-identical today

Infra ships default policies the strategy may compose or override:

| Role | Default (infra-owned) | Source today |
|---|---|---|
| Entry | Triple-A + VA-fade | `DecisionService` |
| Exit | SL/TP/trail/time-stop | `quant/execution/exits.py` `ExitEngine` |
| Sizing | fixed-fractional + clamp | `quant/execution/risk.py` + `SignalBuilder.size` |

A strategy that only wants a new *entry* edge inherits default exit/sizing; a
strategy that wants full ownership overrides all three.

### 0.3 The rule every agent enforces

> The strategy is **pure** — it never touches `IBroker`, `IStorage`, the event
> bus, the loop, or wall-clock. Same context → same decision. The engine calls
> the strategy's roles at lifecycle points and does all I/O.

---

## 1. Non-negotiables (each gate verifies)

1. **One engine, one event bus, one `Signal`, one bar/candle type.**
2. **Mode = event source only** (`LiveFeed | ReplaySource | HistoricalFile | Simulator`);
   no `if mode == ...` in decision/execution logic.
3. **Replay == live** byte-for-byte (golden-file in CI).
4. **Fail closed** — a strategy/decision failure blocks new entries but never
   orphans an open position, exit/watchdog, or persistence.
5. **No delete from the live path without a reference scan + parity gate.**

---

## 2. Agents (missions, file ownership, gates)

File ownership is **disjoint** so agents run in parallel with minimal conflicts.
Shared files (the contract) are frozen in Agent 0 and touched only by Agent 0.

### Agent 0 — Contract freeze (blocker, single agent, lands first)

- **Mission:** finalize `quant/strategy.py` full-lifecycle interface + default
  policies; extend `DecisionContext` with `held_bars`; define `ExitDecision`
  import path; update `register_strategy`/`get_strategy` docstring.
- **Files:** `quant/strategy.py`, `quant/decision/context.py`, `quant/decision/decision_service.py`
  (signature only), `tests/quant/test_strategy.py`.
- **Gate:** `get_strategy()` returns an object satisfying `isinstance(s, Strategy)`;
  existing 16 strategy/runtime/decision tests green.

### Agent A — Event-model unification (infra, parallel after 0)

- **Mission:** one `DomainEvent` base + one `EventBus`/`EventStore`; fold
  `quant/events.py` runtime events into `quant/contracts/events.py`; pick one bus.
- **Files:** `quant/contracts/events.py`, `quant/contracts/event_store.py`, `quant/events.py`.
- **Gate:** golden-file determinism byte-identical; `test_event_store.py`,
  `test_events.py`, `test_golden_runtime.py` green.

### Agent B — Engine delegation refactor (infra, parallel after 0)

- **Mission:** `QuantEngine` + `QuantBridge` call the strategy's three roles
  (entry/exit/size) instead of owning `ExitEngine`/`SessionRisk` directly; extract
  today's exit + sizing logic into `DefaultExitPolicy`/`DefaultSizingPolicy`.
- **Files:** `quant/runtime.py`, `quant/execution/exits.py`, `quant/execution/risk.py`,
  `quant/decision/signal_builder.py` (`size`), `backend/app/application/services/quant_bridge.py`.
- **Gate:** paper-protocol + full-stack + runtime tests byte-identical (defaults preserve behavior).

### Agent C — Canonical types & ports (infra, parallel after 0)

- **Mission:** one bar/candle type; one numeric rule (`Decimal` for money/prices,
  documented `float` only for indicator math); remove the `float()` normalization
  hack; ensure `ports/*` are the only seams the domain touches.
- **Files:** `quant/contracts/ports/*`, `quant/contracts/value_objects.py`,
  `quant/bars.py`, `backend/app/application/services/session_event_router.py` (numeric normalization).
- **Gate:** `test_session_event_router.py`, `test_decision_service.py`, bar/candle tests green.

### Agent D — Reference strategy on the new interface (strategy, after 0 + B)

- **Mission:** implement `DecisionService` as the first full-lifecycle `Strategy`:
  entry = Triple-A + VA-fade (unchanged), exit = `DefaultExitPolicy`, sizing =
  `DefaultSizingPolicy`; add a second minimal `MeanReversionStrategy` to prove the
  swap path end-to-end.
- **Files:** `quant/decision/decision_service.py`, `quant/decision/va_fade.py`,
  `quant/strategies/mean_reversion.py` (new), `tests/quant/test_strategy.py`.
- **Gate:** `test_decision_service.py` green; new test: two strategies, same tape,
  different decisions — engine never changed.

### Agent E — Replay-parity harness (infra, after B + D)

- **Mission:** golden tape in CI; `QUANT_RECORD_REPLAY` captures decisions **and
  fills**, not just bars+auction; assert `AuctionState → Decision → Signal → Order`
  identical live vs replay.
- **Files:** `tests/system/test_quant_*_e2e.py`, replay capture (`quant_bridge.py` record path).
- **Gate:** replay == live byte-for-byte on the committed tape.

### Agent F — Kill the mode fork (infra, after E)

- **Mission:** replace `QUANT_EXECUTION_MODE ∈ {off,shadow,paper,live}` branching
  with the event-source abstraction; paper/live become broker-adapter concerns.
- **Files:** `backend/app/application/services/session_event_router.py`,
  `backend/app/application/services/quant_bridge.py`, `backend/app/config_models/settings_adapter.py`.
- **Gate:** `test_quant_execution_mode.py` rewritten to assert "source, not mode";
  paper acceptance gate passes.

### Agent G — Hardening & CI (runs throughout, certifies the end)

- **Mission:** add `mypy`; un-skip/delete skipped tests; verify `start*.sh` resolve
  interpreter + `PYTHONPATH=backend:.` consistently; keep `ruff`/`compileall`/pytest green.
- **Files:** `.github/workflows/test.yml`, `backend/pytest.ini`, `Makefile`, `start*.sh`.
- **Gate:** CI green including mypy + parity; clean-checkout preflight passes.

---

## 3. Sequencing / dependency graph

```
Agent 0 (contract freeze) ──► A (events)      ─┐
                        ├──► B (engine)       ─┼─► E (parity) ─► F (kill mode fork)
                        ├──► C (types/ports)  ─┘        ▲
                        └──► D (strategy) ──────────────┘   (D needs B's calls)
Agent G (hardening) runs in parallel with everything; certifies at the end.
```

- **Only A/C/G are safe to start the same hour as 0** (no execution risk).
- **B and D are the execution-critical pair**; B lands first, D integrates on top.
- **E must follow B+D**; **F must follow E**.

---

## 4. Safety rules (every agent)

1. Never delete from the live entry path by name/size alone — reference-scan all
   source/tests/docs first.
2. Preserve the current live engine until parity is proven on the golden tape.
3. Keep broker adapters, exit/watchdog, reconciliation, and idempotent-close intact
   until their contract tests pass.
4. Each batch is a discrete commit that passes `compileall` + focused tests;
   execution-path batches additionally require the replay/parity or integration gate.
5. No credential changes, no `git push`, no live-market actions.
