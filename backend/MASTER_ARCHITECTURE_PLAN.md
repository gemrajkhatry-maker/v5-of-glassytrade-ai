# GlassyTrade v6 — Master Architecture & Refactoring Plan

> **Authored by:** Senior Architect / Principal Engineer
> **Status:** Draft — pending team review
> **Date:** 2026-04-02
> **Scope:** SOLID, DDD, Event-Driven Architecture, Code Quality, QA Strategy

---

## Executive Summary

The GlassyTrade backend has a **correct high-level layered architecture** (DDD layers, ports & adapters, hexagonal-ish) but the **implementation has drifted** across five dimensions:

| # | Dimension | Problem | Impact |
|---|-----------|---------|--------|
| 1 | **God Classes** | `trading_session.py` (1326 lines), `engine.py` (940), `entry_gate.py` (1108) | Every trading rule change = shotgun surgery |
| 2 | **Dead Event Bus** | 13 domain events defined, 5 `.publish()` calls, **0 subscribers** | Event-driven facade masks procedural spaghetti |
| 3 | **Dual Position State** | `Portfolio.positions` + `TradeManager._positions` require manual reconciliation | Race conditions, unmanaged/stale positions |
| 4 | **Layer Inversions** | Domain → Settings, Application → API layer imports | Untestable core, impossible to substitute mocks |
| 5 | **No Single Source of Truth** | Config lives in Pydantic + YAML + `getattr()` defaults; Position state split; two event buses; two gate systems | "Which do I trust?" cognitive overload |

### Non-Goals of This Plan

- We are **NOT** rewriting from scratch
- We are **NOT** changing the live trading logic or Fabio AMT playbook rules
- We are **NOT** removing features (even dead-code — features get feature-flagged off, not deleted)

### Core Principles for This Migration

| Principle | What It Means Here |
|-----------|-------------------|
| **Strangler Fig** | Extract new clean code alongside old code; cut over one pathway at a time |
| **Parallel Run** | New and old codepaths produce the same output for N ticks before switching |
| **No Big Bang** | Every PR is < 300 lines, passes full test suite, is deployable independently |
| **Safety First** | The production trading engine continues running throughout the migration |

---

## Architecture Vision (Target State)

```
┌──────────────────────────────────────────────────────────────┐
│                        API Layer                              │
│  Routers (REST)  │  WS Viewers (read-only)  │  Admin Control  │
└────────────────────────┬─────────────────────────────────────┘
                         │
                  CommandBus (new)         EventBus (real)
                  for writes ───────►  for side-effects ▲
                         │                                  │
┌────────────────────────┴─────────────────────────────────────┤
│                    Application Layer                          │
│                                                               │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐  │
│  │ TickOrchestr│ │ EntryOrchestr│ │ ExitOrchestrator     │  │
│  │ ator        │ │ ator         │ │ (replaces ExitCoord) │  │
│  └──────┬──────┘ └──────┬───────┘ └──────────┬───────────┘  │
│         │               │                     │              │
│         ▼               ▼                     ▼              │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐  │
│  │ AMTOrchestr │ │ AgentPipeline│ │ PositionOrchestrator │  │
│  │ ator        │ │ Orchestrator │ │ (single position src)│  │
│  └─────────────┘ └──────────────┘ └──────────────────────┘  │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────┴─────────────────────────────────────┐
│                      Domain Layer                             │
│                                                               │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐  │
│  │ MarketState │ │ RiskManager  │ │ Trade Aggregate Root │  │
│  │ Engine      │ │              │ │ (single, real)       │  │
│  └──────┬──────┘ └──────┬───────┘ └──────────┬───────────┘  │
│         │               │                     │              │
│         ▼               ▼                     ▼              │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐  │
│  │ EntryGates  │ │ ExitGates    │ │ PositionSizeService  │  │
│  │ (pure fns)  │ │ (pure fns)   │ │                      │  │
│  └─────────────┘ └──────────────┘ └──────────────────────┘  │
│                                                               │
│  Ports: MarketData │ Broker │ Storage │ EventBus │ LLMPort   │
│           ┌────────┴────────┴────────┴──────────┴────────┐   │
└──────────┼────────────────────────────────────────────────┘   │
           │                                                     │
┌──────────┴────────────────────────────────────────────────────┤
│                    Infrastructure Layer                        │
│                                                               │
│  DhanAdapter │ PaperBroker │ SQLite │ MLX │ LGBM │ AsyncPersist│
└────────────────────────────────────────────────────────────────┘
```

### Key Structural Changes in Target State

1. **One Position Source of Truth** → The `Trade` aggregate root owns position state. `Portfolio` becomes a query/projection layer over the aggregate.
2. **Real Event Bus** → Subscribers exist for every published event. Side-effects are decoupled from the main pipeline.
3. **Command Bus** → Trading decisions flow through a structured command object, not direct method calls.
4. **No Layer Inversion** → Domain layer has zero imports from `app.config` or `app.api`.
5. **Orchestrators replace God Classes** → `trading_session.py` split into 6 focused orchestrators (< 200 lines each).

