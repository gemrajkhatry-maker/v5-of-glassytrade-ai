# Event-Sourced Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the event-sourced architecture (EventStore → EngineState → project_state → ViewState) by fixing remaining defects, eliminating duplicate models, and hardening the money path so the system is safe for live trading.

**Architecture:** The quant layer now has a true event-sourced core — `EventStore` with HMAC-SHA256 chain, `EngineState` as immutable single source of truth, `apply_event()` pure transitions, `project_state()` canonical view derivation. The remaining work is to align every other module to this architecture, close the 7 critical live-trading defects, and eliminate the duplicate domain models that exist 2–3× per concept.

**Tech Stack:** Python 3.13, pytest, React 19 + Vite + Zustand + vitest. No new dependencies.

---

## Global Constraints

- **Real-money trading system.** Correctness > cleverness, determinism > convenience, deletion > refactoring.
- **Behavior-preserving** extractions only (strangler pattern). Every refactor gated by golden-trace replay or equivalent tests.
- **Fresh failing test before every fix.** Never fix without a test that catches the current bug.
- **Test command:** `.venv/bin/python -m pytest tests/quant -q tests/backend -q` (or equivalent per lane).
- **Commit atomicity:** one logical change per commit with a descriptive message.
- **`quant/` must remain pure** — zero `backend/` or `app/` imports.
- **Every deliberate limit/ceiling carries a `# ponytail:` comment** explaining why.
- **No new abstractions** unless there are two implementations today.

---

## Current State (after analysis)

The event-sourcing foundation is built and wired:
- `quant/event_store.py` — append-only log, HMAC-SHA256 checksum chain, `fold()` derives state
- `quant/state_machine.py` — `EngineState` frozen dataclass (single source of truth), `with_bar/with_position/without_position/with_risk` transitions
- `quant/transitions.py` — `apply_event()` pure state transition function
- `quant/state.py` — `project_state(EngineState)` canonical path, `StateProjector` deprecated
- `quant/events.py` — typed events, `EventBus` with priority dispatch, synchronous
- `quant/runtime.py` — engine loop emits events → `EventStore.append()` → `fold()` → `project_state()`
- `quant/multi_engine.py` — coordinator with per-engine `EventStore`, startup reconcile, EOD watchdog
- `quant/execution/ports.py` — `IOMS` Protocol (submit/close/close_partial/add_pyramid)
- `quant/execution/oms.py` — `PaperOMS` (lot-snapped, pyramid-aware)
- Backend shell: DI container, lifespan, routers all wired

---

## Phase 0: Triage the Architecture Review Findings

The 2026-08-28 principal architecture review found **7 critical correctness violations** and **3 structural problems**. These are the highest-priority items.

### Phase 0 Deliverable
- All 7 money-path defects closed with tests
- Duplicate domain models reduced to single sources of truth
- God classes decomposed
- Layer cycles broken

---

### Phase 1: Money-Path Correctness (Critical — fix FIRST)

#### Task 1.1: `PortfolioRiskAuthority` limits must actually bind

**Problem:** `portfolio_risk.py:28-29` ships `max_portfolio_risk_pct=0.95` and `max_portfolio_daily_loss_pct=0.95`. On ₹10L that permits ₹9.5L of aggregate open risk — the cross-engine ceiling effectively doesn't exist.

**Files:**
- `quant/execution/portfolio_risk.py` — replace 0.95 defaults with conservative derived caps
- `quant/multi_engine.py` — construction site (~:260) — verify `PortfolioRiskAuthority` wiring
- `tests/quant/execution/test_portfolio_risk_limits.py` — new test file

**Interfaces:**
- Consumes: `PortfolioRiskAuthority(starting_equity, max_portfolio_risk_pct, max_portfolio_daily_loss_pct)`
- Produces: `PortfolioRiskAuthority.can_accept(equity, requested_risk)` → bool

- [ ] **Step 1: Write failing test** — construct a 4-engine book where each engine is individually within `SessionRisk` limits; assert the authority rejects the 3rd/4th entry under new caps, and that realized loss at the new daily cap halts new entries.
- [ ] **Step 2: Run test to verify it fails** — `.venv/bin/python -m pytest tests/quant/execution/test_portfolio_risk_limits.py -v`
- [ ] **Step 3: Fix `portfolio_risk.py`** — replace 0.95 defaults with caps derived from `risk_per_trade_pct` and `max_daily_loss_pct` config values. Add `# ponytail:` comment on the derivation.
- [ ] **Step 4: Run suite** — `.venv/bin/python -m pytest tests/quant/execution -q tests/quant -q`
- [ ] **Step 5: Commit** — `fix(quant): make portfolio risk ceiling bind`

