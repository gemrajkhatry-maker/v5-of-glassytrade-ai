# Pre-Deployment System Review — glassytrade-ai

**Date:** 2026-09-23 · **Role:** Principal Engineer / Release Manager · **Mode:** multi-agent (4 Explore agents: module-map+elimination, E2E flow trace, shotgun+SSoT, integrations+readiness)
**Tree:** working tree has uncommitted Fixes A/B/C (`composition_root`, `gateway`, `multiplexed_feed`, `runtime` + tests) — review baseline is a moving target.
**Constraint applied:** already failed once in production · conservative · deletion preferred over refactoring · no “keep just in case”.

---

## 1. System Intent

Glassytrade-ai is a multi-symbol paper/live scalping engine: a single Dhan WebSocket feeds per-symbol engines that fold ticks into bars, run a deterministic AMT analysis (profile, orderflow, session, Triple-A), evaluate a four-gate decision pipeline plus signal builder, and submit through an IOMS seam (PaperOMS/LiveOMS) with event-journalled persistence, portfolio-risk ceilings, and a FastAPI/WS shell for health, scan, journal, and a read-only gameloop — with LLM/TimesFM/Laya strictly advisory and never gating.

---

## 2. Active Execution Paths

### Path A — Tick → Decision → Order (money-path)

```
Dhan WS binary → streaming_service FullPacket → dhan_adapter asdict →
MultiplexedMarketFeed._route/_convert (source-tagged LTT, 30s grace) →
per-symbol queue(4096) → LiveGateway → QuantEngine._run_inner →
TickHandler → BarAggregator → AMTEngine.analyze → DTO+Snapshot →
[bar closed] → DecisionLoop._entry_guards → DecisionContextBuilder.build →
AmtScalpingStrategy.should_enter → DecisionService.evaluate →
GatePipeline(g1 session, g2 cooldown, g3 edge, g4 RR) → SignalBuilder / VA-fade →
SubmissionHandler.submit → IOMS.submit → PaperOMS|LiveOMS →
EventStore.append → fold → EventBus → Journal + SQLite bridge
```

**Hop integrity:** engine-thread crash = fail-stop (`_crashed`, visible). Gate exceptions swallowed into `GateResult("error:…")`. AMT failure → first log then **forever-stale DTO, zero signal**. Stale-DTO decision deferral → **zero log/event**. Feed drop-oldest uncounted; drop warnings rate-limited 30s; `silent_symbols`/`_drop_counts` **tests-only, not on /health**.

### Path B — Exit

```
bar/tick/thesis-flip/EOD → ExitManager (close lock) → PositionManager.manage_exit →
ExitEngine.evaluate → oms.close/close_partial → PositionClosed event →
fold clears state.position + pm.current_position → risk release
```

**Dual authority:** `engine.state.position` (fold) vs `pm.current_position` (execution book) — three `_build_context` wrappers read them differently (`decision_loop` bare pm; `exit_manager`/`runtime` `pm or state`). Mid-sweep pyramid-close failure window after base close. Duplicate `close_lingering_pyramids` (runtime copy = test-only).

### Path C — Health

`/health`: DB probe, journal failures, crashed/stale engines → `ok|degraded|unhealthy` (only DB/string-error → unhealthy; **all engines dead = “degraded”**). `/health/ready`: readiness, startup contracts, reconciliation. **Neither sees feed silence, drop counts, WS health snapshot, or poll-fallback mode.**

### Classification (STEP 1)

