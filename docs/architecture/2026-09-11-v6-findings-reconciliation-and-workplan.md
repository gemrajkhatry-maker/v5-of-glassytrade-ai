# GlassyTrade AI — v6.0 Findings Reconciliation & Multi-Agent Working Plan

**Date:** 2026-09-11
**Branch:** `architecture/design-level-refactoring`
**Companion docs:**
- `docs/architecture/2026-09-11-design-level-refactoring-specification.md` (design intent, invariants, sequencing)
- `docs/architecture/2026-09-11-v6-parallel-execution-plan.md` (the 36-node dependency graph, parallel waves, critical path)
- `docs/architecture/2026-09-11-v6-execution-graph.json` (machine-readable DAG — resolve with `make plan`)
**Audited target in the review:** `v5.2` @ `b127779f`
**Verified against:** current working tree (HEAD + 10 uncommitted files)

---

## 0. Why this document exists

An external institutional review asserted 20 ranked risks and a v6.0 target layout against
`v5.2`. The review is directionally useful but **partially stale**: this branch has already
closed several of its findings, while others are worse than the review states (the god
classes have grown). Nothing may be scheduled off an unverified finding, so this document:

1. Re-verifies every finding against the current tree with `file:line` evidence (§2).
2. Separates **real open work** from **already-closed** and **incorrect claims** (§2.4).
3. Maps the v6.0 target layout to the actual tree as a gap table (§3).
4. Assigns the open work to a multi-agent squad structure with ownership gates (§4).
5. Defines the staged working plan, RED-test requirements and exit criteria (§5–§6).

**Status of this document:** analysis + plan only. It authorizes no live-broker behavior
change. `ARCHITECTURAL` and `QUANT-DESIGN` decisions are escalated per §4.3.

---

## 1. Verification method

| Property | Value |
|---|---|
| Method | Static read of HEAD for every finding named file + targeted `agentic_code_search` for the claimed construct |
| Guard-rail baseline (this session) | `pytest tests/architecture tests/quant/execution tests/quant/chaos` → **365 passed, 1 skipped, 13.42s** |
| Repo baseline file | `docs/architecture/baselines/2026-09-11-approved-refactor-baseline.txt` → `341 passed` at `8af8542a` |
| Kanban digest | `.kanban/CONTEXT.md` — last full pytest run: **49 failing** (11 pre-existing domain/integration failures + symbol-registry/timesfm/break tests) |
| Digest re-check (this session) | Every failing subset named in the digest — `backend/tests/unit/domain`, `tests/quant/amt/market/test_break.py`, `tests/quant/amt/session/test_scanner_timesfm.py`, `tests/quant/amt/session/test_symbol_registry.py` — now passes: **405 passed, 13 skipped, 9.57s**. The digest is **stale**; only the live-network Dhan integration tests in `brokers/broker/dhan/tests/test_integration.py` remain unverified (they require credentials). |
| Full-suite runtime | Exceeds 10 minutes; the plan must add a split shard policy before it relies on a full-suite gate (Squad H task H-0). |
| Knowledge graph | 15,223 nodes · 34,414 edges · 560 communities (stale since 2026-09-11T06:48Z) |

Verdict vocabulary used below:

- **CLOSED** — verified fixed at HEAD, with a test guarding it.
- **PARTIAL** — mechanism exists but does not satisfy the v6.0 acceptance criterion.
- **OPEN** — verified absent/unchanged at HEAD.
- **REFUTED** — claim is false against HEAD.
- **UNVERIFIED** — evidence insufficient in this pass; assigned to a squad task, not to a phase.

---

## 2. Findings reconciliation — the 20 ranked risks

### 2.1 P0 findings