#### Task 1.2: One capital book, not one per engine

**Problem:** `multi_engine.py:1002-1003` builds a fresh `Portfolio()` per live engine. Capital state duplicated N ways with no reconciliation between them.

**Files:**
- `quant/multi_engine.py` (`:1002-1014`)
- `quant/execution/live_oms.py` — adapt to shared portfolio
- `tests/quant/execution/test_shared_portfolio.py` — new test file

- [ ] **Step 1: Write failing test** — two engines, each entering a position; assert the shared book reflects both, and that a drawdown in engine 1 throttles sizing in engine 2.
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Hoist a single `Portfolio` to `QuantCoordinator.__init__`** and pass to every `LiveOMS` at `_spawn_engine()`. Verify `IBroker.execute_order` consumers tolerate a shared, concurrently-mutated book. If any path assumes engine-local ownership, ledger it and add a guard.
- [ ] **Step 4: Run suite**
- [ ] **Step 5: Commit** — `fix(quant): share Portfolio across all LiveOMS instances`

#### Task 1.3: Live order quantity must not be discarded

**Problem:** Engine sizes via `SessionRisk.position_size`, but `LiveOMS`/`broker_mapper` drop the qty; `DhanBrokerAdapter._resolve_quantity` re-sizes from a fresh `Portfolio` frozen at `INITIAL_CAPITAL`. Option `lot_size` never set → non-lot-multiple orders → exchange rejection.

**Files:**
- `quant/execution/live_oms.py` — pass engine-computed quantity through, don't re-size
- `brokers/broker/dhan/` — `broker_mapper.py` and `dhan_broker_adapter.py` — honor the quantity from the engine, only validate lot-multiple
- `tests/` — test that engine-computed quantity reaches the broker unmodified

- [ ] **Step 1: Write failing test** — assert that a signal with quantity=5.0 reaches the broker as 5.0 (after lot-snap), not re-sized against a fresh Portfolio.
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Fix** — remove the re-sizing in `live_oms.py` and `broker_mapper.py`. The engine's `SessionRisk.position_size()` already accounts for portfolio risk. The broker adapter should only lot-snap and validate.
- [ ] **Step 4: Run suite**
- [ ] **Step 5: Commit** — `fix(quant): preserve engine-computed quantity through live OMS`

#### Task 1.4: `risk_per_trade_pct` from config must reach engines

**Problem:** `live.yaml:17` sets `risk_per_trade_pct=0.002` but `composition_root.py:134-146` never propagates it. Engines default to 0.95 (not 0.2%).

**Files:**
- `backend/app/application/di/composition_root.py` (`:134-146`) — add `risk_per_trade_pct` to `coord_config`
- `quant/multi_engine.py` (`:883`) — verify it reads from config
- `tests/` — test that config value reaches `SessionRisk`

- [ ] **Step 1: Write failing test** — assert `SessionRisk` uses the configured `risk_per_trade_pct`, not the default.
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Fix** — thread `risk_per_trade_pct` from `SystemConfig` through `compose_container` → `QuantCoordinator` → each engine constructor.
- [ ] **Step 4: Run suite**
- [ ] **Step 5: Commit** — `fix(di): propagate risk_per_trade_pct from config to engines`

#### Task 1.5: Broker rejection must not kill engine thread

**Problem:** No try/except around `oms.submit`. `RuntimeError` propagates → `_crashed` → symbol dead for the day. `register_open` reservation never released.

**Files:**
- `quant/runtime.py` (~:895) — wrap `oms.submit` in try/except; on failure, release portfolio reservation
- `quant/execution/live_oms.py` — add `try/except` in `submit`; return error signal or raise typed exception
- `tests/` — test that a broker rejection does not crash the engine thread

- [ ] **Step 1: Write failing test** — mock `IOMS.submit` to raise `RuntimeError`; assert engine thread continues, risk reservation is released, symbol is not marked crashed.
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Fix** — wrap `oms.submit` in try/except in `runtime.py`. On failure: release portfolio reservation via `PortfolioRiskAuthority`, emit error event, continue. Add typed `OrderRejected` event to `events.py`.
- [ ] **Step 4: Run suite**
- [ ] **Step 5: Commit** — `fix(quant): survive broker rejection without crashing engine`

