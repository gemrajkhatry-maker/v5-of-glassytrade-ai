# Principal Review — GlassyTrade AI Trading Platform

**Role:** Principal Trading Systems Architect & Senior Code Reviewer
**Scope:** Full-system audit of `backend/`, `quant/`, `brokers/`, `shared/`, `tests/`, `frontend/`
**Severity framing:** Real-money trading system. Every finding is graded:

| Grade | Meaning |
|---|---|
| 🔴 CRITICAL | Can cause financial loss, wrong orders, or unrecoverable state |
| 🟠 HIGH | Will cause divergence between modes or maintenance collapse |
| 🟡 MEDIUM | Correctness risk under edge cases; significant debt |
| 🟢 LOW | Cleanup / hygiene |

**State note (2026-08-13):** This supersedes the earlier review that referenced the
deleted `backendv2/` and `brokersv2/` trees. Those were removed, and the legacy AMT
brain (`backend/app/domain/fabio_ai/`) was migrated into `quant/`. This document
reflects the current tree.

---

## 0. Executive Summary

The system is **mid-migration** and currently runs **two parallel decision engines**.
The old monolithic AMT brain was correctly moved to `quant/amt/`, but the migration
introduced a second, parallel decision path (the "greenfield" `quant/` engine) that is
gated behind `QUANT_EXECUTION_MODE` and shadows the live path. The remaining duplication
now sits in the **execution-critical path** (gates + signal builders), not cosmetics.

Current scale (excluding `backend/venv/`):

| Package | LOC | Files |
|---|---|---|
| `backend/` | ~60k | 116 (app) |
| `quant/` | ~30k | 165 |
| `brokers/` | ~24k | 65 |
| `shared/` | ~1k | 7 |
| `tests/` | ~21k | — |
| `frontend/` | ~9.5k TS | — |

**Bottom line:** one backend, one broker layer, one `quant/` engine now exist — good.
But there are still **two AMT kernels, two gate pipelines, two signal builders, two
`Signal` types, two `EventBus` implementations, and a mode fork** (`off/shadow/paper/live`)
inside decision/execution logic. That is the single largest remaining risk.

---

## 1. What actually runs (active execution flow)

```
start.sh → uvicorn app.main:app
  → TradingEngine._tick_loop (Dhan WS ticks)
    → CandleAggregator (Lee-Ready delta) → closed OHLC
    → TradingSessionService.process_tick (in asyncio.to_thread)
        ├─ AMTService → AMTHandler → quant.amt.analyzer.AMTAnalyzer   ← LIVE brain (legs, LVN/HVN, aggression, IB-break, NPOC)
        ├─ run_micro_agent_pipeline (LGBM agent)
        ├─ run_overseer_if_needed (MLX/LLM overseer)
        └─ on candle close → SessionEventRouter.execute_entry_path
              ├─ _try_execute_quant_decision   (AuctionCoordinator + DecisionService; gated by QUANT_EXECUTION_MODE)
              └─ run_gate_pipeline → quant.decision.gates.legacy_gate_pipeline (12 gates) → build_entry_signal
    → EntryCoordinator → RiskSizingEngine → IBroker (Dhan live | Paper) → SQLite + fsynced fallback spool
    → StateBroadcaster → WS gameloop (frontend = read-only viewer)
```

The infrastructure is genuinely strong: hexagonal ports
(`IBroker/IStorage/IMarketData/ILLMInference/IProbabilityInference`), a composition root,
typed frozen events with causal linking, a deterministic `QuantEngine` + golden-file test,
startup reconciliation + readiness contracts, circuit breakers, and a fail-closed
persistence path (`DBFallbackBuffer` + fsynced JSONL spool + block-new-entries when degraded).

---

## 2. The core problem: three brains, two decision engines

| # | Module | Role | Fed by |
|---|---|---|---|
| 1 | `quant/amt/analyzer.py` `AMTAnalyzer` | full AMT (legs, drives, aggression, NPOC) — **drives live entries** | `AMTService` |
| 2 | `quant/coordinator.py` `AuctionCoordinator` | pure auction snapshot (VWAP/VP/OF/location/absorption/triple-A) — WS `auction` field + feeds DecisionService | `QuantBridge` |
| 3 | `quant/decision/decision_service.py` `DecisionService` | new "decision engine of record" (5 gates + signal + VA-fade) | `QuantBridge` |