| ID | Review finding | Verdict | Evidence at HEAD | Gap that remains |
|---|---|---|---|---|
| P0-1 | Naked position exposure — no broker-native contingent stop | **OPEN** | `quant/execution/live_oms.py` `submit()` submits entry then returns; `close()`/`close_partial()` are the only exits. No `SL-M`/trigger-price call exists in `quant/` (search for `sl_m`, `trigger_price`, `place_stop` → 0 hits). Pyramids deliberately disabled with an explicitly documented ghost-position rationale at `live_oms.py` `add_pyramid` (`E9`). | Two-phase atomic commit (entry → native SL-M), stop-order id recorded on `PositionOpened`, panic-flatten route on phase-2 failure, `EmergencyFlatten` event. |
| P0-2 | Fail-open persistence resets `SessionRisk` to zero | **REFUTED at HEAD** | `quant/execution/risk.py:27-39` defines `RiskLoadStatus`; `_load()` classifies `STORAGE_ERROR` (`:140`) and `CORRUPT` (`:161`) instead of silently resetting; `can_trade()` blocks entries on both (`:282-284`). Guarded by `tests/quant/execution/test_risk_load_status.py`. | Promote the per-session block to a **readiness** signal surfaced in the WS snapshot + `/v1/metrics`; confirm the coordinator can't construct an engine whose risk loaded degraded. |
| P0-3 | Commercial-license + hot-path use of TimesFM 3.0 | **OPEN** | `quant/decision/timesfm_engine.py`, `quant/decision/timesfm_agents.py`, `quant/strategies/timesfm_strategy.py` all live. `start.sh:41` defaults `TIMESFM_END_TO_END=true`, so the **model-authoritative entry path is the paper default**; the canonical 4-gate `GatePipeline` is bypassed on that path (`docs/reviews/2026-09-10-audit-appendices/audit-sizing-context.md`). | Licensing decision (§4.3 D-1), sidecar relocation, and a fitness test asserting no model import in the deterministic entry path. |
| P0-4 | Futures→options 1:1 scale distortion (no Greek Δ translation) | **OPEN** | `quant/contracts/` has **no** `options_converter.py`. `option_delta` exists only as a `DecisionContext` field whose Greek branch is unreachable (`audit-sizing-context.md` B.1). | `OptionConverter` (Δ-scaled stop/target), Gate-4 R:R computed in premium space, tick-floor `2τ_opt` clamp. |
| P0-5 | Directionless `AggressionScorer` → sell climax can approve a Long | **OPEN** | `quant/amt/orderflow/aggression.py` — `AggressionScorer.score()` and `PersistentAggressionScorer.score()` accept only component booleans; **no `direction` parameter**. Components are purely additive, capped at 4.5. Independently flagged by the repo's own reviews (`docs/reviews/2026-09-07-deep-production-readiness-review.md` §P1-12). | Sign-alignment gate; zero bullish components when `direction == "SHORT"`; RED test proving a negative-delta climax cannot score ≥ `MIN_AGGRESSION_SCORE` for a Long. |
| P0-6 | Split sizing authority (scanner / strategy / OMS all size) | **OPEN** | `quant/decision/timesfm_agents.py` `_dynamic_sizing` (~`:492`) produces `dynamicSizing`; `SessionRisk.position_size()` sizes independently; `LiveOMS.submit()` snaps to lot a third time via `snap_to_lot` (`live_oms.py`). `quant/execution/ports.py` `IOMS.submit` documents quantity as an *input*, not an authority. | Single `SessionRiskAuthority`; scanner reduced to ranking only; one lot-snap point; fitness test forbidding a second sizing path. |
| P0-7 | `SignalApproved` emitted before broker acknowledgement | **REFUTED at HEAD** | `quant/runtime.py:1346-1348` emits `SignalApproved` **after** a successful `self._oms.submit()`; the failure branch (`:1293-1312`) latches a block and unwinds the portfolio reservation. Guarded by `tests/quant/runtime/test_signal_approval_truthful.py` and `test_signal_blocked_latch.py`. | Rename the event to `OrderAcknowledged` (or add it) so "approved" no longer conflates *gates passed* with *venue accepted*. |
| P0-8 | Synchronous hot-path contention on a shared model | **OPEN (worse than reported)** | `quant/decision/timesfm_engine.py` exports a module-level `_TIMESFM_INFER_LOCK` shared across engines — inference is globally serialized, not merely contended. `quant/strategies/timesfm_strategy.py:31` imports the same lock. | Remove the model from the decision path entirely (§5 Phase 2); no lock in any decision module afterwards. |
| P0-9 | Silent tick drops distort profile/VWAP | **UNVERIFIED** | `quant/brokers/multiplexed_feed.py` routes per-symbol `queue.Queue`s with documented benign-baseline drops and a `_cum_to_delta` volume cap. The review's specific claim (`Queue(maxsize=1000)` + `put_nowait` → silent drop) was **not** confirmed in this pass. | Squad F task F-1: instrument and quantify; replace with a pre-allocated ring buffer + `ticks_dropped` counter in the snapshot. |
| P0-10 | REST timeout misclassified as `REJECTED` → orphan position | **PARTIAL** | `quant/execution/execution_state_machine.py` (53 lines) and `quant/contracts/execution_vocabulary.py` exist with an explicit `UNKNOWN` state; the paper path is covered (`tests/quant/execution/test_execution_state_machine.py`). Live timeout handling in `backend/app/infrastructure/adapters/dhan_broker_adapter.py` remains to be proven. | Post-timeout order-status reconciliation loop; `UNKNOWN → RECONCILIATION_REQUIRED` asserted for the live adapter, not just paper. |