#### Task 1.6: SIGTERM emergency halt must not double-close

**Problem:** `emergency_halt(force_close=True)` bypasses `_close_lock` and sends a second opposing MARKET order. If first close filled, the second opens a fresh opposite intraday position. Also bypasses pyramids.

**Files:**
- `quant/multi_engine.py` (`:558-583`) — route through `force_close_position()` (engine's own lock-serialized path)
- `quant/runtime.py` — verify `force_close_position` uses `_close_lock` and `PositionManager`
- `tests/` — test that emergency halt with force_close closes positions once, not twice

- [ ] **Step 1: Write failing test** — position open, call `emergency_halt(force_close=True)`; assert exactly ONE close order, no opposite position created.
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Fix** — ensure `emergency_halt` uses the same `force_close_position` path the EOD watchdog uses (engine's `_close_lock`, `PositionManager` aware, pyramid-aware). Remove any inline `oms.close()`.
- [ ] **Step 4: Run suite**
- [ ] **Step 5: Commit** — `fix(quant): prevent double-close in emergency halt`

#### Task 1.7: Short-position reconciliation must handle signed sizes

**Problem:** Broker reports `size=abs(qty)` (always +) vs DB signed size → any open SHORT at restart = guaranteed "discrepancy" → strict mode refuses to boot.

**Files:**
- `quant/multi_engine.py` (`_signed_broker_qty` exists but may not be wired in reconciliation path)
- `backend/app/application/di/` — `StartupReconciliation` — verify it uses `_signed_broker_qty`
- `tests/` — test that a SHORT position reconciles correctly

- [ ] **Step 1: Write failing test** — broker returns SHORT position with `size=10, side=SHORT`; assert reconciliation normalizes to signed -10.
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Fix** — ensure `StartupReconciliation` uses `_signed_broker_qty` consistently. If reconciliation path bypasses it, add it.
- [ ] **Step 4: Run suite**
- [ ] **Step 5: Commit** — `fix(reconciliation): normalize broker signed quantities`

---

### Phase 2: Structural De-Duplication (High Priority)

#### Task 2.1: Eliminate duplicate domain models

**Problem:** 3 candle types (`Bar`, `OHLC`, `FloatOHLC`), 2 signal models, 3 position models, 2 order models, 2 tick models, 6 PnL sites, 3 sizing impls, 4 lot-snap sites, 3 VWAPs, 5 session/time parsers.

**Strategy:** Freeze the engine-domain models as the single source of truth. Map everything else at the boundary (broker adapter, WS adapter, frontend).

**Files:**
- `quant/bars.py` — `Bar` is the engine truth
- `quant/execution/order.py` — `Signal`, `Position`, `Order`, `Fill` are engine truth
- `quant/state_machine.py` — `EngineState`, `PositionState`, `RiskState` are state truth
- `brokers/broker/entities.py` — keep only broker-transport models; remove domain duplication
- `quant/contracts/entities.py` — consolidate with execution models
- `shared/entities/models.py` — consolidate or remove
- `frontend/types.ts` — generate from WS contract, not hand-maintained

**Approach:** One task per duplicate cluster. Each task:
1. Identify the canonical model
2. Remove the duplicate
3. Add adapter/mapping at the boundary
4. Test

#### Task 2.1a: Consolidate signal/position/order models

- [ ] **Step 1:** Audit `signal_builder.py:49`, `entities.py:31`, `execution/order.py:14` — determine canonical
- [ ] **Step 2:** Remove `entities.py` signal model; use `signal_builder.Signal` everywhere
- [ ] **Step 3:** Remove `shared/entities/models.py` position/order/tick duplicates; use `execution/order.py` + `bars.py`
- [ ] **Step 4:** Update broker adapter to map to engine models at boundary
- [ ] **Step 5:** Test

#### Task 2.1b: Consolidate candle models

- [ ] **Step 1:** Audit `Bar`, `OHLC`, `FloatOHLC` — `Bar` is engine truth
- [ ] **Step 2:** Remove `OHLC` and `FloatOHLC` from `contracts/value_objects.py`; replace with `Bar` at boundaries
- [ ] **Step 3:** Update all consumers
- [ ] **Step 4:** Test

#### Task 2.1c: Consolidate VWAP and session/time parsing

- [ ] **Step 1:** Audit `aggregator.py`, `amt/profile/vwap.py`, `contracts/market_data_utils.py` — pick canonical
- [ ] **Step 2:** Audit `session_gates.py`, `amt/session/context.py`, `state.py`, `aggregator.py`, `contracts/timezones.py` — pick canonical
- [ ] **Step 3:** Remove duplicates, add adapter at boundary
- [ ] **Step 4:** Test

---

### Phase 3: God Class Decomposition (Medium Priority)

#### Task 3.1: Decompose `QuantEngine` (runtime.py, 1218 LOC)

**Strategy:** Extract pure functions and stateful subsystems. The engine loop stays the orchestrator; extracted modules become injectable.

**Extraction targets:**
- `DecisionPipeline` — gates + signal builder + context builder (already partially in `decision/`)
- `ExitEngine` — already extracted (`execution/exits.py`)
- `PositionManager` — already extracted (`position_manager.py`)
- `AMTEngine` — already extracted (`amt_engine.py`)
- `EventSourcingLayer` — `EventStore` + `fold()` + `project_state()` (already extracted)

**Remaining decomposition:**
- `_decide()` → `DecisionPipeline.evaluate()` call (currently inline)
- `_run_inner()` → orchestrator that calls extracted modules
- `_check_pyramid()` → pyramid logic into `PositionManager`

- [ ] **Step 1:** Profile `runtime.py` — identify the 3 largest methods by LOC
- [ ] **Step 2:** Extract each into a dedicated module/class with pure function signature
- [ ] **Step 3:** Write golden-trace test capturing `_decide()` output before/after
- [ ] **Step 4:** Verify golden traces pass
- [ ] **Step 5:** Commit

#### Task 3.2: Decompose `QuantCoordinator` (multi_engine.py, 1066 LOC)

**Extraction targets:**
- `EngineLifecycle` — `_spawn_engine()`, `_stop_engine()`, `_stop_engines()`
- `EODWatchdog` — `_eod_watchdog_loop()`, `eod_square_off()`, `check_and_rotate_dead_symbols()`
- `ContractScanner` — `_scan()`, `_refresh_gex()`, `_resolve_futures_symbols()`
- `HealthReporter` — `crashed_engines()`, `stale_engines()`, `journal_consecutive_failures()`
- `ReconciliationService` — `_intraday_reconcile()`, `_periodic_state_reconcile()`, `startup_reconcile()`

- [ ] **Step 1:** Extract `EngineLifecycle` into `quant/coordinator/lifecycle.py`
- [ ] **Step 2:** Extract `EODWatchdog` into `quant/coordinator/eod.py`
- [ ] **Step 3:** Extract `ContractScanner` into `quant/coordinator/scanner.py`
- [ ] **Step 4:** Extract `HealthReporter` into `quant/coordinator/health.py`
- [ ] **Step 5:** `QuantCoordinator` becomes a thin orchestrator importing these
- [ ] **Step 6:** Test

#### Task 3.3: Remove dead code (parallel with Phase 2-3)

**Ranked by LOC:**
1. `quant/execution/exit_rules.py` — 616 LOC dead (only `classify_exit`, `get_session_time_stop` live)
2. `quant/contracts/constants.py` — ~30 unread constants
3. `SignalBuilder.size()` (`signal_builder.py:206`) — never called
4. `runtime.py` dead imports/constants
5. `events.py:86 DepthUpdated` — defined/projected, never emitted
6. `quant/strategy.py` — dead seam
7. `analyzer.py:965 compute_observation()` + `amt/models/observation.py` — RL leftovers
8. `amt/session/one_min_bar.py:36 OneMinBarEngine` — zero refs
9. `risk.py:301 pyramid_position_size`, `:316 rupee_risk_for_quantity` — test-only
10. `decision/context.py` dead fields — `state`, `consecutive_losses`, `agent_probability`, `balance_ratio`, `equity`, `risk_per_trade_pct`
11. AI VOs — `ModelWeights`, `FactorBreakdown`, `AIAnalysisResult`, `AICommandResponse`
12. Frontend dead: `ProfileOverlayInfo.tsx`, `llmHistory`, phantom fields in `types.ts`
13. Backend dead: `TradeJournal` has no production writer, `PaperBrokerAdapter.execute_order` never called, `IBroker.cancel_order` zero callers

---

### Phase 4: Layer Cycle Breaking (Medium Priority)

**Problem:** `contracts → execution → decision → contracts` import cycle. `contracts/entities.py` imports `execution.exit_rules`. `execution/order.py` imports `decision.signal_builder.Signal`.

**Strategy:** Each module owns its domain. Boundaries use Protocols/Callbacks, not direct imports.

- [ ] **Step 1:** Remove `contracts/entities.py` import of `execution.exit_rules` — move exit rule types to `execution/` or `contracts/ports/`
- [ ] **Step 2:** Remove `execution/order.py` import of `decision.signal_builder.Signal` — use a Protocol or import at function level
- [ ] **Step 3:** Break `decision→contracts→execution→decision` cycle by introducing `contracts/ports/` for cross-boundary types
- [ ] **Step 4:** Verify no circular imports: `python -c "import quant; print('ok')"` 

---

### Phase 5: Frontend Contract Alignment (Medium Priority)

#### Task 5.1: Freeze and generate WS contract

**Problem:** Untyped delta merge → silent corruption. `types.ts` hand-maintained with ~20-field drift from backend.

**Strategy:**
- Create `schema/ws_messages.json` as single source of truth
- Generate pydantic models (backend) + TS types (frontend) + runtime validator
- Parse-or-reject whole message

- [ ] **Step 1:** Define `ws_messages.json` with all message types and fields
- [ ] **Step 2:** Generate pydantic models from JSON schema
- [ ] **Step 3:** Generate TS types from JSON schema
- [ ] **Step 4:** Replace `view_state_to_ws()` manual mapping with generated schema validation
- [ ] **Step 5:** Remove `frontend/types.ts` hand-maintained fields
- [ ] **Step 6:** Test

#### Task 5.2: Remove frontend trading logic re-implementation

**Problem:** Frontend re-derives trading verdicts, breakout/retest detectors, 3-A gate scoring, PnL/R-multiple math, session phases (with NSE times hardcoded onto MCX symbols), and client-side mid-price LTP.

**Strategy:** The engine is the source of truth. Frontend renders; it does not decide.

- [ ] **Step 1:** Audit all frontend computation of trading logic
- [ ] **Step 2:** Remove client-side gate scoring, PnL math, session phase computation
- [ ] **Step 3:** Use engine-provided `quant_decision`, `risk_state`, `portfolio` from WS snapshot
- [ ] **Step 4:** Remove hardcoded NSE/MCX session times from frontend
- [ ] **Step 5:** Test

---

### Phase 6: Wiring Simplification (Low Priority)

#### Task 6.1: Replace DI container with plain factories

**Problem:** `container.py` 157L + `composition_root.py` 166L for a static graph. No runtime resolution needed.

**Strategy:** `wiring.build_app_context() → AppContext` plain factories, no scopes/runtime resolution.

- [ ] **Step 1:** Replace `DIContainer` with `AppContext` dataclass
- [ ] **Step 2:** `compose_container()` → `build_app_context(config) → AppContext`
- [ ] **Step 3:** Remove `container.py`
- [ ] **Step 4:** Update all `container.resolve()` calls to direct attribute access
- [ ] **Step 5:** Test

---

## Sequencing

```
Phase 0/1 (money safety) → Phase 2 (de-duplication) → Phase 3 (god classes) 
→ Phase 4 (layer cycles) → Phase 5 (frontend) → Phase 6 (wiring)
```

**Rationale:**
- Phase 1 closes real-money correctness violations immediately — these can lose money today
- Phase 2 reduces cognitive load before decomposition (fewer models to reason about)
- Phase 3 decomposition is safe only after duplicates are removed
- Phase 4 breaks cycles that become obvious after decomposition
- Phase 5/6 are lower-risk structural improvements

---

## Per-Task Safety Protocol

1. **Capture golden traces** before behavioral changes: record `(inputs_hash, symbol, bar_index) → action` from current `_decide()` and `ExitEngine.evaluate()`
2. **Write failing test** reproducing the defect
3. **Implement minimal fix** — behavior-preserving
4. **Replay traces** through refactored code — any diff blocks the commit
5. **Full test suite green** at ≤ pre-existing failures
6. **Commit** with descriptive message

---

## Open Decisions (need user input)

1. **LiveOMS:** Delete or wire properly for live trading? (Current: partially wired, quantity dropped)
2. **LLM advisor:** Keep as offline journal analysis or delete entirely? (Currently: live path has `wiring_advisor.py` with daemon thread)
3. **WS contract generation:** Adopt schema-first approach or keep manual mapping?
4. **Concurrency model:** Keep thread-per-symbol or switch to single asyncio loop? (Spike deferred)
