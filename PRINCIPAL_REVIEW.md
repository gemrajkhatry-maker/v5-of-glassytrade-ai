# Principal Review — GlassyTrade AI Trading Platform (current state)

**Role:** Principal Trading Systems Architect & Senior Code Reviewer
**Date:** 2026-08-13 · **Branch:** `stable_4`
**Scope:** Full-system audit of the booted architecture: `quant/`, `backend/`, `brokers/`, `frontend/`, `shared/`
**Severity framing:** This is treated as a **real-money trading system**. Every finding is graded:

| Grade | Meaning |
|---|---|
| 🔴 **CRITICAL** | Can cause financial loss, wrong orders, or unrecoverable state |
| 🟠 **HIGH** | Will cause divergence between components or maintenance collapse |
| 🟡 **MEDIUM** | Correctness risk under edge cases; significant debt |
| 🟢 **LOW** | Cleanup / hygiene |

---

## 0. Executive Summary

The previous review (same file, pre-`b48a975`) described **four parallel half-systems**: `backend/` + `backendv2/`, `brokers/` + `brokersv2/`. That problem has been **substantially resolved**. `backendv2/` and `brokersv2/` are deleted; the domain logic was consolidated into a single pure-Python core, and a large dead-code purge followed (10+ `refactor: delete …` commits). This is now a **single-stack, layered, mostly-clean architecture**:

```text
frontend/  (React, 9.9k LOC)          — pure-ish consumer, WS viewer
backend/   (FastAPI shell, 8.9k LOC)  — routers, WS transport, DI, SQLite, adapters
quant/     (domain core, 22.6k LOC)   — deterministic decision engine, stdlib-only
brokers/   (Dhan hexagon, 24k LOC)    — ports → domain → application → infrastructure
shared/    (684 LOC)                  — conversion/resilience helpers
```

**Test health (run 2026-08-13, project venv py3.13, after the 2026-08-13 cleanup):**

| Suite | Result |
|---|---|
| `backend/tests` (non-live, non-slow) | **1038 passed, 0 failed**, 61 skipped |
| `tests/` (root, non-live) | **1073 passed, 0 failed**, 28 skipped |
| `brokers/tests` | **439 passed, 1 skipped**, 2 deselected |
| `frontend vitest` | **160 passed** |

**~2,710 passing, 0 failing.** The 4 previously-failing tests were stale assertions against *deliberate, recent behavior changes* (SL placement convention commit `091a0c3`/`2ffaef5`; scanner probing 4 expiry indexes to find the nearest weekly). They are fixed in this pass, and the scanner expiry tests are now date-independent (computed next-Tuesday instead of the hardcoded `2026-08-11`, which was already in the past). The 48 test drop in `brokers/tests` is the removal of the dead `BrokerGateway` facade and its 3 test files (§3.11).

**Bottom line:** The platform is now architecturally coherent — one decision brain, one booted backend, one broker stack, ports/adapter boundaries that are actually enforced, near-zero TODO debt. The two highest-value remaining risks are (1) the **documented split-brain** between `AuctionCoordinator` (the WS `auction` projection) and `AMTAnalyzer` (the decision engine) running in parallel on every bar with *different VWAP definitions*, and (2) the **absence of any replay/golden-tape parity gate**, so determinism is claimed but never enforced end-to-end.

---

## 1. How the system is implemented (current state)

### 1.1 `quant/` — the decision core (survives; this is the right shape)

Pure Python, stdlib-only, zero `backend/` imports (verified: `quant/runtime.py`, `quant/coordinator.py` docstrings state this and the import surface is clean). This is the single best architectural decision in the codebase.

**Runtime topology:**

```
Dhan WS (via brokers/ adapter)
   → MultiplexedMarketFeed (one WS connection, ≤1000 instruments, per-symbol fan-out)
   → LiveGateway per symbol
   → QuantEngine (daemon thread per symbol; QuantCoordinator owns N engines)
        on bar close:
          AuctionCoordinator.on_bar_close(bar)  → AuctionState   (WS "auction" projection)
          AMTAnalyzer.analyze(bar)              → AMTResult→DTO  (decision-engine inputs)
          DecisionService.evaluate(ctx)         → QuantDecision  (7 gates → SignalBuilder → VA-fade)
          PaperOMS / ExitEngine / SessionRisk   → Position/Fill/Risk events
        → EventBus (typed frozen events) → StateProjector → WS snapshot
        → decision queue → backend shell
```