---

## Phased Migration Plan

Each phase has: **Goal**, **Work Items**, **QA Strategy**, **Rollback Criteria**, and **Exit Gate**.

---

### Phase 0: Foundation & Safety Net (Week 1–2)

**Goal:** Establish the safety net so every subsequent change is validated automatically.

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 0.1 | Fix 18 test collection errors | 2d | Eng + QA | 18 tests fail at import — unblocks the whole test suite |
| 0.2 | Run full test suite green baseline | 1d | Eng | Capture current passing % — this becomes the floor |
| 0.3 | Add architecture guardrails | 1d | Eng | Install `import-linter` to enforce layer boundaries (domain must not import config/api) |
| 0.4 | Create `shared/timezones.py` constant | 0.5d | Eng | Single `IST` timezone definition used across 5+ files |
| 0.5 | Create `shared/dto/depth_dto.py` | 0.5d | Eng | Extract duplicated `_depth_to_dto` from engine.py + gameloop.py |
| 0.6 | Add duplicate R:R lint check | 0.5d | QA | Simple grep-based CI check in pre-commit |
| 0.7 | Document current data flow | 2d | QA + Eng | Sequence diagram of tick → trade → exit — serves as ground truth for refactor |
| 0.8 | Set up CI pipeline | 2d | Eng | pytest, linting, import-linter on every PR |

#### QA Strategy — Phase 0

```
Task 0.1: For each of the 18 failing tests:
  ✓ Run test individually, capture error
  ✓ Classify: import error vs assertion failure vs fixture error
  ✓ Fix the root cause (likely missing mock or wrong import path)
  ✓ Add to a "flaky test quarantine" if it's intermittently failing
  ✓ Re-run full suite — verify count is now 1671 + 18 = 1689 collected

Task 0.2: Baseline capture
  ✓ Run: pytest -q --tb=no (capture pass/fail/skip/error counts)
  ✓ Store as JSON in tests/baseline_test_results.json
  ✓ All subsequent phases must maintain or exceed this pass rate

Task 0.3: Architecture guardrails (import-linter)
  ✓ Configure: domain cannot import app.config, app.api
  ✓ Configure: application cannot import app.api
  ✓ Run: lint-imports → must fail on existing violations (expected)
  ✓ Add exemptions for known violations with TODO references to phase IDs
  ✓ Each exemption gets a GitHub issue linked to it

Task 0.7: Ground truth sequence diagram
  ✓ Trace one complete tick from WS receipt → position open → exit
  ✓ Document every method call, every state mutation, every event
  ✓ Include thread boundaries (tick loop thread, LLM handler thread)
  ✓ Review with domain expert (Fabio Valenti playbook rules)
  QA Sign-off: Domain expert confirms diagram matches live behavior
```

#### Rollback Criteria

- Test suite pass rate drops below baseline
- `import-linter` catches a new violation we haven't exempted

#### Exit Gate — Phase 0 ✅

- [ ] 18 collection errors fixed, all tests importable
- [ ] Baseline test results captured and stored
- [ ] `import-linter` configured with exemptions documented
- [ ] `_depth_to_dto` duplication removed
- [ ] Sequence diagram reviewed and signed off by domain expert
- [ ] CI pipeline running on PR

---

### Phase 1: Kill the Dead Event Bus — Make It Real (Week 2–3)

**Goal:** Either make the event bus functional with real subscribers, or remove it entirely and acknowledge the system is synchronous. **Recommendation: Remove the facade and use direct calls intentionally.**

#### Decision: Remove Dead Event Bus

The `EventBus` has zero subscribers. The 5 `.publish()` calls write to an empty handler list. Maintaining it creates false expectations. We will:

1. **Remove** the `publish()` calls that nobody receives
2. **Replace** with explicit synchronous method calls (honest about what the system is)
3. **Keep** `EventBusPort` as an optional future extension point (not wired in)

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 1.1 | Remove 5 dead `event_bus.publish()` calls | 0.5d | Eng | Replace with direct method calls at the call site |
| 1.2 | Remove `event_bus` from `ServiceGraph` | 0.5d | Eng | It's only created, never consumed |
| 1.3 | Remove `EventBusPort` from handler constructors | 1d | Eng | `LLMEntryHandler`, `LLMOverseerHandler`, `EntryCoordinator` |
| 1.4 | Mark `DomainEvent` classes as `@dataclass(frozen=True)` (already done) | 0.25d | Eng | Verify immutability is enforced |
| 1.5 | Remove `SignalBus` (also unused — 0 consumers) | 0.5d | Eng | Delete file, remove imports |
| 1.6 | Document: "This system is synchronous method-call based" | 0.25d | Eng | Add to architecture.md so nobody adds an event bus again |

#### QA Strategy — Phase 1

