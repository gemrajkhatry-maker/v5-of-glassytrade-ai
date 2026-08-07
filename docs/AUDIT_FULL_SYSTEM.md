# AMT Scalper — Full System Audit

> **Date:** 2026-08-06
> **Branch:** `stable_4`
> **Scope:** Backend → Quant Engine → WebSocket → Frontend
> **Status:** 🔴 Critical — two parallel engines, 60+ dead shims, greenfield decisions never execute

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Architecture: Spec vs Reality](#2-architecture-spec-vs-reality)
- [3. Backend Audit](#3-backend-audit)
  - [3.1 Entry Point — main.py](#31-entry-point--mainpy)
  - [3.2 Engine — engine.py](#32-engine--enginepy)
  - [3.3 Session Service — trading_session.py](#33-session-service--trading_sessionpy)
  - [3.4 AMT Service — amt_service.py](#34-amt-service--amt_servicepy)
  - [3.5 Quant Bridge — quant_bridge.py](#35-quant-bridge--quant_bridgepy)
  - [3.6 Quant Runtime — runtime.py](#36-quant-runtime--runtimepy)
  - [3.7 DI / Composition Root](#37-di--composition-root)
  - [3.8 Shim Layer — 60+ Re-export Modules](#38-shim-layer--60-re-export-modules)
- [4. Quant Engine Audit](#4-quant-engine-audit)
  - [4.1 Auction Coordinator](#41-auction-coordinator)
  - [4.2 Decision Pipeline](#42-decision-pipeline)
  - [4.3 Gaps in Quant](#43-gaps-in-quant)
- [5. Frontend Audit](#5-frontend-audit)
  - [5.1 WebSocket Hook — useServerTradingSystem.ts](#51-websocket-hook--useservertradingsystemts)
  - [5.2 Types — types.ts](#52-types--typests)
  - [5.3 Data Overload](#53-data-overload)
- [6. Data Flow — Tick to Screen](#6-data-flow--tick-to-screen)
- [7. Training Data Gap](#7-training-data-gap)
- [8. Root Causes Ranked by Impact](#8-root-causes-ranked-by-impact)
- [9. Remediation Plan](#9-remediation-plan)
  - [Phase 1 — Delete Shims](#phase-1--delete-shims)
  - [Phase 2 — Wire Greenfield to Execution](#phase-2--wire-greenfield-to-execution)
  - [Phase 3 — Kill Legacy AMT Path](#phase-3--kill-legacy-amt-path)
  - [Phase 4 — Migrate to QuantEngine](#phase-4--migrate-to-qu antengine)
  - [Phase 5 — Fix Training Data](#phase-5--fix-training-data)
- [A. Inventory](#a-inventory)
- [B. Findings Index](#b-findings-index)

---

## 1. Executive Summary

The AMT scalper has **two parallel analysis engines** running on the same tick data. The legacy path (`AMTService` → `AMTHandler` → 800-line `GatePipeline`) executes trades. The greenfield path (`QuantBridge` → `AuctionCoordinator` → `DecisionService`) produces clean, immutable `AuctionState` snapshots but **its decisions are never wired to execution**. Both run on every tick, doubling latency and cognitive load.

Between them sits a **shim layer of 60+ re-export modules** from a half-finished migration. Every traceback shows the wrong file. Every IDE jump lands on a one-liner proxy. Tests exercise shim paths, not canonical paths.

The result: a 135K-line codebase where the correct architecture (149 lines, pure functions, deterministic) exists but doesn't run, and the running architecture (657-line god method, 17 collaborators, two analysis engines) can't be safely refactored because the shims obscure the real dependency graph.

**The fix is deletion, not addition.** Delete shims. Wire greenfield to execution. Delete legacy. Migrate to the clean engine.

---

## 2. Architecture: Spec vs Reality

### What the Architecture Doc Says (`docs/AMT_ARCHITECTURE_PROPOSAL.md`)

```
ticks → aggregator → VP/VWAP/orderflow → AuctionState → 5 gates → signal → OMS → exit
```

**6 files, ~2,000 lines.** Four laws:
1. Analysis is pure per closed bar — no hidden cross-bar mutation
2. One tick consumer — no locks in the hot path
3. Decisions on bar close — not tick-by-tick
4. LLM never gates a trade — advisory overlay only

### What Actually Runs

```
Dhan WS → TradingEngine (523 lines)
              ↓
      CandleAggregator + TickProcessor + FuturesAggregator
              ↓
      TradingSessionService.process_tick() (657 lines, 17 collaborators)
              ↓
      ┌─────────────────────────────────────────────────────────┐
      │  PATH A: Legacy AMT (executes trades)                   │
      │    AMTService → AMTHandler.analyze()                    │
      │    → Volume Profile + CVD + Aggression + 20+ detectors  │
      │    → AMTResult (30+ fields)                             │
      │    → Micro-agent pipeline (probability engine)          │
      │    → SessionEventRouter → GatePipeline (800 lines)      │
      │    → IB Scalp Engine + 1Min Bar Engine                  │
      │    → LLM Entry Handler + Overseer                       │
      │    → Trade Lifecycle Handler → Broker                   │
      └─────────────────────────────────────────────────────────┘
              ↓
      ┌─────────────────────────────────────────────────────────┐
      │  PATH B: Greenfield Quant (NOT EXECUTED)                │
      │    QuantBridge → AuctionCoordinator                     │
      │    → 6 pure detectors → AuctionState (immutable)        │
      │    → DecisionService → GatePipeline (200 lines)         │
      │    → SignalBuilder / VA Fade fallback                   │
      │    → session.last_quant_decision (stored, not acted on) │
      └─────────────────────────────────────────────────────────┘
              ↓
      QuantEngine (149 lines — standalone, not used in live path)
              ↓
      StateBroadcaster → WebSocket → Frontend (12 data sections)
```

### The Gap

| Spec | Reality |
|------|---------|
| One analysis path | Two parallel paths (legacy + greenfield) |
| Pure per-bar analysis | `asyncio.to_thread` on every tick, blocking |
| One tick consumer | Thread pool executor per tick |
| Decisions on bar close | Decisions every 500ms (throttled) + bar close |
| LLM advisory only | LLM in entry path + monitoring + overseer (3 roles) |
| 6 files, ~2K lines | 135K lines across backend + quant + frontend |
| Greenfield executes | Greenfield computes but never executes |

---

## 3. Backend Audit

### 3.1 Entry Point — `backend/app/main.py` (337 lines)

**Responsibility:** FastAPI app setup, lifespan, lifespan option scan, DI wiring, route registration.

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B-01 | **P0** | **Startup blocks for 2+ minutes** — option chain scan runs synchronously during lifespan. All HTTP (including `/health`) is blocked. Frontend 180s timeout is the symptom, not the limit. | `main.py:143-229` |
| B-02 | **P0** | **Three DI paths coexist** — `composition_root.py` builds container, `api/dependencies.py` has `init_singletons()` (global mutable singletons), `TradingEngine.__init__` takes container services. Same object wired 3 ways. | `main.py:302-312` |
| B-03 | **P1** | **Startup telemetry is 400 lines** — `startup_telemetry.py` tracks phases, reconciliation, contracts. Nobody reads the data. Observability theater. | `core/startup_telemetry.py` |
| B-04 | **P1** | **Health router registered twice** — `/` and `/api`. Duplicate routes, confusing OpenAPI spec. | `main.py:315-316` |
| B-05 | **P2** | **`load_dotenv` at module level** before imports — different import orders give different env loading behavior. | `main.py:17-18` |

**Failure Scenario (B-01):** Backend starts during market hours. Option chain scan takes 90s. Frontend reconnects, hits `/api/health`, gets 504. User thinks system is down. Trading is running but invisible.

---

### 3.2 Engine — `backend/app/application/engine.py` (523 lines)

**Responsibility:** Tick loop. Consumes Dhan WS packets, aggregates candles, routes to session service, broadcasts state.

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B-06 | **P0** | **`asyncio.to_thread` on every tick** — `process_tick()` runs in thread pool per tick. Thread pool contention under load. Should be: ticks → queue → worker consumes. | `engine.py:470-477` |
| B-07 | **P0** | **500ms throttle produces inconsistent state** — throttled ticks get `_update_throttled_state` (cached analysis). Non-throttled get full `process_tick`. Frontend sees two quality levels with no flag to distinguish. | `engine.py:456-464` |
| B-08 | **P1** | **Dual aggregators** — `_candle_aggregator` (options) and `_futures_aggregator` (underlying). Same class, same logic. Futures feeds IB engine; options feeds AMT. Split creates divergence bugs. | `engine.py:160-165` |
| B-09 | **P1** | **Circuit breaker silently drops ticks** — when open, ticks are skipped with no alert. A buggy AMT analysis could mute an entire symbol's feed. | `engine.py:381-382, 409-410` |
| B-10 | **P2** | **500ms throttle floor is hardcoded** — not configurable, different from `STREAM_INTERVAL`. | `engine.py:458` |

**Failure Scenario (B-06):** Market spikes, 50 ticks/sec for 3 symbols = 150 ticks/sec. Each spawns a thread pool call. Python thread pool default is `min(32, os.cpu_count() + 4)`. Queue backs up. Ticks process out of order. AMT state jumps backward.

---

### 3.3 Session Service — `backend/app/application/services/trading_session.py` (1,067 lines)

**Responsibility:** The central pipeline — phase checks, AMT analysis, IB engines, position management, gate pipeline, LLM, exits.

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B-11 | **P0** | **657-line `process_tick()` method** — does phase check, AMT analysis, IB engine update, IB scalp evaluation, 1-min bar engine, pre-candle advisory, position management, exit checks, micro-agents, gate pipeline, LLM entry, overseer, cooldown, latency tracking. **8 responsibilities, 17 collaborators.** | `trading_session.py:325-991` |
| B-12 | **P0** | **Greenfield quant decisions never execute** — `QuantBridge` feeds `auction` DTO and `last_quant_decision` to the session. `SessionEventRouter.route_entry_signal()` only uses the legacy AMT path's signals. Greenfield = read-only dashboard widget. | `trading_session.py:831-870` |
| B-13 | **P0** | **AMT failure doesn't abort tick** — when `run_analysis()` returns None, a sentinel `AMTResult` with zeros is created. Pipeline continues: exits, overseer, position management all run against garbage data. | `trading_session.py:739-747` |
| B-14 | **P1** | **`hasattr` instead of proper init** — `if not hasattr(self, "_ib_engines")` masks initialization order dependency. | `trading_session.py:719-720` |
| B-15 | **P1** | **Signal stale threshold = 10 minutes** — `AGENT_DECISION_THRESHOLD = 0.65`. A signal older than 10 min is stale. In fast markets, 10 min = 50+ points of movement. | `trading_session.py:465-476` |
| B-16 | **P1** | **Stage latency tracking is dead code** — keys are `symbol:stage` strings. Never aggregated, never exposed to any endpoint. | `trading_session.py:1036-1054` |
| B-17 | **P2** | **Cooldown rationale string manipulation** — `base_rationale.split("[Cooldown")[0]` to strip previous cooldown tag. Fragile string parsing. | `trading_session.py:955` |

**Failure Scenario (B-13):** AMT analysis throws (e.g., empty candle buffer). `run_analysis()` catches and returns None. Sentinel `AMTResult(market_state="BALANCED", poc=0.0, ...)` is created. Exit engine checks: POC = 0.0, which is below current price → triggers false stop-loss. Position closes at loss. Journal records clean exit. User never knows AMT failed.

---

### 3.4 AMT Service — `backend/app/application/services/amt_service.py` (165 lines)

**Responsibility:** Runs volume profile + order flow analysis, feeds greenfield quant bridge.

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B-18 | **P0** | **QuantBridge coupled inside AMT path** — `bridge.on_bar_close()` called from `amt_service.py`. Greenfield engine depends on legacy AMT path running first. Should be independent. | `amt_service.py:103-111` |
| B-19 | **P1** | **Underlying state sync with 60s TTL** — shares market state across options on same underlying. If one option's AMT fails, it gets stale state from sibling. | `amt_service.py:132-153` |
| B-20 | **P1** | **`_UNDERLYING_MIN_CANDLES = 5`** — lowered from 20. Comment: "CVD on option data produces sign-flipping noise." Bandaid — real fix is futures delta, not option premium delta. | `amt_service.py:22-23` |

---

### 3.5 Quant Bridge — `backend/app/application/services/quant_bridge.py` (242 lines)

**Responsibility:** Maps backend OHLC → quant Bar, feeds AuctionCoordinator, serializes to DTO.

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B-21 | **P0** | **Module-level singleton** — `bridge = QuantBridge()` at module level. Global mutable state. Tests share state across modules. | `quant_bridge.py:242` |
| B-22 | **P0** | **`QUANT_DECISION_ENABLED` defaults to disabled** — when False, `on_bar_close_with_decision` stores nothing on the session. Greenfield decision exists but is not wired to execution. **This is the single biggest gap between architecture doc and reality.** | `quant_bridge.py:186-188` |
| B-23 | **P1** | **`_build_decision_context` reverse-engineers state** — `agent_direction` and `position_open` inferred from session internals with try/except. Should receive explicit context. | `quant_bridge.py:206-239` |
| B-24 | **P1** | **Hardcoded defaults** — `equity=100000.0`, `risk_per_trade_pct=0.01`, `tick_size=0.05`. Should come from config. | `quant_bridge.py:234-238` |

---

### 3.6 Quant Runtime — `backend/quant/runtime.py` (149 lines)

**Responsibility:** Standalone deterministic engine — gateway → aggregator → coordinator → decision → OMS → exits.

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B-25 | **P0** | **Not used in production** — `QuantEngine` has correct architecture. Live path uses `TradingEngine` → `TradingSessionService`. Two engines = two bug surfaces. Backtest ≠ production. | `runtime.py` |
| B-26 | **P1** | **Hardcoded agent values** — `agent_direction="LONG"`, `agent_probability=0.7`. No connection to micro-agent pipeline. | `runtime.py:114-115` |
| B-27 | **P1** | **Single symbol only** — one coordinator, one aggregator. Backend handles multiple symbols. Would need symbol multiplexer for production. | `runtime.py:41` |

---

### 3.7 DI / Composition Root — `backend/app/application/di/composition_root.py` (416 lines)

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B-28 | **P1** | **Two GatePipelines, different implementations** — composition root builds legacy `GatePipeline` (800 lines, LLM + probability + storage deps). `quant.decision.pipeline.GatePipeline` is ~200 lines of pure functions. Same name, different class. | `composition_root.py:393-406` |
| B-29 | **P1** | **LLM adapter selection by file extension** — `.gguf` → GGUFInferenceAdapter, else → MLXInferenceAdapter. Fragile. Should be config-driven. | `composition_root.py:216-221` |
| B-30 | **P2** | **`_wire_overseer_broadcast` hack** — injects lazily-bound bridge because overseer's `_engine` slot was "previously never populated." Bandaid for wiring problem. | `composition_root.py:169-184` |

---

### 3.8 Shim Layer — 60+ Re-export Modules

**What they are:** Files in `backend/app/domain/` that contain only:

```python
"""Re-export shim — moved to quant/amt/profile/lvn.py. Delete in Phase 3."""
from quant.amt.profile.lvn import *  # noqa: F401,F403
```

| # | Severity | Finding |
|---|----------|---------|
| B-31 | **P0** | **60+ files, broken tracebacks** — importing `from app.domain.services.lvn_detector import LVNPlayDetector` pulls from `quant.amt.profile.lvn`. Tracebacks show the shim file, not the real source. Debugging is a treasure hunt. |
| B-32 | **P0** | **Star imports everywhere** — `from quant.contracts.enums import *`. IDE autocomplete is broken. `__all__` may not cover everything. Circular import risk. |
| B-33 | **P1** | **Test surface inflation** — tests importing via shims test the shim path, not canonical path. A broken shim doesn't fail; it silently imports the wrong symbol. |

**Full shim inventory (60 files):**

```
backend/app/shared/timezones.py                    → quant.contracts.timezones
backend/app/domain/constants.py                     → quant.contracts.constants
backend/app/domain/models/exchange_config.py        → quant.contracts.exchange_config
backend/app/domain/trading/events.py                → quant.contracts.events
backend/app/domain/trading/models/enums.py          → quant.contracts.enums
backend/app/domain/trading/event_store.py           → quant.contracts.event_store
backend/app/domain/trading/models/trading_context.py → quant.contracts.trading_context
backend/app/domain/trading/models/vwap_bands.py     → quant.contracts.vwap_bands
backend/app/domain/trading/models/value_objects.py  → quant.contracts.value_objects
backend/app/domain/trading/models/utils.py          → quant.contracts.utils
backend/app/domain/trading/models/aggregates.py     → quant.contracts.aggregates
backend/app/domain/trading/models/initial_balance.py → quant.contracts.initial_balance
backend/app/domain/trading/models/volume_profile.py → quant.contracts.volume_profile_models
backend/app/domain/trading/models/entities.py       → quant.contracts.entities
backend/app/domain/trading/models/cvd.py            → quant.contracts.cvd
backend/app/domain/ports/notification_adapter.py    → quant.contracts.ports.notification_adapter
backend/app/domain/ports/probability_inference.py   → quant.contracts.ports.probability_inference
backend/app/domain/ports/npoc.py                    → quant.contracts.ports.npoc
backend/app/domain/ports/llm_inference.py           → quant.contracts.ports.llm_inference
backend/app/domain/ports/__init__.py                → quant.contracts.ports
backend/app/domain/fabio_ai/services/exit_rules.py  → quant.execution.exit_rules
backend/app/domain/fabio_ai/services/session_context_factory.py → quant.amt.session.context_factory
backend/app/domain/fabio_ai/services/orderflow_detectors.py → quant.amt.orderflow.detectors
backend/app/domain/fabio_ai/services/mlx_compute.py → quant.amt.compute
backend/app/domain/fabio_ai/services/vwap_breakout.py → quant.decision.vwap_breakout
backend/app/domain/fabio_ai/services/market_state_engine.py → quant.amt.market.state_engine
backend/app/domain/fabio_ai/services/profile_factory.py → quant.amt.profile.factory
backend/app/domain/fabio_ai/services/footprint_analyzer.py → quant.amt.orderflow.footprint
backend/app/domain/fabio_ai/services/market_structure_classifier.py → quant.amt.market.structure
backend/app/domain/fabio_ai/services/order_flow_service.py → quant.amt.orderflow.service
backend/app/domain/fabio_ai/services/eia_calendar.py → quant.amt.session.eia
backend/app/domain/fabio_ai/strategy/squeeze_detector.py → quant.amt.market.squeeze
backend/app/domain/services/aggressive_prints.py    → quant.amt.orderflow.aggressive_prints
backend/app/domain/services/one_min_bar_engine.py   → quant.amt.session.one_min_bar
backend/app/domain/services/symbol_registry.py      → quant.amt.session.symbol_registry
backend/app/domain/services/tick_delta.py           → quant.amt.orderflow.tick_delta
backend/app/domain/services/tick_utils.py           → quant.contracts.tick_utils
backend/app/domain/services/candle_metrics.py       → quant.contracts.candle_metrics
backend/app/domain/services/acceptance_rejection.py → quant.amt.market.acceptance_rejection
backend/app/domain/services/displacement_detector.py → quant.amt.market.displacement
backend/app/domain/services/market_data_utils.py    → quant.contracts.market_data_utils
backend/app/domain/services/decimal_utils.py        → quant.contracts.decimal_utils
backend/app/domain/services/break_detector.py       → quant.amt.market.break_detector
backend/app/domain/services/lvn_detector.py         → quant.amt.profile.lvn
backend/app/domain/services/ib_breakout_scalp.py    → quant.amt.session.ib_scalp
backend/app/domain/services/lvn_play_detector.py    → quant.amt.market.lvn_play
backend/app/domain/services/initial_balance_engine.py → quant.amt.session.ib_engine
backend/app/domain/services/volume_profile.py       → quant.amt.profile.volume_profile
backend/app/domain/services/delta_profile.py        → quant.amt.profile.delta_profile
```

Plus 10+ more in `backend/app/domain/fabio_ai/services/` (profile_classifier, regime_detector, opening_classifier, drive_decay, drive_tracker, cvd_tracker, aggression_scorer, npoc_tracker, absorption_rejection, three_align).

---

## 4. Quant Engine Audit

### 4.1 Auction Coordinator — `quant/coordinator.py` (53 lines)

```python
class AuctionCoordinator:
    def on_bar_close(self, bar: Bar) -> AuctionState:
        self._vp_builder.update(bar)
        self._vwap_builder.update(bar)
        self._of_builder.update(bar)
        self._abs_detector.update(bar)
        self._loc_builder.update(bar)

        vp = self._vp_builder.snapshot()
        vwap = self._vwap_builder.snapshot()
        of = self._of_builder.snapshot()
        absorption = self._abs_detector.snapshot()
        loc = self._loc_builder.snapshot(vp, bar.close)

        phase = self._triple_a.update(bar, vp, vwap, absorption)
        signal = self._triple_a.last_signal

        return AuctionState(time, close, vp, vwap, of, absorption, loc, phase, signal)
```

**Verdict: ✅ Correct.** Matches architecture doc exactly. Pure, deterministic, immutable output. Same bars in → same states out.

**The six detectors:**

| Detector | File | Lines | Status |
|----------|------|-------|--------|
| `VolumeProfileBuilder` | `quant/volume_profile.py` | ~200 | ✅ CME avg-weighted, POC + VAH/VAL |
| `VWAPBuilder` | `quant/vwap.py` | ~100 | ✅ Volume-weighted, ±1σ, ±2σ |
| `OrderFlowBuilder` | `quant/order_flow.py` | ~80 | ✅ Delta, CVD, CVD slope |
| `AbsorptionDetector` | `quant/absorption.py` | ~120 | ✅ Vol > 1.5× avg + compressed range |
| `LocationBuilder` | `quant/location.py` | ~100 | ✅ IB, zone, nearest level |
| `TripleAStateMachine` | `quant/triple_a.py` | ~150 | ✅ WAIT→ABSORB→ACCUM→SIGNAL |

### 4.2 Decision Pipeline — `quant/decision/`

```
AuctionState + DecisionContext → GatePipeline (5 gates)
  ├─ Gate 1: Session phase + position check
  ├─ Gate 2: Cooldown
  ├─ Gate 3: Direction + probability
  ├─ Gate 4: Triple-A edge
  └─ Gate 5: Risk-reward (min RR)
  ↓
SignalBuilder → Signal (entry, sl, tp, rr)
  ↓ (fallback)
detect_va_fade → VA fade signal
```

| File | Lines | Purpose |
|------|-------|---------|
| `decision_service.py` | 51 | Orchestrates gates → signal → VA fade |
| `pipeline.py` | ~200 | 5-gate evaluation |
| `signal_builder.py` | ~80 | Builds Signal from passed gates |
| `va_fade.py` | ~60 | Tier-2: value-area fade detection |
| `context.py` | ~40 | DecisionContext dataclass |
| `result.py` | ~20 | GateResult dataclass |

**Verdict: ✅ Correct logic, but not wired to execution.** The `DecisionService.evaluate()` returns `QuantDecision(approved=True, signal=...)` when all gates pass. The `QuantBridge` stores this as `session.last_quant_decision`. Nothing reads it for execution.

### 4.3 Gaps in Quant

| Gap | Impact | Effort |
|-----|--------|--------|
| **No NSE session rules** — "first 15 min NO TRADES" is in training data but not in quant gates. | Greenfield decisions won't respect session rules. | Small (1 gate) |
| **No loss-based stop** — "5 losses = STOP trading" is in training data. `SessionRisk` tracks losses but threshold not wired to gates. | Capital protection gap. | Small (1 gate field) |
| **No position sizing** — `SessionRisk.position_size()` computes quantity. But tick size, margin, broker constraints not in quant path. | Paper trades at wrong sizes. | Medium |
| **No execution bridge** — `QuantEngine` has `PaperOMS`. Live path uses `DhanBrokerAdapter` via legacy session. No path from `QuantDecision.approved=True` to actual order submission. | **Greenfield cannot place trades.** | Medium |
| **Weak test coverage** — 107 tests for ~10K lines. Key gaps: Triple-A transitions, VA fade fallback, gate interaction edge cases. | Refactoring is unsafe. | Medium |
| **Hardcoded agent values** — `agent_direction="LONG"`, `agent_probability=0.7` in standalone engine. | Decisions are always LONG with 70% confidence. | Small |

---

## 5. Frontend Audit

### 5.1 WebSocket Hook — `frontend/src/hooks/useServerTradingSystem.ts` (810 lines)

**Responsibility:** WS connection, state updates, RAF batching, reconnection, history loading.

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| F-01 | **P0** | **280 lines of state merging** — `handleWsMessage` handles: server_mode, history_loaded, gap_fill, delta, full state, pong, errors. Each branch mutates `InstrumentState` differently. Race between delta and full state is possible. | `useServerTradingSystem.ts:376-668` |
| F-02 | **P1** | **RAF batching drops oldest updates** — `MAX_RAF_QUEUE_SIZE = 10`. When queue overflows, oldest updates are discarded. In fast markets, stale AMT data displays. | `useServerTradingSystem.ts:166-169` |
| F-03 | **P1** | **Frontend gap filling fabricates data** — `mergeCandleData` forward-fills missing candles with zero-volume bars at previous close. Chart looks continuous but has phantom candles. | `useServerTradingSystem.ts:82-126` |
| F-04 | **P1** | **Three URL resolution strategies** — `VITE_BACKEND_URL`, dev proxy, direct hostname. REST and WS URLs computed differently. Misconfig = REST works, WS fails. | `useServerTradingSystem.ts:192-220` |
| F-05 | **P2** | **Message dedup declared but unused** — `recentMessageIdsRef` created at line 153, never read/written. Dead code. | `useServerTradingSystem.ts:153-154` |

**Failure Scenario (F-01):** Backend sends delta at T+0, then full state at T+16ms (next frame). React batches both. Delta sets `amtAnalysis.fieldX = "LONG"`. Full state sets `amtAnalysis = null` (AMT failed this tick). Order of application: delta first, then full overwrites → correct. But if full arrives first (network reordering), delta patches onto new null → `TypeError: cannot set properties of null`.

---

### 5.2 Types — `frontend/src/types.ts` (326 lines)

| # | Severity | Finding |
|---|----------|---------|
| F-06 | **P1** | **`AMTAnalysis` has 50+ optional fields** — every field after `legVal` is `?`. Frontend renders cards based on fields that may not exist. Missing field = blank card, not error state. |
| F-07 | **P1** | **Three analysis types coexist** — `AMTAnalysis` (legacy), `AuctionAnalysis` (greenfield), `QuantDecisionAnalysis` (greenfield decision). UI renders all three side by side. User sees AMT=LONG and Quant=NO_EDGE with no indication of authority. |
| F-08 | **P2** | **`AIAnalysis` type is unused** — `sentiment`/`confidence`/`quantScore` type exists but backend doesn't send this shape. Dead type. |

---

### 5.3 Data Overload

The `InstrumentState` sends **12 data sections** per symbol to the UI:

| Section | Source | Fields | Authoritative? |
|---------|--------|--------|----------------|
| `amtAnalysis` | Legacy AMT | 30+ | ✅ (executes trades) |
| `auctionAnalysis` | Greenfield quant | 20 | ❌ (dashboard only) |
| `quantDecisionAnalysis` | Greenfield decision | 6 | ❌ (never executes) |
| `genAIAnalysis` | LLM entry | 6 | ❌ (advisory) |
| `agentDecision` | Micro-agent | 7 | ⚠️ (feeds legacy gates) |
| `overseerAction` / `overseerReason` | LLM overseer | 2 | ❌ (advisory) |
| `riskState` | Risk manager | 5 | ✅ |
| `portfolio` | Paper broker | 4 | ✅ |
| `llmHistory` | LLM history | 20 entries | ❌ (log) |
| `orderBook` | Depth | N×2 | ✅ |
| `tick` | Current candle | 10 | ✅ |
| `runtimeSafety` | Safety checks | 3+ | ⚠️ |

**The architecture doc says "chart + decision card." The reality is a data firehose with 12 sections, 3 of which are analysis outputs (2 conflicting), and only one executes trades.**

---

## 6. Data Flow — Tick to Screen

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ DHAN WS → TradingEngine._tick_loop_forever()                                │
│   ├─ Futures aggregator → underlying OHLC (for IB engine)                   │
│   ├─ Option aggregator → option OHLC                                        │
│   ├─ Footprint accumulator                                                  │
│   ├─ 500ms throttle check → cached state if throttled                       │
│   └─ asyncio.to_thread(session_service.process_tick()) ← BLOCKING PER TICK  │
│                                                                             │
│   ┌─ process_tick() (657 lines) ───────────────────────────────────────┐    │
│   │                                                                      │    │
│   │   PhaseManager.check_and_handle_phase()                              │    │
│   │   AMTService.run_analysis()                                           │    │
│   │     ├─ AMTHandler.analyze() ← VOLUME PROFILE + ORDER FLOW            │    │
│   │     ├─ QuantBridge.on_bar_close() ← GREENFIELD AUCTION STATE         │    │
│   │     └─ underlying state sync (60s TTL cache)                          │    │
│   │   IB Engine.update()                                                  │    │
│   │   IB Scalp Engine.evaluate()                                          │    │
│   │   1-Min Bar Engine.update()                                           │    │
│   │   Pre-Candle Advisor (T-60s before bar close)                         │    │
│   │   Position management (if has position):                              │    │
│   │     ├─ Exit checks                                                    │    │
│   │     ├─ RL Handler                                                     │    │
│   │     └─ Trade Lifecycle Handler                                        │    │
│   │   Entry decision (if no position):                                    │    │
│   │     ├─ Micro-agent pipeline (probability)                             │    │
│   │     ├─ SessionEventRouter.route_entry_signal()                        │    │
│   │     │   └─ GatePipeline (LEGACY, 800 lines)                           │    │
│   │     ├─ LLM Entry Handler (60s cooldown)                               │    │
│   │     └─ Overseer Handler                                               │    │
│   │   ← QuantBridge stores last_quant_decision (NOT EXECUTED) ────────── │    │
│   └──────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│   StateBroadcaster.set_state() → notify_viewers()                            │
│   ┌─ WebSocket _viewer_loop() ───────────────────────────────────────┐    │
│   │ Generation wait → delta compute → JSON send → RAF on client      │    │
│   └──────────────────────────────────────────────────────────────────┘    │
│   ┌─ React useServerTradingSystem ──────────────────────────────────┐    │
│   │ WS onmessage → JSON parse → delta merge → RAF batch → render    │    │
│   └─────────────────────────────────────────────────────────────────┘    │
│   ┌─ React Components ────────────────────────────────────────────┐    │
│   │ Chart (Lightweight Charts) + Analysis Cards + Decision Panel   │    │
│   └───────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Latency Budget Per Tick

| Stage | Time | Notes |
|-------|------|-------|
| Dhan WS → engine | ~10ms | Network |
| Candle aggregation | ~1ms | Pure function |
| `asyncio.to_thread` overhead | ~500μs | Thread pool dispatch |
| `process_tick()` — AMT + quant + agents | **50-200ms** | **THE BOTTLENECK** |
| State broadcast + WS | ~5ms | JSON serialization |
| Frontend RAF batch | ~16ms | One animation frame |
| **Total** | **65-215ms** | Within 500ms throttle floor → ~2 updates/sec |

---

## 7. Training Data Gap

### What Exists

```
amt_dataset/
├── nifty_amt_data/              ← key:value format (1,150 rows)
│   ├── train.jsonl              (920 rows)
│   ├── val.jsonl                (115 rows)
│   └── test.jsonl               (115 rows)
└── nifty_amt_data_livefmt/      ← ChatML JSON (1,150 rows, live-format)
    ├── train.jsonl              (920 rows)
    ├── val.jsonl                (115 rows)
    └── test.jsonl               (115 rows)
```

### The Distribution Shift

**Training data format** (`nifty_amt_data/`):
```
session: nse
time: 11:00
state: IMBALANCED
poc: above
rejection: yes
note: Failed auction at VAH, max 2 re-entries per LVN
```

**Live LLM prompt** (from `prompt_builder.py`):
```
SESSION: NSE | TIME: 11:00 | PHASE: MID_SESSION
MARKET STATE: IMBALANCED — price above prior POC (21,650)
VALUE AREA: VAH 21,720 | VAL 21,580 | POC 21,650
ORDER FLOW & AGGRESSION: Buy absorption at 21,650, aggression 0.82
CVD: +1,800 slope rising | Delta: +450
STRUCTURE: First drive sell-off complete, second drive buying
TRIPLE-A PHASE: ACCUMULATING
```

**The model trains on structured key-value but receives free-form prose at inference.** The `livefmt` directory was regenerated to match the live format but is not wired to any training pipeline.

### Impact

LLM decisions are unreliable because the model has never seen the actual input format it receives in production. This explains:
- Inconsistent confidence levels
- Rationales that don't match the prompt context
- Occasional hallucinated setups

### Fix

Retrain on `nifty_amt_data_livefmt/` OR switch live prompts to key-value format. The `livefmt` approach is preferred because the narrative format is richer and matches how the trader actually reads the dashboard.

---

## 8. Root Causes Ranked by Impact

| Rank | Root Cause | Impact | Fix Effort |
|------|-----------|--------|-----------|
| **1** | Two analysis engines, only one executes | Greenfield decisions computed but never reach broker. Legacy AMT is 657-line mess. | Medium (wire quant → execution) |
| **2** | 60+ shim modules with star imports | Tracebacks lie. IDE broken. Tests test shim paths. Refactoring is a minefield. | Small (find-and-replace) |
| **3** | `TradingSessionService.process_tick()` is 657 lines | 17 collaborators, 8 responsibilities. Cannot unit test sub-steps. | Large (extract to pipeline) |
| **4** | `asyncio.to_thread` per tick | Thread pool contention under load. Should be queue-driven worker. | Small (rewrite tick loop) |
| **5** | Training data format mismatch | LLM sees prose at inference, trained on key-value. Decisions unreliable. | Small (retrain on livefmt) |
| **6** | Frontend renders 3 analysis types side by side | User sees conflicting signals (AMT=LONG, Quant=NO_EDGE). No authority. | Small (hide legacy, show quant) |
| **7** | `QuantEngine` not used in production | Clean 149-line engine exists but live uses 523-line `TradingEngine`. Two bug surfaces. | Medium (migrate) |
| **8** | Missing hard rules in quant gates | NSE 15-min avoid, 5-loss stop, position sizing not in greenfield. | Small (add to gates) |

---

## 9. Remediation Plan

### Phase 1 — Delete Shims (1-2 days)

**Goal:** Every import resolves to its canonical `quant.*` path. Tracebacks tell the truth.

| Step | Action | Risk |
|------|--------|------|
| 1.1 | Generate import map: `grep -r "from app.domain" backend/ --include="*.py" \| sort` | None |
| 1.2 | Replace all imports pointing through shims with canonical `quant.*` paths | Medium — may break circular imports |
| 1.3 | Delete all 60+ shim files | None — after imports rewritten |
| 1.4 | Run full test suite, fix breakage | Expected: 50-100 test failures from stale imports |
| 1.5 | Delete `backend/app/domain/services/` (empty after shim removal) | None |
| 1.6 | Delete `backend/app/domain/fabio_ai/services/` shim subdirectory | None |

**Result:** ~60 fewer files. Tracebacks show real sources. IDE autocomplete works. Codebase is navigable.

---

### Phase 2 — Wire Greenfield to Execution (2-3 days)

**Goal:** `QuantDecision.approved=True` → actual order submission. Legacy path becomes fallback/off.

| Step | Action | Risk |
|------|--------|------|
| 2.1 | Enable `QUANT_DECISION_ENABLED = True` by default in config | Low — greenfield runs in parallel, doesn't break legacy |
| 2.2 | Add NSE session rules to `quant/decision/gates_session_position.py` — 15-min avoid flag | Low — pure gate logic |
| 2.3 | Wire loss-based stop to `quant/decision/gates_edge.py` — read `SessionRisk.consecutive_losses` | Low — one gate field |
| 2.4 | Route `QuantDecision.approved=True` → `Signal` → broker adapter in `SessionEventRouter` | **High** — this is the execution path. A/B gate: legacy executes if quant decision is None |
| 2.5 | Add `quantDecision` field to WS snapshot (already exists via `state_snapshot_builder`) | None — already wired |
| 2.6 | Frontend: make `quantDecisionAnalysis` the primary decision card, gray out `amtAnalysis` | None — UI change |

**Result:** Greenfield decisions execute. Legacy path is shadow mode. Can compare outcomes.

---

### Phase 3 — Kill Legacy AMT Path (3-5 days)

**Goal:** One analysis path. ~400 fewer files. `process_tick()` drops from 657 to ~100 lines.

| Step | Action | Risk |
|------|--------|------|
| 3.1 | Remove `AMTService` from tick path. Replace with `QuantBridge.on_bar_close_with_decision()` | **High** — removes legacy analysis |
| 3.2 | Remove `AMTHandler` and all 20+ legacy detectors from import chain | Medium — some may be used by tests only |
| 3.3 | Replace legacy `GatePipeline` (800 lines) with `quant.decision.pipeline.GatePipeline` (200 lines) | **High** — different gate logic |
| 3.4 | Remove `IBScalpEngine`, `OneMinBarEngine` from tick path (or migrate to quant) | Medium — these are separate strategies |
| 3.5 | Remove micro-agent pipeline from hot path (keep as offline analysis) | Low — was advisory |
| 3.6 | Simplify `process_tick()` to: quant bridge → decision → execute → broadcast | **High** — rewrites the core loop |
| 3.7 | Frontend: remove `amtAnalysis` from `InstrumentState`. Keep `auctionAnalysis` + `quantDecisionAnalysis`. | None — UI cleanup |

**Result:** One analysis path. `process_tick()` ~100 lines. ~400 fewer files. Frontend shows one decision.

---

### Phase 4 — Migrate to QuantEngine (1 week)

**Goal:** Deterministic engine. Backtest == production. No `asyncio.to_thread` per tick.

| Step | Action | Risk |
|------|--------|------|
| 4.1 | Add multi-symbol support to `QuantEngine` — one `AuctionCoordinator` per symbol | Medium |
| 4.2 | Build `DhanGateway` adapter implementing `BrokerGateway` interface for quant | Medium |
| 4.3 | Replace `asyncio.to_thread` with queue-driven worker: ticks → `asyncio.Queue` → worker | **High** — rewrites tick loop |
| 4.4 | Wire `QuantEngine` events to `StateBroadcaster` → WebSocket | Medium |
| 4.5 | Remove `TradingEngine`, `CandleAggregator` (backend), `TickProcessor` | High — deletes old engine |
| 4.6 | Migrate LLM advisory to event-subscriber pattern (subscribe to `AuctionUpdated` events) | Low |

**Result:** 149-line engine runs production. Same code for backtest and live. No thread pool per tick.

---

### Phase 5 — Fix Training Data (1-2 days)

**Goal:** LLM decisions become reliable for the advisory role they play.

| Step | Action | Risk |
|------|--------|------|
| 5.1 | Verify `nifty_amt_data_livefmt/` matches current `prompt_builder.py` output format | Low |
| 5.2 | Retrain model on `livefmt` data (or fine-tune from existing checkpoint) | Low — LLM is advisory only |
| 5.3 | Add format validation: assert live prompt matches training distribution | Low |
| 5.4 | Delete original `nifty_amt_data/` (keep `livefmt/` as canonical) | None |

**Result:** LLM sees the same format at training and inference. Decisions improve.

---

## A. Inventory

### Codebase Metrics

| Metric | Value |
|--------|-------|
| Total lines (project) | ~241K |
| Backend Python files | ~180 |
| Backend Python lines | ~100K |
| Quant Python files | ~65 |
| Quant Python lines | ~10K |
| Shim files (re-export only) | 60+ |
| Frontend TypeScript files | ~25 |
| Frontend TypeScript lines | ~10K |
| Tests (total) | ~1,990 |
| Tests (quant only) | 107 |
| WebSocket endpoints | 2 |
| REST endpoints | 12 |

### File Size Distribution (Backend)

| Range | Count | Examples |
|-------|-------|---------|
| >500 lines | 8 | `trading_session.py` (1,067), `engine.py` (523), `composition_root.py` (416) |
| 200-500 lines | 25 | `amt_handler.py`, `gate_pipeline.py`, `prompt_builder.py` |
| 50-200 lines | 80 | Most services, handlers, adapters |
| <50 lines | 67 | Shims, small utilities, `__init__.py` files |

### Git History

| Metric | Value |
|--------|-------|
| Recent commits (brain migration) | 30+ |
| Migration pattern | `backend/app/domain/` → `quant/` (via shims) |
| Phase 0 (migration) | ✅ Complete |
| Phase 1 (event-driven runtime) | ✅ Complete |
| Phase 2 (wire to execution) | ⏳ In progress (feature-flagged) |
| Phase 3 (delete shims) | ❌ Not started |
| Phase 4 (migrate to quant engine) | ❌ Not started |

---

## B. Findings Index

### P0 — Critical (12 findings)

| ID | Component | Summary |
|----|-----------|---------|
| B-01 | main.py | Startup blocks for 2+ minutes |
| B-02 | main.py | Three DI paths coexist |
| B-06 | engine.py | `asyncio.to_thread` on every tick |
| B-07 | engine.py | 500ms throttle produces inconsistent state |
| B-11 | trading_session.py | 657-line `process_tick()` method |
| B-12 | trading_session.py | Greenfield quant decisions never execute |
| B-13 | trading_session.py | AMT failure doesn't abort tick |
| B-18 | amt_service.py | QuantBridge coupled inside AMT path |
| B-21 | quant_bridge.py | Module-level singleton |
| B-22 | quant_bridge.py | `QUANT_DECISION_ENABLED` defaults to disabled |
| B-25 | runtime.py | QuantEngine not used in production |
| B-31 | shims | 60+ files, broken tracebacks |

### P1 — High (18 findings)

| ID | Component | Summary |
|----|-----------|---------|
| B-03 | main.py | Startup telemetry is 400 lines of dead weight |
| B-04 | main.py | Health router registered twice |
| B-08 | engine.py | Dual aggregators create divergence |
| B-09 | engine.py | Circuit breaker silently drops ticks |
| B-14 | trading_session.py | `hasattr` instead of proper init |
| B-15 | trading_session.py | Signal stale threshold = 10 minutes |
| B-16 | trading_session.py | Stage latency tracking is dead code |
| B-19 | amt_service.py | Underlying state sync with 60s TTL |
| B-20 | amt_service.py | `_UNDERLYING_MIN_CANDLES = 5` bandaid |
| B-23 | quant_bridge.py | `_build_decision_context` reverse-engineers state |
| B-24 | quant_bridge.py | Hardcoded defaults |
| B-26 | runtime.py | Hardcoded agent values |
| B-27 | runtime.py | Single symbol only |
| B-28 | composition_root.py | Two GatePipelines, different implementations |
| B-29 | composition_root.py | LLM adapter selection by file extension |
| B-32 | shims | Star imports everywhere |
| B-33 | shims | Test surface inflation |
| F-02 | frontend | RAF batching drops oldest updates |

### P2 — Medium (6 findings)

| ID | Component | Summary |
|----|-----------|---------|
| B-05 | main.py | `load_dotenv` at module level |
| B-10 | engine.py | 500ms throttle floor hardcoded |
| B-17 | trading_session.py | Cooldown rationale string manipulation |
| B-30 | composition_root.py | `_wire_overseer_broadcast` hack |
| F-05 | frontend | Message dedup declared but unused |
| F-08 | frontend | `AIAnalysis` type is unused |

---

*End of audit. Generated 2026-08-06 from branch `stable_4`.*