- **`quant/runtime.py` (1,144 lines)** — `QuantEngine`, the deterministic single-threaded event loop. Correct design: wall-clock time never enters `_decide`; the LLM is an **advisory overlay** (`_DETERMINISTIC_CONVICTION = 0.7`, LLM never gates a trade). Per-engine `ThreadPoolExecutor` for LLM fold-back, shut down on coordinator stop (`71f7690`).
- **`quant/coordinator.py` (398 lines)** — `QuantCoordinator`: option scanner → persisted contracts (`.active_contracts.json`, exchange-scoped, IST-day-scoped) → one engine per contract. Restart-safe contract selection, prior-session levels via `SessionLevelStore` (`.session_levels.json`).
- **`quant/decision/`** — `GatePipeline` runs **7 fail-fast gates** (session phase, position cooldown, failed-auction sequence, direction probability, Triple-A edge, risk-reward, LLM consensus), then `SignalBuilder`; falls back to Value-Area fade (tier-2); otherwise `NO_EDGE`. Every rejection carries structured `block_reasons` (`T11`).
- **`quant/execution/`** — `PaperOMS`, `SessionRisk` (daily-loss budget, persisted to kv-store so restarts don't wipe it), `ExitEngine`/`exit_rules.py` (599 lines: spread blowout, trailing stop, session-aware time stop, armed trail stop).
- **`quant/contracts/`** — entities, `value_objects.py` (Decimal `OHLC`), ports: `IBroker`, `IMarketData`, `IStorage`, `ILLMInference`, config port. Composition root is the **only** place concrete adapters are imported — DIP enforced.
- **`quant/events.py`** — frozen-typed `EventBus` (synchronous, ordered dispatch). Correct backbone.

### 1.2 `backend/` — API shell (thin, correctly)

- `app/main.py` — FastAPI lifespan: option scanner → `QuantCoordinator.start()` → startup **reconciliation** (fail-closed in live mode: refuses to boot on DB/broker position mismatch). Startup telemetry phases.
- `app/application/di/composition_root.py` — **the** dependency graph; the only module importing concrete adapters. Paper vs Dhan broker selected by `GLASSYTRADE_ENV`.
- `app/api/websocket/gameloop.py` (334 lines) — **server-driven** thin transport: polls coordinator snapshots, delta-compresses, streams to clients. The old client-pushes-ticks mode is deleted. Subscribe → `symbol_switched`.
- `app/infrastructure/` — SQLite storage (positions, trades, llm_decisions, kv), Dhan market-data adapter, Dhan broker adapter, Paper broker, GGUF inference adapter.
- `app/config_models/` — YAML + env config with validation.

### 1.3 `brokers/` — Dhan hexagon (clean)

`ports/` (auth, http, websocket, mapper, resilience) → `domain/` (entities, value objects, api contracts, segment mapping) → `application/services/` (order, market data, options, portfolio, streaming, historical) → `infrastructure/` (http client, websocket, auth provider, symbol mapper). Plus `paper/broker.py` and `gateway.py`. Contract-tested (487 tests). This is the shape the old review wanted.

### 1.4 `frontend/` — near-pure consumer (much improved)

- **Fixed since last review:** `mergeCandleData` gap-fill/forward-fill **deleted** (line 395 comment: *"history contains real candles; no candles are fabricated client-side"*); `dataSource: 'DHAN'` **removed** from `types.ts`/`constants.ts` (grep: 0 matches); chart managers are pure render functions.
- **Still present:** `calculateVWAPColor` in `components/chart/AMTLevelsOverlay.ts` (line 40) derives band *color/slope* from backend-provided `vwap` values — harmless style logic, but the one remaining place the frontend does any analysis-derived math; `useServerTradingSystem.ts` is 788 lines (transport + RAF batching + delta-merge + subscribe — a god-hook, but no longer fabricating data).
- **Regressions:** `types_generated.ts` is **missing** and `scripts/generate_types.py` **no longer exists**, but `package.json` still has `generate-types` scripts pointing at it, and docs still reference the generated-contract pipeline. The contract is hand-mirrored again.

### 1.5 `shared/` — small, one DIP violation still standing

The old review flagged `shared/entities/models.py` importing broker types. **Still present:** `shared/entities/models.py` defines its own `Exchange` enum (line 17) but `Instrument.is_index()` does `from brokers.broker.types import Exchange` at line 85 — shared code reaching into the broker layer (lazy import, so soft, but the dependency direction is wrong). 🟡

---

## 2. What the previous review flagged — status

| Old finding | Status |
|---|---|
| 4 parallel stacks (backend/backendv2, brokers/brokersv2) | ✅ **Resolved** — v2 stacks deleted (`b48a975`), one stack survives |
| 130 same-named duplicated files | ✅ **Resolved** by deletion |
| Copy-pasted gameloop | ✅ **Resolved** — one server-driven gameloop (334 lines) |
| TODO-stub tests passing | ✅ **Resolved** — TODO count ~0; tests assert (2,730 passing) |
| Frontend forward-fill fabricating candles | ✅ **Resolved** — deleted |
| `dataSource: 'DHAN'` direct-broker flag | ✅ **Resolved** — removed |
| Frontend re-implements VWAP (`calculateVWAP`) | ✅ **Resolved** in `VolumeSeriesManager` (only style-derivation `calculateVWAPColor` remains) |
| Replay only in broker layer, no engine replay | ⚠️ **Still open** — no replay path for the trading engine |
| Client-driven WS mode (frontend pushes ticks) | ✅ **Resolved** — deleted |
| Shared→broker dependency | ✅ **Resolved (2026-08-13)** — `is_index()` now uses the module's own `Exchange` enum (`brokers.broker.types` was a re-export of the same class) |
| Deprecated shims in tree | ✅ **Resolved** — purged |
| ≥7 VWAP implementations | ⚠️ **Partially** — down to ~5 (§3.2) |
| ≥5 Candle types | ⚠️ **Partially** — still ~5 (§3.3) |
| Parity/golden-tape CI gate | ❌ **Still open** — no golden tape exists |

---

## 3. Findings (graded)

### 🔴 3.1 Two production brains with different math (documented, but still wrong-shaped)

`quant/runtime.py` runs **both** `AuctionCoordinator` (`quant/coordinator.py`, feeds the live WS `auction` view) **and** `AMTAnalyzer` (`quant/amt/analyzer.py`, feeds the decision engine) on every closed bar. `docs/AMT_UNIFICATION.md` (a decision record) measures and **accepts** the divergence:

- VWAP: `AuctionCoordinator` is **close-weighted** (`Σ close·vol / Σ vol`); `AMTAnalyzer` is **typical-price-weighted** (`Σ (H+L+C)/3·vol / Σ vol`).
- POC/VAH: different bucket edges (`create_profile` adds a 1% price buffer; `VALUE_AREA_PCT` 0.70 vs 0.68) → ≤1% divergence on every bar.
- VAL: `AMTAnalyzer` applies a deliberate leg-VA clamp that can move VAL by **16%** on trend-leg bars.
- CVD slope: window/filter configs differ (20-bar OLS vs 40-bar + sign-persistence).
- IB: 6-bar window vs 30-minute wall-clock window (they coincide only on exactly-5-minute bars).

The ADR's "keep both, divergence budget ≤5%" is a reasonable *interim* position, but it means **the numbers the operator watches on the chart are not the numbers the engine trades on**, and the budget is enforced only by one synthetic-session test. This is the single most expensive remaining architectural risk — it is exactly the class of bug the old review called out (frontend/backend disagreement), moved one layer down.

**Also unresolved inside this finding:** `OHLC.create()` (Decimal coercion in `quant/contracts/value_objects.py`) breaks `AMTAnalyzer` (`AcceptanceRejectionEngine` compares `candle.volume` (Decimal) with a float → `TypeError`). The ADR logs it as a known latent bug (`incidental finding §4.6`) — still unfixed, and it means the AMT analyzer is only exercised with raw-float OHLC in tests, not with the production Decimal type.

### 🟠 3.2 VWAP still ×5

| Site | Definition |
|---|---|
| `quant/vwap.py` (`VWAPBuilder`) | close-weighted, incremental |
| `quant/amt/analyzer.py` (`_update_session_vwap`) | typical-price, incremental |
| `quant/contracts/market_data_utils.py` | helper |
| `quant/aggregator.py` | bar-level |
| `brokers/broker/dhan/domain/entities.py` | broker-side field |

Down from 7–8, but still not one implementation, and two of them disagree by definition.

### 🟠 3.3 Candle/OHLC still ×5

`quant/contracts/value_objects.py:OHLC` (Decimal) · `quant/bars.py:Bar` · `backend/.../schemas.py:OHLCDataDTO` · `brokers/.../dhan/domain/value_objects.py:OHLC` · `frontend/types.ts:OHLCData`. Plus hand-written mappers (`quant/state.py:133` maps Bar→OHLCData shape; `dto_to_ohlc` in schemas). Wire contracts are hand-mirrored, not generated (§3.5).

### 🟡 3.4 Stale tests (fixed 2026-08-13) — still no harness to catch the drift

Four tests were failing as stale assertions against *deliberate* behavior changes: `test_phase1_leaf_components.py` asserted the old SL convention (full bucket outside the VA edge) instead of the new 2-ticks-inside placement (`091a0c3`), and the scanner tests hardcoded `2026-08-11` as the "future weekly" expiry (already past on 2026-08-13, so the scanner correctly probed 4 expiry indexes). All four are fixed and the scanner tests are now date-independent.

The gap that let them rot is still open: no **golden-tape parity gate** (§4.2) — the thing that would fail the build the moment the SL convention or scanner behavior changes, instead of silently leaving red tests behind.

### 🟡 3.5 Contract generation pipeline deleted — broken npm scripts removed (2026-08-13)

`frontend/package.json` `generate-types`/`gen-types` scripts called `scripts/generate_types.py`, which **does not exist**; `frontend/types_generated.ts` is absent. The broken scripts are now **removed** from `package.json`; `docs/*` still describe the generated-contract authority and should be updated or the generator restored. The hand-mirrored `types.ts` ↔ `schemas.py` drift risk is back (in miniature).

### 🟡 3.6 No replay / golden-tape for the trading engine

`QuantEngine`'s docstring claims *"replaying the same tick sequence always yields the same event trace"* — and the design is genuinely deterministic — but there is **no recorded-session replay harness and no CI parity gate**. The only "determinism" evidence is unit tests on components. For a system that will place real orders, the absence of a **replay-a-recorded-day == expected-trace** regression gate is the top process gap.

### 🟡 3.7 WS transport is a polling loop with O(n²) diffs

`gameloop.py` polls `coordinator.snapshot()` on a timer and runs recursive `_deep_equal` over the whole per-symbol state for every client, every tick. Fine at 4 symbols / 1 operator; it will not survive 20 symbols × N clients, and it can't deliver true event push. The engine already emits typed events on an `EventBus` — the WS layer should consume those instead of diffing snapshots.

### 🟡 3.8 Frontend god-hook and residual style-derivation

`useServerTradingSystem.ts` (788 lines) is transport + reconnect/heartbeat + RAF batching + delta-merge + subscribe bookkeeping. Better than before (no data fabrication), but it's the backend-in-a-hook again, and `calculateVWAPColor` in `AMTLevelsOverlay.ts` still derives VWAP band *color/slope* client-side from backend-provided `vwap` values — minor (it doesn't recompute VWAP), but it's the one remaining spot where analysis-derived presentation logic lives in the UI and it's pinned by its own math test.