- **Actively used:** quant decision/execution/amt/runtime/multi_engine, engine/*, brokers mux feed, contracts registry, backend routers (all 8 registered), composition_root, storage, mode.py, scripts pre-release.
- **Conditionally used:** timesfm/llm/laya advisors (flags default off), dhan_* adapters (live), paper_broker (paper), automation CLI (manual, not CI), testing router (dev), feature schema (health display).
- **Never used (production):** see §3.

---

## 3. Dead / Duplicate / Legacy Code — DELETE list

### DELETE (zero production callers / no-op — safe now)

| # | Target | Evidence | Breaks if deleted |
|---|--------|----------|-------------------|
| D1 | `quant/decision/data_quality.py` `conviction_allowed` + `_ALLOWED_CONVICTION` | 0 callers; test asserts absence | nothing |
| D2 | `quant/runtime.py:189-283` `close_lingering_pyramids` (dup) | prod uses `exit_manager:43`; 6 test imports | retarget 6 imports |
| D3 | `container.py` `register()` non-singleton | 0 callers; resolve() caches anyway | docstring only |
| D4 | `analyzer.py:686-706` dead `flow["…"]` no-ops (+ `:693` shadowed) | 12 statements, result discarded | nothing |
| D5 | `quant/contracts/options_converter.py` (whole file) | 0 importers | nothing |
| D6 | `backend/.../storage/sqlite_storage.py` (whole file) | 0 importers | nothing |
| D7 | `quant/execution/coordinator_metrics.py` (+ test) | 0 prod; docstring lies | 1 test file |
| D8 | `quant/execution/execution_state_machine.py` + `execution_vocabulary.py` (+ 3 tests) | 0 prod; only arch test keeps them | wire-or-delete decision |
| D9 | `selector.compute_lot_size` / `compute_option_lot_size` | 0 / test-only prod | 4 tests rehome to SessionRisk |
| D10 | `shared/resilience` `PerEntityCircuitBreaker`, `get_position_circuit`, write-dead globals | 0 users / never recorded | drop from /metrics or wire |
| D11 | DI `Configuration` binding, `MarketDataDep`/`ActiveSymbolsDep`, `app.state.graph/service_graph` | 0 resolvers/readers | 1 vestigial test line |
| D12 | `settings_adapter.py:55` no-op Path expr; `GapFillConfig`; `short_signals_enabled` flag (0 consumers) | dead config | yaml+dataclass |
| D13 | `detect_gap_fill_fade` + `test_gap_fill_fade.py` + `ctx.gap_profile_*` (0 readers) | wire-or-drop deferred in plan | frontend DTO keys stay |
| D14 | `ExitEngine.evaluate` `timesfm_forecast` param + 2 pass-throughs | never read; policy says never gates | 2 call sites |
| D15 | 15-min bias aggregators `runtime:443-452` | constructed, never fed/read | 2 lines |
| D16 | Tracked artifacts: `gap_architecture.workflow.html` (718KB), `automation/reports/monitor_report_*.json` | git-tracked junk | extend hygiene prefixes |
| D17 | `lvn.py` `keep_highest` param (ignored) + stale test | body always `max()`; 1 red test today | fixes red suite |
| D18 | Alias DTO keys `departedAndReapproached`, `driveDepartedAndReapproached` (keep `driveEntryValid` + `isSecondDrive` semantics clarified) | 4 aliases of 1 bool | 2 or-chain readers |
| D19 | `MCX_SUB_SESSIONS` second MCX table (`context.py:581-587`) vs phase table | contradicts same file | reconcile first |
| D20 | `brokers/broker/market_info.is_market_open` NSE-only clock + independent `LOT_SIZES`/`STEP_SIZES` extras | wrong for MCX; registry exists | delegate to registry |

### MERGE (duplicate implementations — one owner each)

| Concept | Copies | Keep | Delete / fold |
|---------|--------|------|----------------|
| Pyramid flatten | `exit_manager:43` + `runtime:189` | exit_manager | runtime copy |
| Session clock | **8 reps** (gate_session_phase, timezones, phase table, MCX_SUB_SESSIONS, symbol_registry, market_info, instruments.json, features) | `timezones` + phase table | gate hardcoded clock; market_info own hours; features literals; json session_* |
| Instrument/lot/tick | json vs `_SPECS` vs YAML vs market_info tables vs selector fallbacks | `instrument_registry._SPECS` | json lot/tick/strike (**GOLD/GOLDM currently swapped**); market_info step tables; selector fallbacks |
| DecisionContext build | 3× `_build_context` + 8× builder call sites | `DecisionContextBuilder` + 1 wrapper | other 2 wrappers |
| Credentials | 2× `.env`, 6 loaders, 3 or-chain readers | one credential resolver + one `.env` | duplicate chains |
| Risk halt | decision_loop guard vs DecisionService | guard 0 (`can_trade`) | service branch or share helper |
| Cooldown | guard vs Gate 2 vs exit_manager (5 bars vs 15 min) | one helper + one unit | dead Gate-2-on-entry path / exit_manager copy |
| Stop-cap constants | gates_rr vs decision_service inline | gates_rr helper | inline copy |
| MIN_STOP_DISTANCE | stops vs signal_builder | stops | signal_builder copy |
| `_as_counter` | ×3 | one util | 2 copies + repoint tests |
| `to_decimal` | shared/money vs dhan_broker_adapter | shared/money | adapter copy |
| Drive departure | drive state + 4 DTO aliases + setup_state + or-chain readers | `DriveState` states serialized once | aliases + synthesized `departed=True` |
| SECOND_DRIVE class | reversion (gate1/gates_edge/broker_mapper) vs **trend** (model_router) | **owner decision required** | contradictory classification |
| Exit reason vocab | IOMS docstring vs free strings vs ExitReason enum vs normalizer | `ExitReason` + from_wire() | free strings at boundary |
| Paper fill/PnL | 3 formulas + 3 default-cost tables | factory-forced cost profile | direct `PaperOMS()` legality in prod path already OK; align formulas |
| Dual position authority | state vs pm vs DB vs broker | **pm = execution, state = derived** (per dual-authority doc — not yet landed) | unify `_build_context` position source |
| VWAP keys | `sessionVwap` + `vwap` | one | or-chain |
| `dev_va` orphan | computed, never published | consumer or delete | analyzer-only today |

### KEEP (load-bearing despite looking dead)

- `TradingStrategy` (boot import) + `build_strategy` (**actively used** at `runtime:567` — do not delete).
- Architecture test suite (sole enforcement of several ratchets).
- `quant/ws_contract.py` (test contract for WS schema).
- Layered Position/Signal families + named crossings (ADR-0001).
- Metrics split (ADR-0003) — but ADR-0003’s `MetricsCollector` file is **gone**; ADR is stale.
- Quarantine-default StartupReconciliation.
- Advisor never-gates invariant (code-verified).
- OMS conformance suite, feed late-tick regression tests.

---

## 4. Shotgun Surgery Findings

| Change | Files that move together | Root cause | Single authoritative owner |
|--------|--------------------------|------------|----------------------------|
| Add/edit a gate | pipeline, result.GATE_NAMES, decision_service (`==3`, `in (1,2)`), result_factory, signal_builder “4 gates”, 4 gate files, ~10 tests, frontend, docs | `GateResult.gate: int` leaks identity into control flow | **Gate identity enum/name**; pipeline holds named gates |
| Session boundary | gate_session_phase, timezones, context (×2 tables), symbol_registry, market_info, json, YAML+RULE-13, features, session_gates cutoffs, exit_rules TIME_STOP_TABLE | 8 hand-rolled clocks | **SessionClock** (`timezones` + phase table) |
| Lot/tick/instrument | json, `_SPECS`, YAML, market_info tables, selector, multi_engine, dhan tables, parity tests | 3 authored tables, only 2 reconciled | **InstrumentRegistry** (RULE-13 extended to json) |
| DecisionContext field | context.py, kwargs map, 3 wrappers, 8 build sites, ~40 getattr readers, ~40 test literals | flat god-object + getattr defaults | **ContextSource** (one builder, typed groups) |
| Credentials | 2 env files, 6 loaders, 3 readers, auth write-back | ambient env, divergent precedence | **one Credentials object** |
| Paper/live mode | mode.py, YAML broker_mode, composition_root (is_live + broker_mode fallback), multi_engine live_oms_enabled, decision_loop capability | 4 authorities | **mode.py only** + IOMS.is_live derived |
| Strategy/setup rule | protocol, amt_scalping, decision_service, pipeline, gates, setup_state, setup_labels, model_router, broker_mapper, va_fade | setup identity in **5 tables** | **Setup registry** (one table) |
| Active symbols | dependencies (single writer ✅), settings (2 defaults), scanner_config, health (4-level chain), main, composition, frontend fallback, gameloop | single writer, **4 default literals** | **settings.SCANNER_UNDERLYINGS** only |
| Sizing/qty | SessionRisk, clamp, lots, 3 snaps in OMS, selector alt formulas, freeze/max_lots | formula single, lifecycle not | **SessionRisk + lots**; OMS must not re-snap differently |
| Drive departure | drive.py, dto ×4, context_builder or-chains, context, setup_state, gates_edge, submission_handler, SECOND_DRIVE tables | spatial fact flattened to verdict aliases | **DriveTracker states** → one DTO field |
| Risk halt / cooldown / stop-cap / MIN_STOP / `_as_counter` / tick 0.05 | dual/triple copies listed in §3 | copy-paste constants + parallel guards | named helpers in `stops.py` / `constants.py` |

---

## 5. Simplified Target Architecture

### Design principles applied

1. **Event-driven where observation matters; direct calls where latency and determinism matter.** Keep the tick→bar→gate→OMS chain as **direct synchronous calls** (hot path, no bus). Use the **existing EventBus** for domain events that already exist (`DecisionProduced`, `SignalBlocked`, `PositionOpened/Closed`, `StopMoved`, `BarClosed`) and **add missing observability events** — do not introduce a new broker.
2. **Single source of truth per concept** — every concept in §4 gets one owner; all other sites become thin callers or are deleted.
3. **Fewer modules over clever abstractions** — deletion first (§3), then merge, then rename.

### Target module map (deep modules)

```
[Feeds]
  SessionClock (deep)          ← timezones + phase table; 8 clocks collapse here
  InstrumentRegistry (deep)    ← _SPECS is sole lot/tick/strike/session authority
  MultiplexedFeed (deep)       ← packet→Tick translator; exposes drop_counts + silent_symbols
  Credentials (deep)           ← one resolve; no or-chains

[Money-path — direct calls, no bus]
  BarAggregator                ← one bar builder
  AMTEngine + SessionKernel    ← ONE session_reset(*, seed_scrub)
  DecisionContextSource (deep) ← one build(); typed position source = pm-first per dual-authority doc
  GatePipeline                 ← named gates; error ≠ veto (GATE_ERROR fails closed, observable)
  SetupRegistry                ← one table for SECOND_DRIVE et al.
  DriveTracker (deep)          ← observe() owns departure; DTO emits states not 4 aliases
  SessionRisk + lots           ← formula + snap once; OMS cannot re-derive differently
  IOMS (real seam)             ← 2 adapters; decide OD-1/2/3 so conformance has one truth

[Shell]
  CompositionRoot              ← sole paper/live + symbol + risk + credential wiring
  HealthService                ← /health + /health/ready read feed silence, drops, poll mode,
                                 watchdog liveness, journal, persistence_degraded; degraded==page
  EventBus (existing)          ← lifecycle append-before-publish everywhere; add DecisionDeferred,
                                 AMTFailure, FeedSilent, DropCount events
```

### Event catalogue (event-driven layer — observability, not control flow)

| Event | When | Replaces today’s silence |
|-------|------|---------------------------|
| `DecisionDeferred` | stale DTO skip, debounce block | zero-log skips |
| `AMTFailure` | analyzer exception (every time, not once) | once-then-silent |
| `GateError` | gate raised (vs veto) | `error:` masquerading as reject |
| `FeedSilent` / `DropCount` | mux `_check_silent`, queue Full | tests-only signals |
| `PollFallbackActive` | WS→REST degradation | one-way silent mode |
| `BridgeWriteFailed` | SQLite handler error | EventBus log-only |
| `WatchdogBeat` / `WatchdogDead` | watchdog pass / thread death | unmonitored daemon |
| Existing (keep) | DecisionProduced, SignalBlocked/Approved, PositionOpened/Closed, StopMoved, RiskUpdated, EmergencyFlatten | — |

### What stays direct-call (anti-event for hot path)

Tick routing, bar fold, gate evaluation, OMS submit/close, event fold — sequencing must remain deterministic and local; a bus here adds latency and failure modes without locality gain.

---

## 6. Required Tests Before Deploy

**Must be GREEN (blockers):**

1. `pytest tests/system` — money-path E2E (**currently 6 failed** — includes no-trade-without-approved-decision, closes-exactly-once).
2. `pytest backend/tests/unit/infrastructure/test_dhan_ledger_truthfulness.py` — UNKNOWN-on-cancel-fail + partial-fill persist (**2 failed** — live contract).
3. `pytest tests/architecture` — layer/ratchet gates.
4. `pytest tests/quant/execution` — includes OMS conformance (**384 green today**).
5. `pytest tests/quant/test_multiplexed_feed.py` — late-tick/arrival regression (**green**).
6. `pytest tests/quant/persistence tests/quant/test_event_store.py` (**green**).
7. `pytest tests/quant/decision tests/quant/strategies` (**425 green**).
8. New: **SessionClock consistency** — every entry point agrees on one timestamp table.
9. New: **Instrument parity** — json ≡ registry ≡ YAML (fails today on GOLD/GOLDM).
10. New: **Feed health wiring** — `/health` surfaces drop_counts/silent_symbols/poll mode.
11. New: **one session_reset property** — day-rollover ≡ explicit reset ≡ seed-scrub inventory.
12. Pre-existing red (triage or fix, do not silently accept): drive 4, setup_lifecycle 2, lvn 1, VA-clamp 2, opposing_signal_exit 2, positive_approval 1, Fabio India 2.

**Testability redesign required (interface is not a test surface today):**

- `_build_context` monkeypatching → construct via ContextSource.
- String-keyed `deps`/`state` dicts → typed capability object.
- Private poking (`_levels`, `_drive_tracker`) → DriveTracker public observe().
- `CoordinatorMetricsProvider` wrong attribute names → fix or delete.
- Positional-sniff `StreamingService.__init__` → kwargs.

**State transitions observable?** Mostly yes via EventBus; missing DecisionDeferred/AMTFailure/FeedSilent (must add). **Errors swallowed?** Gate errors, AMT-after-first, deferrals, bridge writes, poll-fallback, queue Full — all must become events or counters.

---

## 7. Go / No-Go Deployment Decision

### **NO-GO** (paper and live as constituted; hard NO-GO for live)

### What can break in production

1. WS exception → permanent 1s REST poll → rate-limited quote failures stop ticks (DEBUG only).
2. AMT failure → forever-stale DTO → decisions/exits on frozen analysis, no signal after first log.
3. `apply_event` ValueError → engine thread dies → symbol stops for session; only “degraded”.
4. Live UNKNOWN/cancel-fail ledger contract **currently regressed** (2 red tests) — prior failure class.
5. Restart book rebuild depends on unflagged SQLite bridge writes; EventStore in-memory; journal replay unread; rotation destroys archives.
6. Total feed silence → no warning (check gated on packet arrival); stale only after 300s market-open.
7. Frontend cannot authenticate if JWT/live configured → UI blind while trading continues.
8. Watchdog thread/pass death → no EOD backstop; dead-man hook is None.
9. instruments.json failure → fail-open empty map (no dual-feed).
10. Clock: IST LTT heuristic + 8 session clocks + wall-clock phases.

### What will fail silently

AMT-after-first · decision deferrals · queue drop-oldest · drop counts never exported · poll mode · bridge writes · publish-before-append (StopMoved) · LiveOMS audit emits · OUTRANKED masked · watchdog/producer death · dead Prometheus counters (dashboards green at 0) · `/health: degraded` not paging.

### Timing / order / external assumptions

Host clock vs IST · Dhan cadence vs 60/300s thresholds · 429 backoff · queue depths · order terminal within poll timeout (red tests) · lifecycle append-before-publish vs non-lifecycle opposite · two staleness clocks (300/600) · frontend heartbeat vs server deltas.

### Day-1 observe/alert (minimum)

1. `/health/ready ≠ ready` **or** status ∈ {degraded, unhealthy} >60s — **page on degraded**.
2. crashedEngines / staleEngines non-empty.
3. **Wire first:** mux drop_counts, silent_symbols(60), WS drop/reconnect counts, poll-fallback flag.
4. journal consecutive_failures; persistence_degraded; DEGRADED_EVENT_APPEND_FAILED.
5. Logs: ENGINE THREAD DIED, append failed, AMT analyze failed, EMERGENCY FLATTEN, RECONCILIATION_REQUIRED, poll fallback, gameloop reject.
6. Trade truth: PositionOpened without DecisionProduced; close without exit_source; positions past EOD; broker-vs-engine drift.
7. Per-symbol tick age; watchdog + producer thread alive.
8. Both shared and per-service Dhan circuit states.
9. ticks_processed_total must advance in market hours (telemetry canary).

### Blockers to clear for GO

| ID | Blocker | Gate |
|----|---------|------|
| B-1 | `tests/system` 6 failures (money-path E2E) | must green |
| B-2 | ledger truthfulness 2 failures (live UNKNOWN contract) | must green |
| B-3 | feed health not wired to /health (silent_symbols, drops, poll mode) | wire + test |
| B-4 | AMT once-then-silent + zero-log decision deferral | fix (events/counters) |
| B-5 | persistence overstated (empty EventStore fold, unread journal replay, unflagged bridge) | fix or honest docs + bridge latch |
| B-6 | observability largely fiction (dead counters, unwired provider, stale ADR-0003) | fix or remove series |
| B-7 | 12+ known red tests untriaged | fix or signed risk acceptance |
| B-8 | live-only: frontend JWT, pyramid asymmetry, Dhan CB export | fix before live |
| B-9 | dirty tree (uncommitted Fixes A/B/C) | commit + re-run gates |

### What is solid (credit)

OMS conformance · architecture ratchets · decision/strategy suites · feed late-tick regression (Fix C live-verified 0 drops) · event-store checksum hardening · quarantine-default reconciliation · refuse-to-start guards (live w/o broker, missing risk/cost) · crash containment · EOD wall-clock backstop · advisor never-gates · WS auth fail-closed in live.

### Path to GO

1. Green B-1 + B-2.
2. Wire B-3 (feed → health) + B-4 (events) + B-6 canary counter.
3. Triage/sign B-7; correct B-5 docs and add bridge failure latch.
4. Commit tree (B-9); re-run: `pytest tests/system tests/quant/execution tests/architecture tests/quant/test_multiplexed_feed.py tests/quant/persistence backend/tests/unit/infrastructure/test_dhan_ledger_truthfulness.py`.
5. Apply §3 deletion wave (zero-risk first) + SessionClock/Instrument/Context merges as separate commits with parity tests.
6. Live additionally: B-8.

**Until B-1..B-4 and B-9 are closed: deployment is BLOCKED.**

---

*Multi-agent provenance: module-map+elimination agent · E2E flow-trace agent · shotgun+SSoT agent · integrations+readiness agent · architecture deepening report (8 candidates, top = Drive/Departure). ADRs respected: ADR-0001 (crossings), ADR-0002 (IBroker gap GATED — composition-only merges), ADR-0003 (metrics split — note file stale).*