```
For each removed event_bus.publish() call:
  ✓ Identify what the call was emitting (event type + data)
  ✓ Verify no downstream system depended on it (already confirmed: 0 subscribers)
  ✓ Remove the call
  ✓ Run: pytest on the modified module
  ✓ Run: integration tests end-to-end with live data simulation
  ✓ Diff state snapshots before/after — must be identical

Risk: If ANY subscriber existed elsewhere (plugins, monitoring), we'd break it.
Mitigation: Grep for .subscribe() across entire repo (already done — zero results).

Parallel run for 1.1–1.3:
  ✓ Run the system with event bus active for 1000 ticks
  ✓ Run the system with event bus removed for 1000 ticks
  ✓ Compare final state: must be byte-identical
```

#### Rollback Criteria

- Integration test state snapshots differ after removal
- Any import breaks in code we haven't yet modified

#### Exit Gate — Phase 1 ✅

- [ ] Zero `.publish()` calls to `event_bus` in the codebase
- [ ] Zero references to `SignalBus` in the codebase
- [ ] All tests pass with same rate as baseline
- [ ] Architecture docs updated to reflect synchronous design

---

### Phase 2: Fix Layer Inversions (Week 3–4)

**Goal:** Domain layer depends only on domain. Settings flow downward via DI. No imports from outer layers.

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 2.1 | Inject settings into OptionScanner via constructor | 0.5d | Eng | Remove `from app.config import settings` |
| 2.2 | Inject settings into VPContractSelector via constructor | 0.5d | Eng | Remove `from app.config import settings` |
| 2.3 | Inject settings into TradingSessionService via constructor | 1d | Eng | Replace 8 `getattr(settings, ...)` with explicit params |
| 2.4 | Remove `from app.api.dependencies import get_service_graph` from trading_session.py | 0.5d | Eng | Pass signal_tracker via constructor instead |
| 2.5 | Create `TradingSessionConfig` dataclass | 1d | Eng | Bundle all settings needed by TradingSessionService |
| 2.6 | Remove `sys.path.insert()` in dhan_adapter.py | 0.5d | Eng | Fix project structure so `brokers/` is importable normally |
| 2.7 | Replace `__import__()` hacks in SessionState with explicit imports | 0.5d | Eng | Fix circular dependency by restructuring imports |
| 2.8 | Add `import-linter` CI enforcement | 0.5d | Eng | Already done in Phase 0; now remove exemptions as we go |

#### QA Strategy — Phase 2

```
For each layer inversion fix:
  ✓ Identify all call sites that construct the modified class
  ✓ Update constructors to pass config/settings
  ✓ Verify: import-linter no longer flags this violation
  ✓ Run: unit tests for the modified module
  ✓ Run: integration tests end-to-end
  ✓ Check: no behavioral change in tick processing

Specific tests for 2.3 (TradingSessionConfig extraction):
  ✓ Create TradingSessionConfig with default values from current settings
  ✓ Pass config to TradingSessionService.__init__()
  ✓ Run 5000-tick simulation with old (getattr) and new (config param) approaches
  ✓ Compare final portfolio state: balance, equity, positions, stats
  ✓ Must match exactly

Specific tests for 2.7 (circular import fix):
  ✓ Import every module in dependency order
  ✓ Verify no ImportError at any step
  ✓ Run: python -c "import app.main" — must succeed
  ✓ Run: full test suite
```

#### Rollback Criteria

- Any import fails at server startup
- `import-linter` catches a new violation
- Constructor injection breaks existing call sites

#### Exit Gate — Phase 2 ✅

- [ ] Zero imports from `app.config` in domain layer
- [ ] Zero imports from `app.api` in application or domain layer
- [ ] All `getattr(settings, ...)` in TradingSessionService replaced with config
- [ ] `import-linter` passes on domain → app/config, app/application → app/api
- [ ] Full test suite passes

---

### Phase 3: Unify Position State (Week 4–5)

**Goal:** One source of truth for position state. Eliminate the reconciliation dance between Portfolio and TradeManager.

#### Design Decision

The **current reality** is that `Portfolio` tracks positions for P&L computation and `TradeManager` tracks positions for exit logic. The right solution depends on trade volume:

- **Option A (preferred for this system):** Make `Portfolio` the single source of truth. `TradeManager` becomes a pure exit-logic service that queries `Portfolio` but doesn't maintain its own position map.
- **Option B:** Keep both but implement a proper CQRS pattern — `Portfolio` as command side, `TradeManager` as query side with event sourcing.