### 🟢 3.9 Hygiene / repo state

- `Makefile` **every target referenced `backendv2`** (deleted) — rewritten 2026-08-13 to `test-backend` / `test-quant` / `test-brokers` / `test-frontend` / `test-ci` against the surviving layout.
- Working tree is dirty: 67 modified + 49 untracked files (amt_dataset jsonl churn, backend tests, adapters). Uncommitted in-flight work — expected, but the review is against the working tree.
- `backend/venv/` exists but is gitignored (ok).
- Root clutter: `glassytrade.db*`, `backend.log`, `.env.bak-*` files.

### 🟢 3.11 Legacy `BrokerGateway` facade removed (2026-08-13)

`brokers/gateway.py` (435-line `BrokerGateway`/`BrokerFactory`/`create_*_gateway` facade) was a legacy second broker API: **nothing in the boot path used it** — the backend adapters use the Dhan hexagon (`brokers.broker.dhan`) directly and the coordinator uses `quant/brokers/live_gateway.py`. It was kept alive only by `brokers/__init__.py` re-exports and 3 test files. Deleted the facade, its tests (`test_gateway.py`, `test_e2e_nse_mcx.py`, `test_integration_market_data.py`), the one gateway test in `test_broker_interface.py`, the dead `brokers/broker/resilience.py` compat shim (zero importers), and pruned `brokers/__init__.py`. Behavioral coverage is intact: `TestPaperBroker` (direct) + `test_entities.py` cover the paper path and the Dhan hexagon keeps its 336 direct tests.