Plus **two gate pipelines** — `quant/decision/gates/legacy_gate_pipeline.py`
(12 gates, **live**, despite the "legacy" name) and `quant/decision/pipeline.py`
(5 gates, quant engine) — and **two signal builders**
(`gates/signal_builder.py` → domain Signal vs `decision/signal_builder.py` → quant Signal).

`QUANT_EXECUTION_MODE ∈ {off, shadow, paper, live}` puts `if mode == ...` inside
decision/execution logic — a mode fork, which is exactly the anti-pattern this codebase
must avoid.

---

## 3. Findings

### 3.1 CRITICAL

1. **Two decision engines can disagree, and only one is parity-tested.**
   `docs/AMT_UNIFICATION.md` documents up to **16% VAL divergence** (leg-VA clamp) and a
   VWAP definition difference between `AMTAnalyzer` and `AuctionCoordinator`. Flipping
   `QUANT_EXECUTION_MODE=live` swaps which math places real orders with no gate asserting
   the two engines agree.
2. **Replay does not cover the live path.** `QuantEngine` (`quant/runtime.py`) is
   deterministic/replayable, but the live path is `TradingEngine → AMTAnalyzer → legacy
   gates` — different code. `QUANT_RECORD_REPLAY` captures bars+auction only, not
   decisions/fills. No replay == live proof exists.

### 3.2 HIGH

3. **God objects:** `trading_session.py` (1,226 lines), `session_event_router.py` (957),
   `quant/amt/analyzer.py` (1,378).
4. **Mixed concurrency:** async tick loop → `asyncio.to_thread` → `threading.Lock` in
   `AMTService`/`QuantBridge`/`DBFallbackBuffer` + `session._lock`. No single ownership rule.
5. **Decimal/float split** in the domain: `session_event_router` adds `float()` normalization
   ("domain prices may be Decimal while AMT values are floats"); `OHLC.create()` Decimal
   coercion breaks `AMTAnalyzer` (per `AMT_UNIFICATION.md`).

### 3.3 MEDIUM

6. Two-phase/lazy wiring (`_OverseerBroadcastBridge.bind`, `register_singleton(list, …)`).
7. Frontend still derives VWAP band style (`AMTLevelsOverlay.calculateVWAPColor`).
8. `_LocalFallbackSpool` fsyncs per append/ack — fine on the failure path only.
9. `ai_command_service.get_journal_endpoint` retains unreachable `compare`/`promotion`
   branches (the router has dedicated endpoints for those).

### 3.4 LOW

10. `backend/venv/` present on disk (torch/transformers/scipy), gitignored but heavy.
11. Stale docs: `.claude/skills/fabio/SKILL.md`, `.claude/skills/infra/SKILL.md` still point
    at the deleted `backend/app/domain/fabio_ai/services/*` paths.

---

## 4. Duplicates / dead code / shotgun surgery (the removal ledger)

### 4.1 Duplicate implementations

| Concept | Copies | Severity |
|---|---|---|
| Gate pipeline | `gates/legacy_gate_pipeline.py` (12, live) vs `decision/pipeline.py` (5, quant) | 🔴 |
| Signal builder | `gates/signal_builder.py` vs `decision/signal_builder.py` | 🔴 |
| Signal type | `quant/contracts/entities.py` vs `quant/decision/signal_builder.py` (+ `quant_signal_mapper.py` glue) | 🔴 |
| AMT kernel | `AMTAnalyzer` vs `AuctionCoordinator` | 🔴 |
| EventBus | `quant/contracts/event_store.py` vs `quant/events.py` | 🟠 |
| Bar/candle | `value_objects.OHLC`, `quant/bars.Bar`, `brokers/.../value_objects.OHLC` | 🟠 |
| Domain entities | `shared/entities/models.py` vs `quant/contracts/entities.py` | 🟠 |
| VWAP | `quant/vwap.py:VWAPState`, `quant/contracts/vwap_bands.py:VWAPBands` | 🟡 |
| Gate logic | `handlers/entry_gate_coordinator.py` vs `quant/decision/gates/*` | 🟡 |