We choose **Option A** because:
1. It's simpler (fits the synchronous architecture established in Phase 1)
2. The reconciliation code (`_record_position_consistency`) is a smell that proves the split is wrong
3. Option B would require implementing the event bus properly (Phase 1 says no)

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 3.1 | Move position tracking logic from TradeManager to Portfolio | 2d | Eng | TradeManager gets Portfolio reference instead of own map |
| 3.2 | Remove `TradeManager.register_position()` / `unregister_position()` | 1d | Eng | Portfolio.open_position() / close_position() becomes the API |
| 3.3 | Remove `_record_position_consistency()` from TradingSessionService | 0.5d | Eng | If there's one source of truth, reconciliation is impossible |
| 3.4 | Implement `Portfolio.get_managed_position(id)` for TradeManager queries | 0.5d | Eng | TradeManager needs read access, not own copy |
| 3.5 | Update all call sites that call register/unregister | 1d | Eng | EntryCoordinator, exit_coordinator, TradeLifecycleHandler |
| 3.6 | Remove `ensure_position_consistency()` reconciliation logic | 0.5d | Eng | Dead code — no second source to reconcile against |

#### QA Strategy — Phase 3

```
This is the highest-risk phase. Position state is money.

Pre-migration tests (run against current code):
  ✓ Run simulation: 1000 ticks → open 5 positions → manage exits → close all
  ✓ Capture: each position's entry_price, exit_price, pnl, close_reason
  ✓ Capture: state after each tick (portfolio + TradeManager position count)

Post-migration tests (new code):
  ✓ Run identical simulation
  ✓ Compare: every position's entry_price, exit_price, pnl, close_reason
  ✓ Compare: position count after each tick
  ✓ Must match exactly — any difference is a FAIL

Specific edge cases to test:
  ✓ Position opened and immediately hit SL on same tick
  ✓ Position opened, scale-in added, then partial exit
  ✓ Position opened, TradeManager trails SL, then exits
  ✓ Portfolio closes position via SL → TradeManager must not double-close
  ✓ Mid-trade recovery: restart engine, recover positions from DB
  ✓ Concurrent position opens on different symbols

Stress test:
  ✓ 50,000 ticks with 50 simulated positions
  ✓ Monitor memory: must not grow unboundedly
  ✓ Monitor: no position state divergence between Portfolio and TradeManager
```

#### Rollback Criteria

- Position count differs between old and new code in any simulation
- Mid-trade recovery fails
- Double-close occurs (position closed twice)

#### Exit Gate — Phase 3 ✅

- [ ] Zero calls to `TradeManager.register_position()` / `unregister_position()`
- [ ] `_record_position_consistency()` removed — reconciliation no longer needed
- [ ] 1000-tick simulation produces identical position states before/after
- [ ] Mid-trade recovery test passes
- [ ] Stress test: 50,000 ticks, 50 positions, no memory leak

---

### Phase 4: Extract God Class — trading_session.py (Week 5–8)

**Goal:** Split `TradingSessionService.process_tick()` (~900 lines) into focused orchestrators. Each orchestrator < 200 lines.

#### Target Decomposition

```
TradingSessionService (facade, ~150 lines)
├── TickOrchestrator (~180 lines)
│   ├── Calls SessionStateManager (session reset, day boundary)
│   ├── Calls SessionPhaseGate (force-exit on session end)
│   ├── Manages candle history (append, trim, persist closed candle)
│   └── Manages underlying futures data cache
│
├── AMTOrchestrator (~150 lines)
│   ├── Calls AMTHandler.analyze()
│   ├── Manages profile state (prior POC/VAH/VAL carryover)
│   ├── Updates Initial Balance engine
│   ├── Manages footprint generation
│   └── Pre-candle advisory trigger
│
├── AgentPipelineOrchestrator (~100 lines)
│   ├── Feature extraction
│   ├── Probability engine call
│   ├── Agent decision scoring
│   └── Decision caching (pending_decision)
│
├── PositionOrchestrator (~150 lines)
│   ├── Entry execution (gate pipeline → signal construction → broker)
│   ├── Exit checking (TradeLifecycleHandler.check_exits())
│   ├── Overseer trigger (LLM position management)
│   └── Post-close handling (learning, risk update, logging)
│
└── StateOrchestrator (~100 lines)
    ├── State snapshot building
    ├── Agent decision DTO
    ├── Risk state DTO
    └── Playbook guard status
```

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 4.1 | Extract SessionStateManager calls → TickOrchestrator | 2d | Eng | Session reset, phase gate, candle management |
| 4.2 | Extract AMT analysis → AMTOrchestrator | 2d | Eng | AMTHandler, IB engine, IB breakout, 1-min engine, pre-candle |
| 4.3 | Extract agent pipeline → AgentPipelineOrchestrator | 1.5d | Eng | Feature extraction, probability, decision |
| 4.4 | Extract position management → PositionOrchestrator | 3d | Eng | Entry, exits, overseer, post-close |
| 4.5 | Extract state snapshot → StateOrchestrator | 1d | Eng | Already partially in build_state_snapshot, complete the extract |
| 4.6 | Wire orchestrators into new TradingSessionService | 2d | Eng | Facade pattern: `process_tick()` calls orchestrators in order |
| 4.7 | Delete old monolithic methods | 1d | Eng | After all orchestrators pass tests, remove old code |

#### QA Strategy — Phase 4