Also fixed: the `shared/entities/models.py` DIP violation (`is_index()` no longer lazy-imports `brokers.broker.types.Exchange`).

### 🟢 3.12 What is genuinely well done (credit where due)

- **Deterministic decision path** — LLM advisory-only, `_DETERMINISTIC_CONVICTION` const, no wall-clock in `_decide`. This is the correct call for a live system.
- **Fail-closed live startup** — reconciliation mismatch in live mode refuses to boot (`9bc0446`).
- **Risk persistence** — daily-loss budget survives restarts (`2033d11`, `71ce44c`).
- **Structured rejection audit** — `block_reasons[]` on every decision (`5c2fe8c`), gate names in UI.
- **Ports enforced at composition root** — the only DIP violation-free DI I've seen in this repo lineage.
- **Event trace capped** at 10k events (`d5cd3c8`) — heap growth guarded.
- **LLM temperature from env, per-engine executor shutdown** on coordinator stop (`71f7690`).
- **Tests actually assert** — 2,730 passing across 4 suites; TODO stubs gone.

---

## 4. How I would implement it (if I got the chance)

Keep the current topology — it is 80% right. The redesign is about closing the three open seams: **split-brain**, **no replay gate**, **polling WS**.

### 4.1 One analysis kernel, two projections (kill the split-brain)