### 4.2 Dead code (already removed this pass)

- `backend/app/infrastructure/adapters/live_engine_server.py` (+ its only test) — alternate runtime, never booted.
- `backend/app/domain/models/market_state.py` — frozen-dataclass domain experiment with zero importers.
- `backend/tests/unit/architecture/test_module_boundaries.py` — fully `@pytest.mark.skip`, asserted on deleted `fabio_ai/`.
- `graphify-out/` — tracked stale tooling cache indexing the pre-migration tree.
- `MagicMock/` — stray test artifact (a `MagicMock` spool-path name materialized as a directory).

### 4.3 Shotgun surgery

- `execute_signal` is 4 layers deep with 2 bypass calls:
  `trading_session._execute_signal → router.execute_signal → entry_coordinator.execute_signal`,
  plus `router` calls `entry_coordinator.execute_signal` directly (lines 625, 747).
- Scattered session mutation: `_last_exec_mono` (4 writers), `_pending_decision` (4),
  `last_quant_decision` (3), `_agent_decision` (3).
- `execute_entry_path` takes ~20 positional/keyword args (data clump).

### 4.4 Test/deploy gaps

- **55 skipped tests** — false "green".
- No type checker in CI (only `ruff` + `compileall` + pytest).
- `requirements.txt` vs `requirements-mlx.txt` split (MLX adapter in `quant/inference`).

---

## 5. Removal & consolidation plan

**P0 — done (this pass):** deleted `live_engine_server`, dead `market_state.py`, skipped
architecture test, `graphify-out/`, `MagicMock/`; gitignored stale caches + spool locks.

**P1 — consolidation (behind a parity gate):**
1. Collapse `gates/signal_builder.py` into `decision/signal_builder.py`; delete `quant_signal_mapper.py`.
2. Fold the 12 gates of `legacy_gate_pipeline.py` into `decision/pipeline.py`; delete the "legacy" copy.
3. Delete `handlers/entry_gate_coordinator.py` (gate logic lives only in `quant/decision/gates`).
4. Pick one `EventBus`; one bar/candle type; one VWAP band type.

**P2 — switchover (after replay parity):**
5. Delete `QUANT_EXECUTION_MODE` branching in `session_event_router`; make `QuantEngine` the
   live path (mode = event source: `LiveFeed | ReplaySource | Simulator`).
6. Delete `AMTAnalyzer`'s parallel entry path once `AuctionCoordinator`+`DecisionService`
   parity is proven on a golden tape.

---

## 6. Target architecture

```
Frontend (pure projection)
   │  REST + WS (versioned, generated)
API/Contract layer (FastAPI routers, Pydantic DTOs)
   │
Application (thin orchestration: entry/exit coordinators, session lifecycle)
   │
Domain (single source of truth):
   Candle · VWAPState · VolumeProfile · Signal · Position · Risk · Session
   AuctionCoordinator (ONE kernel) → DecisionService (ONE gate set + ONE SignalBuilder)
   │
Pipeline: sequencer → normalize → candle → indicators → structure → signal → gates → risk → order
   │
EventSource: LiveFeed | ReplaySource | HistoricalFile | Simulator   ← mode is only here
   │
IBrokerAdapter (Dhan | Paper) → SQLite + fsynced spool   ·   MLX/LLM advisory
```

**Non-negotiables:** one kernel, one gate set, one `Signal`, one `EventBus`, mode = event
source only. This collapses §4.1 and makes replay-vs-live parity enforceable by feeding the
same event tape through the same `process(event, state)`.

### Multi-agent execution order

| Agent | Mission | Gate to pass |
|---|---|---|
| A — Dead-code removal | P0 deletions + untrack stale cache | suite green |
| B — Duplicate consolidation | unify gates/Signal/VWAP/EventBus | golden-file + parity green |
| C — Legacy switchover | promote `QuantEngine` to live; delete mode fork | replay == live byte-for-byte |
| D — Shotgun-surgery refactor | flatten `execute_signal`; extract `EntryDecision` value object; one concurrency owner | unit tests green |
| E — Hardening | un-skip/delete the 55 skipped tests; add mypy; add replay-parity CI gate | CI gate passing |