### 2.2 P1 / P2 findings

| ID | Review finding | Verdict | Evidence at HEAD | Gap |
|---|---|---|---|---|
| P1-11 | Aggressor side inferred from tick price direction | **OPEN (confirmed)** | `quant/brokers/multiplexed_feed.py` `_attr_delta` / `_convert` deliberately attribute traded volume by up-tick/down-tick price direction, with an in-code comment explaining Dhan's feed carries no aggressor flag. | Multi-level OFI + spread confirmation; provenance must stay `INFERRED`, never upgraded (`quant/execution/flow_provenance.py` exists — extend it to this site). |
| P1-12 | Unauthenticated WebSocket control surface | **OPEN** | `backend/app/api/websocket/gameloop.py:113` `@router.websocket("/ws/gameloop")` — no dependency, no token check. `backend/app/main.py` installs only a `WebSocketLogMiddleware` on that path (`:176-186`), which logs and forwards. | `backend/app/api/websocket/auth.py` JWT validation; reject unauthenticated upgrade; contract test asserting 4401/close on bad token. |
| P1-13 | EOD watchdog can die silently | **PARTIAL** | `quant/multi_engine.py` `_eod_watchdog_loop` (`:1153`), `eod_square_off` (`:1020`) and per-engine `logger.exception` on failure (`:1054`) exist. Thread-death supervision/alerting is not evident. | Supervise the thread (restart + `readiness=DEGRADED` on death); assert a position remaining at close raises an operator alert. |
| P1-14 | Secrets leak into logs | **OPEN / path claim wrong** | No `redact`/`mask`/`scrub` helper exists in `backend/` (search → 0 hits outside docs). The review's path `backend/app/logging_config.py` **does not exist**; the real module is `brokers/broker/logging/logging_config.py`. | Redaction filter on the logging formatter + a test that serializes config/exceptions/journal/WS frames and proves tokens never appear. |
| P1-15 | Monotonic stop violation race (bar vs tick paths) | **CLOSED** | `quant/execution/protective_stop.py` — frozen `ProtectiveStopState.tighten()` **rejects widening** for both sides; `resolve_protective_stop()` resolves a single effective stop for bar and tick paths. | Route **every** stop write (including live broker amend) through `tighten()`; add an invariant test on the live amend call. |
| P1-16 | Wall-clock bar aggregation drift | **CLOSED** | `quant/aggregator.py` — `_window()` floors off the tick epoch (`epoch // interval_seconds`), late windows (`window < _open_key`) are **dropped, not merged**, and synthetic fixture ids are protected by the `_EPOCH_2000` guard. | Extend the same anchor to the WS/history-merge path and record the exchange timestamp in `BarClosed`. |
| P1-17 | Single WebSocket ingestion point | **OPEN** | One `MultiplexedMarketFeed` over one Dhan socket (`quant/brokers/multiplexed_feed.py` module docstring: "ONE `stream_full(all_symbols)` call"). | Strategic (§5 Phase 4): dual feed with dedup + failover. |
| P1-18 | GC latency spikes from hot-path allocation | **OPEN** | `quant/runtime.py` tick/bar path constructs dataclasses per update (`quant/aggregator.py` `_accumulate` builds a new `Bar` per tick). | Allocation budget + profiling gate; measure before optimizing. |
| P2-19 | UI thread frame drops in `ChartScene.tsx` | **UNVERIFIED** | Frontend review not performed in this pass. | Squad G task G-3: profile render path, decouple full-canvas redraw from tick cadence. |
| P2-20 | Portfolio leverage cap unenforced when uninitialized | **PARTIAL** | `quant/execution/portfolio_risk.py` exists and is wired (`tests/quant/test_portfolio_risk_guard.py`, `test_stress_and_portfolio_risk.py`); hard-ceiling behavior on an uninitialized config is not proven. | Fail-closed default cap; test that a missing config refuses entries rather than deploying. |