Replace `AuctionCoordinator` + `AMTAnalyzer` with **one canonical, incremental analysis kernel** in `quant/amt` (it is the fuller engine): a single `AnalysisState` updated by `analyze(bar, state) -> AnalysisState`, with **one** VWAP definition (typical-price, volume-weighted std), **one** profile builder (`compute_value_area`), **one** IB window (bar-count, not wall-clock). Then:

- the **decision engine** consumes `AnalysisState` directly;
- the **WS `auction` projection** is a pure render adapter over the same `AnalysisState` (`projection(AnalysisState) -> AuctionState`), pinned by the existing golden-file test `tests/quant/test_golden_file.py`.

The divergence budget disappears because there is nothing left to diverge. `quant.core`'s snapshot shape survives as the projection, so the frontend contract doesn't change. Fix `OHLC.create()` (accept `Decimal | float`, coerce once at the boundary) in the same change.

### 4.2 Event-sourced replay + golden tape as a CI gate

- Persist every `EventBus` event (append-only log, already cheap: the engine emits ~10 events/bar).
- `ReplayEngine = QuantEngine(EventSource=LogReader)` — same `process(event, state)` core, replay clock controls timing only. Mode is an infrastructure concern.
- **Golden tape:** record one full synthetic (or paper) trading day; CI replays it on every commit and asserts the exact event trace + projection sequence. Any change to signal math, SL placement, gates, or VWAP that alters the trace **fails the build** — this is what would have caught the 4 stale tests and every future SL-convention change.
- Delete the divergence-budget test in favor of the golden tape (or keep it as a pre-migration measurement only).

### 4.3 Event-push WS instead of snapshot polling

- `gameloop.py` subscribes to the coordinator's `EventBus` (per-symbol queues), and ships **event envelopes** (`{v, seq, ts, type, payload}`) + per-event projection patches instead of timer-poll + full `_deep_equal`.
- Keep the full-snapshot message on connect/subscribe only.
- This removes the O(n²) diff, gives true push latency, and makes replay-vs-live visually identical by construction (same envelope).

### 4.4 Collapse the remaining duplicates