```
This is the most complex phase. We use the "Extract Method → Verify Pattern":

For each extracted orchestrator (4.1–4.5):
  1. EXTRACT: Move code into new class, keep original method intact
  2. DUAL RUN: In process_tick():
     - Old codepath: runs process_tick() as-is, stores result A
     - New codepath: runs new orchestrator, stores result B
     - Assert: A == B (deep comparison)
     - Return A (live system uses old code until we're confident)
  3. ITERATE: Fix B until it matches A
  4. SWITCH: When B matches A for 5000 ticks:
     - Return B from process_tick()
     - Keep A running in background for 1 more day with assertion
  5. DELETE: Remove old codepath

Specific orchestrator tests:

  4.1 TickOrchestrator:
    ✓ Test: session day boundary resets correct state
    ✓ Test: candle append/trim at MAX_CANDLES_PER_SYMBOL boundary
    ✓ Test: underlying futures cache updates correctly
    ✓ Test: force-exit on session phase 5 triggers

  4.2 AMTOrchestrator:
    ✓ Test: AMT result for 500 historical candles matches current
    ✓ Test: IB engine state transitions (building → complete → triggered)
    ✓ Test: Profile carryover (prior POC → prior_poc parameter)
    ✓ Test: Pre-candle fires at T-60s, not before

  4.3 AgentPipelineOrchestrator:
    ✓ Test: Feature extraction produces identical output for same input
    ✓ Test: Agent decision matches current _agent_decision for 5000 ticks
    ✓ Test: Pending decision caching works (decision saved, executed on new candle)

  4.4 PositionOrchestrator:
    ✓ Test: Entry gate pipeline passes → position opened
    ✓ Test: Entry gate pipeline fails → no position
    ✓ Test: Exit conditions trigger correctly (SL, TP, trail, time, CVD kill)
    ✓ Test: Overseer fires on schedule for open positions
    ✓ Test: Post-close updates learning, risk, persist DB

  4.5 StateOrchestrator:
    ✓ Test: State snapshot DTO is byte-identical to current
    ✓ Test: Agent decision DTO formatting
    ✓ Test: Playbook guard state computation
```

#### Rollback Criteria

- Dual-run A vs B produces different state for 3+ consecutive ticks
- Any orchestrator raises an unhandled exception
- Entry or exit behavior changes (position opened/closed differently)

#### Exit Gate — Phase 4 ✅

- [ ] All 5 orchestrators created, each < 200 lines
- [ ] Dual-run A vs B matches for 10,000 ticks
- [ ] Old monolithic process_tick() code removed
- [ ] `TradingSessionService.process_tick()` is ~30 lines (facade delegating to orchestrators)
- [ ] Full test suite passes
- [ ] Live trading journal (JSONL) shows no regression

---

### Phase 5: Fix entry_gate.py — Split Into Domain Modules (Week 8–9)

**Goal:** Extract 1,108-line entry_gate.py into focused pure-function modules.

#### Target Decomposition

```
entry_gate/
├── __init__.py
├── three_align.py       # Three-Align Gate (Market State + Location + Confirmation)
├── confirmation_bundle.py  # Volume impulse + Delta + Spread checks
├── momentum_fade.py     # Freight train/blocking logic
├── signal_builder.py    # build_entry_signal (SL/TP calculation)
├── grading.py           # compute_grade_score, A/B/C setup classification
├── vwap_analyzer.py     # VWAP bias, VWAP bands
├── imbalance_analyzer.py # Stacked imbalance alignment
└── gate_runner.py       # run_gate_pipeline (12-gate sequential)
```

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 5.1 | Extract `three_align_check` → `three_align.py` | 1d | Eng | Pure functions, already isolated |
| 5.2 | Extract `check_confirmation_bundle` → `confirmation_bundle.py` | 0.5d | Eng | Pure functions |
| 5.3 | Extract `check_momentum_fade` → `momentum_fade.py` | 0.5d | Eng | Pure functions |
| 5.4 | Extract `build_entry_signal` → `signal_builder.py` | 1.5d | Eng | Contains SL/TP math — highest risk |
| 5.5 | Extract `compute_grade_score` → `grading.py` | 1d | Eng | Includes VWAP bias + imbalance helpers |
| 5.6 | Extract `run_gate_pipeline` → `gate_runner.py` | 0.5d | Eng | Already has GatePipeline class |
| 5.7 | Remove original entry_gate.py | 0.5d | Eng | After all extracts verified |
| 5.8 | Remove duplicate R:R calculation in signal_builder.py | 0.25d | Eng | Lines 690-691 |

#### QA Strategy — Phase 5