### 2.3 v6.0 target claims that the review got wrong

| Claim | Reality at HEAD |
|---|---|
| "God class `runtime.py` is 1,595 LOC" | **1,978 LOC** — debt grew |
| "God class `multi_engine.py` is 1,528 LOC" | **1,912 LOC** — debt grew |
| "`amt/analyzer.py` is 1,066 LOC" | **1,102 LOC** |
| "Chaos tests: **0%** / completely missing" | **REFUTED** — `tests/quant/chaos/test_crash_recovery.py`, plus `tests/quant/edge_cases`, `tests/quant/certification`, `tests/quant/replay`, `tests/quant/determinism` |
| "Fail-open persistence" | **REFUTED** at HEAD (see P0-2) |
| "`SignalApproved` before broker ack" | **REFUTED** at HEAD (see P0-7) |
| "No architecture fitness tests" | **REFUTED** — `tests/architecture/` has 8 suites (layer bypass, boundaries, silent-except, dead exports, drifting literals, repo hygiene, fitness, WS contract drift), all green in the 365-pass baseline |
| "Order timeouts default to `REJECTED`" | Partially superseded — a canonical execution state machine with `UNKNOWN` already exists for paper |

**Consequence:** four of the ten P0 rows are already closed. The plan below spends effort only on
verified-open work, and its first act is to freeze the true LOC/behaviour baseline so the next
review is measured against facts.

### 2.4 Verified work queue (what actually gets scheduled)

**P0 (money path)** — P0-1, P0-3, P0-4, P0-5, P0-6, P0-8, P0-10
**P0 (verify-only)** — P0-2 (promote to readiness), P0-9 (quantify first)
**P1** — P1-11, P1-12, P1-13, P1-14, P1-17, P1-18
**P2** — P2-19, P2-20

---

## 3. v6.0 target layout vs. the actual tree

Legend: `✔` exists at or near the target path · `Δ` exists but needs to move/rename · `✘` missing.

```
v5-of-glassytrade-ai/
├── backend/app/
│   ├── api/dependencies.py                          ✔ backend/app/api/dependencies.py
│   ├── api/routers/                                 ✔
│   ├── api/websocket/auth.py                        ✘  <-- P1-12 (NEW)
│   ├── api/websocket/gameloop.py                    ✔ (404 LOC; auth missing)
│   ├── infrastructure/adapters/dhan_broker_adapter.py ✔
│   ├── infrastructure/adapters/dhan_market_data.py  ✘  (today: dhan_adapter.py + dhan_order_feed.py)
│   ├── infrastructure/storage/sqlite_storage.py     ✘  (today: quant/persistence*.py, quant/event_store.py)
│   └── main.py                                      ✔
├── brokers/dhan/                                    ✔ brokers/broker/dhan/ (deeper than target)
├── quant/
│   ├── amt/orderflow/{aggression,cvd,detectors}.py  ✔ + footprint.py, aggressive_prints.py, drive.py
│   ├── amt/profile/, amt/session/                   ✔
│   ├── amt/analyzer.py                              ✔ 1,102 LOC (decompose)
│   ├── contracts/exchange_config.py                 ✔
│   ├── contracts/options_converter.py               ✘  <-- P0-4 (NEW)
│   ├── contracts/value_objects.py                   ✔
│   ├── decision/gates/gate_*.py                     Δ  today flat: gates_edge.py, gates_rr.py,
│                                                         gates_session_position.py
│   ├── decision/pipeline.py                         ✔ (38 LOC; thin)
│   ├── decision/signal_builder.py                   ✔
│   ├── execution/{exits,live_oms,lots,portfolio_risk,
│   │              ports,protective_stop,risk}.py    ✔ all present
│   ├── sidecars/narrative/                          ✘  today: quant/llm/advisor.py, decision/timesfm_advisor.py
│   ├── sidecars/volatility/                         ✘  (NEW)
│   ├── event_store.py, events.py                    ✔
│   ├── multi_engine.py, runtime.py                  ✔ (1,912 / 1,978 LOC — decompose)
│   ├── state_machine.py                             ✔
│   └── transition.py                                Δ  today: transitions.py
└── tests/{architecture,chaos,determinism,quant}/    Δ  chaos/determinism live under tests/quant/
```