- One `Candle` type in `quant/contracts`; `BrokerCandle`/`OHLCDataDTO`/`OHLCData` become adapter-side conversions only.
- One VWAP (`quant/vwap.py` or the kernel's), imported everywhere.
- Restore `scripts/generate_types.py` (Pydantic → TS + Python + OpenAPI from `quant/contracts`) or delete the npm scripts and docs; do not leave a half-referenced pipeline.
- Rewrite the `Makefile` to the surviving layout and add `make parity` (golden tape) + `make test` (backend + root quant + brokers + frontend).

### 4.5 Frontend: finish the consumerization

- Delete `calculateVWAPColor` + its math test; style bands from backend `AMTAnalysis.vwapUpper/Lower*` (already emitted).
- Split `useServerTradingSystem.ts` into: `useTransport` (connect/reconnect/heartbeat) + `useServerState` (delta-merge into the existing Zustand `stores/ui.ts`) + a `tickBus` chart fast-path (the pattern already exists).
- Frontend renders gaps as empty, never fabricates.

### 4.6 Testing and ops hardening

- **Property tests** (hypothesis is already in the repo): Order/Position state machines (no mutation after CLOSED, `sl < entry < tp`), Decimal invariants, Candle `H≥L`, `O,C ∈ [L,H]`.
- **Structured audit log** end-to-end: every order, fill, risk event, and decision with `block_reasons` already flows through typed events — persist them; expose an ops endpoint.
- **Circuit breakers** on broker calls already exist in `brokers/` resilience — keep, and add metrics on breaker trips.
- Fix the 4 stale tests now (assert the new SL convention and the 4-expiry scan), so the branch is green *before* the golden tape lands.

---

## 5. Roadmap

| Phase | Scope | Validation |
|---|---|---|
| **P0 (now)** | Fix 4 stale tests; restore/delete `generate_types` references; rewrite Makefile; fix `OHLC.create()` Decimal bug | All 4 suites green; `make test` works |
| **P1 (2–3 wks)** | Golden-tape replay harness + CI gate (no domain changes) | Replay of recorded session == recorded trace; gate blocks drift |
| **P2 (3–5 wks)** | Unify analysis kernel (§4.1); one VWAP, one Candle; WS event-push (§4.3) | Golden tape unchanged after refactor; WS latency drops; divergence budget deleted |
| **P3 (frontend)** | Delete `calculateVWAPColor`; split god-hook; restore generated types | Zero indicator math in `frontend/` (grep gate); contract snapshot test |
| **P4 (ops)** | Property tests, audit-log endpoint, breaker metrics, `make parity` in CI | p99 tick latency budget; audit trail complete |

---

## 6. Evidence map

| Claim | Evidence |
|---|---|
| v2 stacks deleted | `git log --diff-filter=D -- backendv2/**` → `b48a975 chore: remove v2 stacks, dead scripts, docs and build artifacts` |
| Single booted backend | `start.sh` runs `uvicorn app.main:app` in `backend/` on :9090; lifespan boots `QuantCoordinator` |
| Deterministic engine claim | `quant/runtime.py:1-8` docstring; `_DETERMINISTIC_CONVICTION=0.7` at :63 |
| Split-brain in production | `quant/runtime.py:167-175` instantiates `AuctionCoordinator` **and** `AMTAnalyzer`; `_on_bar_closed` runs both (:305-314) |
| Divergence measured/accepted | `docs/AMT_UNIFICATION.md` §3–5 (VAL 16% on clamp bars; VWAP definitional 0.14%) |
| `OHLC.create()` Decimal bug | `docs/AMT_UNIFICATION.md` §4.6; `quant/contracts/value_objects.py:37` |
| VWAP ×5 | `quant/vwap.py`, `quant/amt/analyzer.py`, `quant/contracts/market_data_utils.py`, `quant/aggregator.py`, `brokers/broker/dhan/domain/entities.py` |
| Candle ×5 | `quant/contracts/value_objects.py:19`, `quant/bars.py:9`, `backend/app/infrastructure/serialization/schemas.py:31`, `brokers/broker/dhan/domain/value_objects.py:460`, `frontend/types.ts:2` |
| `generate_types.py` missing | `find . -name generate_types.py` → 0; `frontend/types_generated.ts` → missing; `frontend/package.json` still calls it |
| Makefile stale | `grep backendv2 Makefile` → every target |
| Frontend fabrication removed | `frontend/hooks/useServerTradingSystem.ts:395-396` comment; grep `dataSource` → 0 |
| Frontend style-derivation remains | `frontend/components/chart/AMTLevelsOverlay.ts:40` `calculateVWAPColor` (slope/color over backend `vwap`) + its test |
| Test counts (post-cleanup) | backend 1038/0/61, root `tests/` 1073/0/28, brokers 439/1/2, frontend 160 — run 2026-08-13 on `.venv` py3.13 |
| Stale SL tests fixed | `test_phase1_leaf_components.py` now asserts SL 97.9/102.1 (2 NSE-option ticks inside VA edge, `091a0c3`/`2ffaef5`) and tests the thin-stop guard directly |
| Stale scanner tests fixed | `test_scanner.py` now uses a computed next-Tuesday expiry (date-independent) and asserts single-chain-call for the nearest weekly |
| BrokerGateway facade removed | `brokers/gateway.py` + `test_gateway.py` + `test_e2e_nse_mcx.py` + `test_integration_market_data.py` deleted; nothing in the boot path imported `brokers.gateway` |
| Dead shim removed | `brokers/broker/resilience.py` — zero importers (scan 2026-08-13) |
| Shared DIP fixed | `shared/entities/models.py:85` lazy broker import removed; `is_index()` uses the local `Exchange` (identical class — `brokers.broker.types` is a re-export) |
| Makefile fixed | rewritten to `test-backend`/`test-quant`/`test-brokers`/`test-frontend`/`test-ci`; previously every target `cd backendv2` |