```
Each extracted module is pure functions — trivially testable.

For each module:
  ✓ Test with synthetic market data (known inputs → known outputs)
  ✓ Test edge cases:
    - Three-Align: insufficient data, zero POC, extreme CVD
    - Confirmation: zero volume, NaN prices, empty order book
    - Signal Builder: negative SL/TP, zero risk, ATR = 0
    - Grading: footprint_candle = None, missing VWAP bands
  ✓ Parallel run: run old and new code on 10,000 historical candles
  ✓ Compare every gate decision, every signal, every grade

Specific SL/TP tests (5.4 — highest risk):
  ✓ LONG Mean Reversion: SL below VAL, TP at POC
  ✓ SHORT Mean Reversion: SL above VAH, TP at POC
  ✓ LONG Trend: SL below POC, TP = VAH + (VAH - POC)
  ✓ SHORT Trend: SL above POC, TP = VAL - (POC - VAL)
  ✓ inside_cluster=True vs inside_cluster=False
  ✓ inside_extreme=True vs inside_extreme=False
  ✓ ATR floor override prevents SL < min_sl_dist
  ✓ session_risk_pct override when tighter than quant SL
  ✓ Tick-size rounding (round_up_to_tick, round_down_to_tick)
  ✓ Test with 2000 historical signals — SL/TP must match exactly
```

#### Rollback Criteria

- Any signal generated with different SL/TP values
- Gate pipeline produces different pass/fail decision for same input

#### Exit Gate — Phase 5 ✅

- [ ] entry_gate.py deleted, split into 8 modules
- [ ] Each module < 150 lines
- [ ] 2000 historical signal test: zero differences in SL/TP
- [ ] Gate pipeline produces identical decisions on 10,000 candles
- [ ] Duplicate R:R line removed

---

### Phase 6: Clean Up Domain Layer (Week 9–10)

**Goal:** Fix dead code, unclear bounded contexts, and value object boundaries.

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 6.1 | Remove `TradeAggregate` or mark as deprecated | 0.5d | Eng | 795 lines of dead event-sourced code |
| 6.2 | Remove `SignalBus` | 0.25d | Eng | Already done in Phase 1.5 — confirm removal |
| 6.3 | Audit `fabio_ai/services/` — move utilities out of domain | 1d | Eng | prompt_builder, spread_normalizer → shared/ |
| 6.4 | Fix Portfolio.process_tick() Source.LLM hardcoded branch | 1d | Eng | Make SL/TP management pluggable per Source |
| 6.5 | Extract MarketDataPort interface into smaller interfaces | 1d | Eng | MarketDataQueryPort + MarketDataStreamPort |
| 6.6 | Fix PaperBroker mutating Signal | 0.5d | Eng | Return modified Signal instead of mutating input |
| 6.7 | Remove `__import__()` hacks in SessionState | 0.5d | Eng | Replace with proper imports |

#### QA Strategy — Phase 6

```
6.1 TradeAggregate removal:
  ✓ Confirm: no import of TradeAggregate exists anywhere in codebase
  ✓ Confirm: test_trade_aggregate.py tests only the dead module (can be archived)

6.3 fabio_ai/services boundary audit:
  ✓ For each of the 50+ services:
    - Does it contain business rules? → stays in domain
    - Is it a utility/helper? → moves to shared/ or application/
    - Does it depend on Settings? → must accept config as parameter
  ✓ Verify: no shared/ imports domain/ (dependency direction)

6.4 Portfolio Source.LLM branch:
  ✓ Create a PositionManager registry that maps Source → management strategy
  ✓ LLM → TradeManager manages exits
  ✓ AGENT → TradeManager manages exits
  ✓ AMT → Portfolio manages exits (SL/TP in Portfolio.process_tick)
  ✓ Test: each strategy produces correct exit behavior
  ✓ Test: adding a new source doesn't require editing process_tick()

6.6 PaperBroker Signal mutation:
  ✓ Test: input Signal is unchanged after execute_order()
  ✓ Test: returned position has the slippage-adjusted price
  ✓ Test: behavior is identical before/after (only the mutation approach changed)
```

#### Exit Gate — Phase 6 ✅

- [ ] TradeAggregate dead code archived/removed
- [ ] fabio_ai/services/ contains only domain services (no utilities)
- [ ] Portfolio.process_tick() no longer has hardcoded Source.LLM branch
- [ ] MarketDataPort split into QueryPort + StreamPort
- [ ] PaperBroker no longer mutates input Signal
- [ ] All tests pass

---

### Phase 7: Engine Cleanup (Week 10–11)

**Goal:** Reduce `engine.py` from 940 lines by extracting concerns.

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 7.1 | Extract depth DTO to shared (done in Phase 0.5) | 0d | Eng | Already done |
| 7.2 | Extract `_seed_history()` → HistorySeeder service | 1d | Eng | Pure concern: loading historical data |
| 7.3 | Extract `_seed_mtf_history()` → MTFHistorySeeder service | 0.5d | Eng | Same pattern |
| 7.4 | Extract `_recover_open_positions()` → PositionRecovery service | 1d | Eng | Already partially in startup_reconciliation.py |
| 7.5 | Extract `_load_candles_from_db()` → CandleRepository | 0.5d | Eng | Data access concern |
| 7.6 | Extract `_backfill_range_bars()` → RangeBarBackfiller | 0.5d | Eng | Visualization concern |
| 7.7 | Simplify `_tick_loop()` by removing duplicated logic | 2d | Eng | After sub-extractions, the loop should be much cleaner |