**Extra top-level `quant/` modules with no v6.0 home** (target either relocates or retires):
`amt_engine.py`, `persistence.py`, `persistence_bridge.py`, `persistence_boundary.py`,
`reconciliation_service.py`, `aggregator.py`, `bars.py`, `position_manager.py`,
`session_gates.py`, `session_levels.py`, `strategy.py`, `coordinator_view.py`, `ws_adapter.py`,
`ws_contract.py`, `hotpath.py`, `state.py`, `wiring_advisor.py`, `triple_a.py`-style siblings.
**Squad E owns the disposition decision for each — no orphan directory moves without a stated owner.**

---

## 4. Multi-agent team plan

### 4.1 Squad roster

Eight squads. Each has one accountable owner role (per the council model), a fixed file
allowlist, and an independent reviewer from the Review division. A squad may not edit outside
its allowlist without escalation.

| Squad | Mission | Owner role | Review division | Finding IDs |
|---|---|---|---|---|
| **S0 · Baseline & Governance** | Freeze the truthful baseline; hold the invariants | Chief Quant Architect | Architecture Review Board | — |
| **A · Money Path & OMS** | Atomic entry + native stop + panic flatten | Head of Trading Systems | OMS & Execution | P0-1, P0-6, P0-10, P1-15 |
| **B · Risk & Persistence Authority** | One sizing authority; fail-closed, readiness-surfaced | Platform Engineering Director | Domain Engineering | P0-2, P0-6(risk half), P2-20 |
| **C · Determinism & Decision Integrity** | Signed flow, Δ translation, truthful provenance | Quant Research Director | Quantitative Research | P0-4, P0-5, P1-11, P1-16 |
| **D · AI Decoupling & Sidecars** | Model out of the hot path; license resolved | Chief Quant Architect | Architecture Review Board | P0-3, P0-8 |
| **E · Runtime Decomposition** | God-class strangler; DDD layout convergence | Chief Quant Architect | Architecture Review Board | P0-3(structural), §3 layout |
| **F · Feed & Latency** | No silent drops; measured latency budget | Platform Engineering Director | Performance | P0-9, P1-17, P1-18 |
| **G · Transport Security & Delivery** | Authenticated, redacted, smooth transport | Security (specialist) | Architecture Review Board | P1-12, P1-13, P1-14, P2-19 |
| **H · Certification Battery** | Chaos, determinism, acceptance vectors, release gate | QA/Test Automation Architect | Product Validation Council | all — closes each phase |

**Escalation to the Executive Council (blocking, decide before Phase 2):**

- **D-1 — TimesFM license.** Keep, replace with an Apache-2.0 model (e.g. Chronos), or delete the
  model path entirely? Gates P0-3 and all of Squad D.
- **D-2 — Native-stop scope.** Which Dhan order type (`SL-M` vs `SL-L`) is the contingent stop,
  and what is the operator-approved panic-flatten policy when phase 2 fails?
- **D-3 — Live readiness definition.** Restate that live remains **NO-GO** throughout; the
  existing spec's invariants 1–3 are re-affirmed unchanged by this plan.

### 4.2 Squad working agreement

1. One workstream per change set — no bundled cleanup (`§8` of the design spec).
2. **RED test first** for every behaviour change; the test must fail on the unpatched tree.
3. Every change identifies whether it moves **paper readiness**, **live readiness**, or neither.
4. Architecture fitness tests are amended in the same change that would otherwise violate them.
5. A squad's work is not "done" until Squad H's focused + replay suites pass and the readiness
   report is regenerated.
6. No squad may touch `brokers/broker/dhan/infrastructure/symbol_mapper.py` (pre-existing user
   changes are frozen by invariant 4).

### 4.3 Squad detail cards

**S0 · Baseline & Governance** — *runs concurrently, never ends*
- Deliverables: true LOC/complexity table for the 6 worst modules; refreshed graph snapshot
  (`/graphify update`); a findings ledger with the §2 verdicts as the canonical status board;
  invariant fitness tests re-run as the merge gate.
- Exit: baseline committed; the 49 pre-existing test failures triaged into
  `pre-existing | caused-by-this-branch | flaky`, with an owner per bucket.
- **Status:** partially done. All failing subsets named by the digest now pass at HEAD
  (405 passed / 13 skipped). Remaining: rerun the live-network Dhan integration suite
  (`brokers/broker/dhan/tests/test_integration.py`, credential-gated) and add a sharded
  full-suite runner (H-0) since the monolithic run exceeds 10 minutes.