#### QA Strategy — Phase 7

```
Each extraction follows the same pattern as Phase 4:
  ✓ Extract to new class/method
  ✓ Dual-run: old codepath produces A, new codepath produces B
  ✓ Assert A == B
  ✓ Keep old, run for N minutes in production
  ✓ Delete old when confident

Specific engine tests:
  7.2 History Seeder:
    ✓ Given: mock market_data returning 100 candles
    ✓ When: _seed_history() runs
    ✓ Then: session.data has 100 candles, initial AMT analysis done

  7.4 Position Recovery:
    ✓ Given: DB has 3 open positions
    ✓ When: _recover_open_positions() runs
    ✓ Then: 3 positions restored to session portfolio
    ✓ And: active_symbols updated
    ✓ And: positions registered with TradeManager

  7.7 Tick loop simplification:
    ✓ Run: 10,000 live ticks through old and new engine
    ✓ Compare: state snapshots for both
    ✓ Must match exactly
```

#### Exit Gate — Phase 7 ✅

- [ ] TradingEngine < 400 lines (down from 940)
- [ ] All sub-extractions pass dual-run tests
- [ ] Engine starts, seeds history, streams ticks — no regression

---

### Phase 8: Final Cleanup & Polish (Week 11–12)

**Goal:** Remove remaining code smells, finalize documentation, hand off to QA.

#### Work Items

| ID | Task | Effort | Owner | Notes |
|----|------|--------|-------|-------|
| 8.1 | Remove all `except Exception: log.debug("Silent exception handled")` patterns | 1d | Eng | Replace with proper error handling or specific exceptions |
| 8.2 | Centralize magic numbers into constants/dataclass configs | 1d | Eng | Create `app/domain/config/` for all trading constants |
| 8.3 | Remove SessionState's 25+ mutable fields — split into bounded contexts | 2d | Eng | TradingState, AnalysisState, DecisionState, QAState |
| 8.4 | Fix inconsistent IST timezone usage — unify to shared.timezone | 0.5d | Eng | Phase 0.4 already created the constant |
| 8.5 | Final architecture docs update | 1d | QA + Eng | Update all docs to match new structure |
| 8.6 | Remove ALL import-linter exemptions | 0.5d | Eng | Zero exemptions remaining |
| 8.7 | Performance regression test | 1d | QA | Compare throughput: old vs new |

#### QA Strategy — Phase 8

```
8.1 Silent exception cleanup:
  ✓ For each of the 12 silent exception handlers:
    - What error is being swallowed?
    - Is it truly non-critical? (UI decoration, logging)
    - Or is it a trading error that should propagate?
  ✓ Non-critical: keep except: but use specific exception type
  ✓ Critical: let it propagate to the orchestrator level
  ✓ Test: each modified path with error injection

8.2 Magic numbers:
  ✓ Grep for: 0.55, 0.5, 0.15, 600, 0.5 (throttle), 60 (cooldown)
  ✓ For each: define as constant, use constant name
  ✓ Test: no behavioral change

8.3 SessionState split:
  ✓ TradingState: data, portfolio, underlying_data
  ✓ AnalysisState: last_amt, last_footprint, last_prediction
  ✓ DecisionState: last_ai_analysis, _agent_decision, _pending_decision
  ✓ QAState: playbook guards, explainability tracking
  ✓ Test: cross-session access works correctly
  ✓ Test: thread safety maintained (each state has its own lock)

8.7 Performance regression:
  ✓ Old system: measure tick processing latency (p50, p95, p99)
  ✓ New system: same measurement
  ✓ Must be within 5% of old system
  ✓ Memory: must not increase per-tick
```

#### Exit Gate — Phase 8 ✅

- [ ] Zero silent exception handlers with bare `except Exception`
- [ ] Zero magic numbers in trading logic (all named constants)
- [ ] SessionState split into 4 focused dataclasses
- [ ] Zero import-linter exemptions
- [ ] Performance: within 5% of baseline
- [ ] Architecture documentation complete and accurate

---

## QA Master Strategy

### Testing Pyramid (Target State)

```
                    ┌─────────────┐
                    │  E2E / Live │  ← 5 integration tests with simulated broker
                    ├─────────────┤
                   /  Integration  \  ← 20 pipeline tests (tick → decision → position)
                  /─────────────────\
                 /      Unit          \  ← 200+ unit tests (pure functions, services)
                /──────────────────────\
               /    Architecture        \  ← Import-linter, dependency graph checks
              /──────────────────────────\
```

### Testing Execution Order

Each phase must complete in this order:

```
1. UNIT TESTS for the changed module first
   ✓ pytest -x path/to/changed_module/
   ✓ Must pass before any other test runs

2. ARCHITECTURE TESTS
   ✓ lint-imports
   ✓ Circular dependency check
   ✓ Layer boundary check (no domain → config imports)

3. COMPARISON TESTS (dual-run)
   ✓ Run old vs new codepath on ≥ 5000 ticks
   ✓ State diff must be empty

4. INTEGRATION TESTS
   ✓ Full pipeline: tick → process → exit
   ✓ WS viewer: connect, receive state, delta updates

5. REGRESSION SUITE
   ✓ Full test suite: pytest -x backend/tests/
   ✓ Must equal or exceed baseline pass rate

6. SMOKE TEST
   ✓ Start the backend server
   ✓ Connect frontend
   ✓ Stream live data for 5 minutes
   ✓ No errors in backend.log
```

### QA Artifacts to Create

| Artifact | Purpose | Created In |
|----------|---------|------------|
| `tests/baseline_test_results.json` | Pass/fail baseline | Phase 0 |
| `tests/validation/comparison_engine.py` | Dual-run comparison framework | Phase 0 |
| `tests/validation/synthetic_market_data.py` | Already exists — extend it | Phase 0 |
| `tests/validation/performance_baseline.json` | Latency/memory baseline | Phase 2 |
| `tests/architecture/import_linter.py` | Layer boundary enforcement | Phase 0 |
| `tests/architecture/dependency_graph.json` | Module dependency map | Phase 0 |
| `qa/review_checklist.md` | Per-Phase PR review checklist | Phase 1 |
| `qa/dual_run_protocol.md` | How to run parallel comparison tests | Phase 3 |
| `qa/live_smoke_test.md` | Live trading verification steps | Phase 5 |

---

## Risk Assessment & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Position state divergence during Phase 3 | Medium | **Critical** (money lost) | Dual-run for 50,000 ticks before switching; emergency rollback to Phase 2 |
| Live trading disruption | Medium | **Critical** | Every phase is deployable independently; no phase requires server restart during trading hours |
| Performance regression | Low | High | Perf benchmark in Phase 0; regression check in every phase |
| Team context loss during 12-week migration | High | Medium | Each phase is documented; code is reviewable; no phase depends on tribal knowledge |
| Config/config.yaml mismatch | Low | Medium | Consolidated config (Phase 2) — single source of truth |
| Breaking change in external broker API | Low | High | Broker adapter layer isolates this — we only touch adapters not the port |

---

## Team Roles

| Role | Responsibilities |
|------|-----------------|
| **Principal Engineer** | Architecture decisions, code review, unblocking technical issues |
| **Senior Backend Dev (2)** | Implementation of phases 2–7 |
| **QA Lead** | Test design, dual-run protocols, regression gate |
| **QA Engineer** | Test execution, smoke testing, performance benchmarks |
| **Domain Expert** | Validates trading logic hasn't changed (Fabio AMT rules) |
| **DevOps** | CI/CD pipeline deployment, rollback infrastructure |

---

## Timeline (12 Weeks)

```
Week  1-2  ████████░░░░░░░░░░░░  Phase 0: Foundation & Safety
Week  2-3  ░░░░████████░░░░░░░░  Phase 1: Kill Dead Event Bus
Week  3-4  ░░░░░░░░████████░░░░  Phase 2: Fix Layer Inversions
Week  4-5  ░░░░░░░░░░░░████████  Phase 3: Unify Position State
Week  5-8  ███░░░░░░░░░░░░░░░░░  Phase 4: Extract God Class (longest)
Week  8-9  ░░░░░███░░░░░░░░░░░░  Phase 5: Split entry_gate.py
Week  9-10 ░░░░░░░░░███░░░░░░░░  Phase 6: Domain Layer Cleanup
Week 10-11 ░░░░░░░░░░░░░███░░░░  Phase 7: Engine Cleanup
Week 11-12 ░░░░░░░░░░░░░░░░████  Phase 8: Final Cleanup & Polish
```

---

## Success Criteria (End of Phase 8)

| Metric | Before | Target | Measure |
|--------|--------|--------|---------|
| `trading_session.py` lines | 1,326 | < 300 | `wc -l` |
| `entry_gate.py` lines | 1,108 | N/A (deleted) | `ls` |
| `engine.py` lines | 940 | < 400 | `wc -l` |
| Largest file in domain/ | ~800 lines | < 200 | `wc -l` max |
| Layer inversion count | 6 | 0 | `import-linter` |
| Event bus subscribers | 0 (dead) | N/A (removed) | Grep |
| Position state sources | 2 (reconciled) | 1 | Code review |
| Silent exception handlers | 12 | 0 | Grep + review |
| Magic numbers in trading | 20+ | 0 | Grep for numeric literals |
| Test coverage | Unknown | ≥ baseline | pytest |
| Architecture guardrail violations | Unlimited | 0 | import-linter |
| God classes (>500 lines) | 4 | 0 | `wc -l` |