**A · Money Path & OMS** — *Phase 1*
- Entry: approval from D-2.
- Work: extend `quant/execution/ports.py` with stop placement; two-phase commit in
  `live_oms.py`; record the stop order id on the position and in `PositionOpened`; panic-flatten
  route emitting `EmergencyFlatten` + `is_halted`; Route every stop write through
  `ProtectiveStopState.tighten()`.
- Exit: broker double (paper + fault-injecting fake) proves entry→stop→fill atomically; phase-2
  failure flattens and halts within one bar; no code path can open a live position without a
  recorded native stop.

**B · Risk & Persistence Authority** — *Phase 1*
- Work: extract `SessionRiskAuthority` as the sole sizing/lot-snap authority; strip
  `dynamicSizing`/VaR-stop from the scanner to ranking only; surface `RiskLoadStatus` in the WS
  snapshot and readiness; hard fail-closed portfolio cap default.
- Exit: redeploy the architecture fitness test that forbids a second sizing path (the design
  spec's ratchet list already names "one sizing and lot-snapping authority"); parameterized
  lot-snap vectors across active NSE/MCX contracts pass.

**C · Determinism & Decision Integrity** — *Phase 1 → 2*
- Work: `direction` parameter on `AggressionScorer` (zero opposing components); signed CVD
  confirmation; `OptionConverter` with Δ-scaled stops and `2τ_opt` floor; provenance tagging on
  the inferred-flow site so it can never be relabelled exact.
- Exit: adversarial vectors prove a negative-delta climax cannot approve a Long; a
  15-point futures invalidation maps to the expected premium stop for Δ ∈ {0.3, 0.5, 0.7};
  Gate 4 rejects < 1.5 in premium space.

**D · AI Decoupling & Sidecars** — *Phase 2, blocked on D-1*
- Work: remove model calls from `runtime.py` / `exits.py` decision path; create
  `quant/sidecars/narrative/` (post-trade journal) and `quant/sidecars/volatility/` (15-minute
  `Q_spread` regime flag writing only `macro_risk_cap`); the sidecar has **no order port**.
- Exit: AST fitness test asserts zero model imports in the deterministic entry path; killing the
  sidecar threads mid-session changes no decision, no order, no stop.

**E · Runtime Decomposition** — *Phase 3*
- Work: strangler facade over `QuantEngine` delegating one responsibility at a time
  (`MarketIngestion` → `Analysis` → `Decision` → `Execution` → `PositionLifecycle` →
  `StateProjection`); reduce `QuantCoordinator` to scheduling/ownership/readiness; converge the
  §3 layout.
- Exit: per-responsibility units tested in isolation; replay parity (identical event hash)
  before/after each delegation; `runtime.py` and `multi_engine.py` each under an agreed cap.

**F · Feed & Latency** — *Phase 3*
- Work: F-1 quantify the drop path before changing it; ring buffer + `ticks_dropped` metric;
  latency budget per hot-path stage; allocation/GC profiling.
- Exit: a declared and measured drop policy (no silent loss); GC pause budget asserted under a
  synthetic burst.

**G · Transport Security & Delivery** — *Phase 3*
- Work: JWT middleware for the gameloop + `symbol_switched`/control messages; log redaction;
  EOD thread supervision with operator alert; frontend render decoupling (after snapshot
  contracts are versioned).
- Exit: unauthenticated upgrade rejected by test; a secret-scanning test proves tokens never
  appear in serialized logs; EOD thread death raises `readiness=DEGRADED`.

**H · Certification Battery** — *every phase, owns the release gate*
- Work: extend chaos injection to phase-2 stop placement and broker drops; 1,000-run
  bit-for-bit replay; NSE/MCX acceptance vectors; paper shadow + readiness report.
- Exit: the seven release gates from the design spec §6 all pass; the readiness report states
  live = NO-GO explicitly.

---

## 5. Staged working plan

Sequencing follows the design spec §7 (Stage 0 → 6) with the review's Phase 1–4 urgency
reconciled against verified facts. Every phase is gated by Squad H.

### Phase 1 — Money path & single authority (Days 1–3)

| # | Task | Squad | Primary files | RED test |
|---|---|---|---|---|
| 1.1 | Confirm D-2 (native stop type + flatten policy) | Council | — | — |
| 1.2 | `IBrokerPort` stop placement contract | A | `quant/execution/ports.py`, `quant/contracts/ports/broker.py` | port-conformance test |
| 1.3 | Two-phase atomic entry + stop in `LiveOMS` | A | `quant/execution/live_oms.py` | fault-injecting broker double: stop rejection → flatten + halt |
| 1.4 | Record stop order id on position + `PositionOpened` | A | `live_oms.py`, `quant/events.py`, `quant/transitions.py` | event/state round-trip |
| 1.5 | Extract `SessionRiskAuthority`; scanner → ranking only | B | `quant/execution/risk.py`, `quant/decision/timesfm_agents.py` | fitness: exactly one sizing path |
| 1.6 | Direction-aware aggression + signed CVD | C | `quant/amt/orderflow/aggression.py`, `quant/decision/gates_edge.py` | bearish climax cannot approve a Long |
| 1.7 | Fail-closed portfolio cap + degraded readiness surfaced | B | `quant/execution/portfolio_risk.py`, `quant/execution/readiness.py` | uninitialized config refuses entries |

**Phase-1 gate:** paper suite green, architecture suite green, no change to live readiness
(still NO-GO), and the two quick-est security items (P1-14 redaction, P1-12 WS auth) are pulled
forward here because they are days of work and end a documented breach class — Squad G runs them
in parallel with A/B/C.

### Phase 2 — AI decoupling & derivatives scaling (Weeks 1–2)

- 2.1 Council decision D-1 (TimesFM licensing) — **blocking**.
- 2.2 Remove model calls from `runtime.py` / `exits.py`; Gate 3 becomes the sole entry authority.
- 2.3 `quant/contracts/options_converter.py` with Δ-scaled stops/targets + Gate-4 premium R:R.
- 2.4 `quant/sidecars/narrative/` (post-trade only, no order port).
- 2.5 `quant/sidecars/volatility/` with `Q_spread` → `macro_risk_cap` only.
- 2.6 1-minute full-body close acceptance rule in Gate 3.

**Gate:** AST test proves zero model imports in the decision path; Δ-vector battery passes;
sidecar kill-switch test passes.

### Phase 3 — Decomposition, feed, transport (Weeks 3–4)

- 3.1 Runtime strangler (one responsibility per change, replay parity each time).
- 3.2 `QuantCoordinator` reduction + immutable snapshots; transport loses internal access.
- 3.3 Feed drop policy + ring buffer + latency/allocation budgets.
- 3.4 Post-timeout broker reconciliation loop (`UNKNOWN → RECONCILIATION_REQUIRED → RECONCILED`).
- 3.5 JWT WS auth + log redaction + EOD supervision (if not already closed in Phase 1).

### Phase 4 — Deterministic certification & canary (Weeks 5–8)

- 4.1 1,000-run bit-for-bit replay on a recorded tape.
- 4.2 Chaos battery: broker drop during phase-2 stop, half-open socket, DB stall, out-of-order ticks.
- 4.3 NSE/MCX acceptance vectors (lot, tick, freeze, expiry, session, square-off windows).
- 4.4 Two-week paper shadow on target contracts.
- 4.5 One-lot canary — **only** on explicit council sign-off, and only after the readiness report
  clears every gate in design spec §6.

---

## 6. Definition of done & rollback

A stage is complete only when it ships: design contract → RED tests → implementation → focused
tests → architecture fitness tests → replay/determinism evidence → migration note → rollback
plan, and states whether it changed paper readiness, live readiness, or neither.

Rollback for anything touching the money path is the paper/live flag plus the last green
baseline hash recorded in `docs/architecture/baselines/`.

---

## 7. Immediate next actions

1. **S0-1** — Freeze the truthful baseline: commit the §2 verdict table as the findings ledger
   and refresh the graph snapshot (currently stale).
2. **S0-2** — Triage the remaining unverified suites (live-network Dhan integration,
   sharded full run) after the digest-named failures were confirmed green.
3. **D-1 / D-2** — Put both blocking decisions to the council; Squad D and A cannot start
   implementation without them.
4. **G-1 / G-2** — Independently of the council, add WS JWT auth and log redaction (small,
   self-contained, closes a live breach class).
5. **C-1** — Add the `direction` parameter to `AggressionScorer` with RED tests (highest
   correctness leverage per line changed).
6. **F-1** — Quantify the tick-drop path before anyone rewrites the feed.

*This document authorizes analysis and planning only. No live broker execution behavior is
approved by it.*
