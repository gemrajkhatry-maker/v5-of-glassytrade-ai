# End-to-End Reimplementation Plan

**Date:** 2026-08-13
**Scope:** `backend/`, `quant/`, `brokers/`, `shared/`, `tests/`, `frontend/`
**Source:** consolidated from `PRINCIPAL_REVIEW.md` (current-state audit) and the multi-agent removal/duplication investigation.
**Strategy:** remove dead code and duplicate implementations first, collapse to the minimum code required for correct behavior, and only then flip the live execution path — every switchover behind a replay-parity gate.

---

## 0. Baseline and invariants

The booted service is `start.sh → uvicorn app.main:app → TradingEngine → TradingSessionService`.
The active decision path is:

```
Dhan WS ticks → CandleAggregator → closed OHLC → TradingSessionService.process_tick
  ├─ AMTService → AMTHandler → quant.amt.analyzer.AMTAnalyzer        (LIVE brain)
  ├─ micro agent (LGBM) / MLX-LLM overseer
  └─ candle close → SessionEventRouter.execute_entry_path
        ├─ _try_execute_quant_decision  (AuctionCoordinator + DecisionService, gated by QUANT_EXECUTION_MODE)
        └─ legacy 12-gate pipeline + build_entry_signal               (LIVE entry path)
  → EntryCoordinator → RiskSizingEngine → IBroker → SQLite + fsynced fallback spool
  → StateBroadcaster → WS gameloop (frontend is a read-only viewer)
```

**Non-negotiables** (each phase must preserve, and each gate must verify):

1. **One kernel** — a single AMT/auction analysis kernel feeds every decision.
2. **One gate set + one `Signal` type + one `SignalBuilder`** — no parallel entry logic.
3. **One `EventBus`** — a single event-store contract.
4. **Mode = event source only** — `LiveFeed | ReplaySource | HistoricalFile | Simulator`; no `if mode == ...` inside decision/execution logic.
5. **Replay == live** — the same event tape through the same `process(event, state)` must be byte-for-byte deterministic (golden-file enforced in CI).
6. **Fail closed** — AMT/decision failure blocks new entries but never orphans an open position, exit/watchdog handling, or persistence.

---

## Phase A — Dead-code removal (P0) ✅ DONE (commit `4926af4`)

Already deleted this pass:

- `backend/app/infrastructure/adapters/live_engine_server.py` (+ its only test) — alternate runtime, never booted.
- `backend/app/domain/models/market_state.py` — dead `VWAPState` domain experiment, zero importers.
- `backend/tests/unit/architecture/test_module_boundaries.py` — fully `@pytest.mark.skip`, asserted on deleted `fabio_ai/`.
- `graphify-out/` — tracked stale cache indexing the pre-migration tree.
- `MagicMock/` — stray test artifact (a `MagicMock` spool-path name materialized as a directory).

Also updated `.gitignore` (`graphify-out/`, `MagicMock/`, `*.fallback.jsonl.lock`) and rewrote `PRINCIPAL_REVIEW.md` to the current tree.

**Remaining P0 follow-ups (path-mapping decisions, not blind deletes):**

1. Fix `.claude/skills/fabio/SKILL.md` and `.claude/skills/infra/SKILL.md` — they still point at deleted `backend/app/domain/fabio_ai/services/*` paths. Repoint to the migrated `quant/amt/*` modules or delete the stale path references.
2. Remove the unreachable `compare`/`promotion` branches inside `ai_command_service.get_journal_endpoint` (the router has dedicated endpoints for those).
3. Remove the on-disk `backend/venv/` (torch/transformers/scipy) from the working copy if it is a local-only artifact; keep the `requirements*.txt` split (MLX vs CPU) but document it.

**Gate:** repo-wide grep returns zero references to deleted modules; `compileall` clean; existing unit + system suite green.

---

## Phase B — Duplicate consolidation (P1)

Collapse the parallel implementations identified in the audit. Every deletion is behind a reference scan + the golden-file/parity gate — **never** blind deletion from the live path.

| # | Consolidation | Target state | Risk |
|---|---|---|---|
| B1 | Collapse `quant/decision/gates/signal_builder.py` (→ domain `Signal`) into `quant/decision/signal_builder.py` (`SignalBuilder` → quant `Signal`); delete `quant_signal_mapper.py` glue | one `Signal` + one `SignalBuilder` | 🔴 touching live entry |
| B2 | Fold the 12 gates of `quant/decision/gates/legacy_gate_pipeline.py` into `quant/decision/pipeline.py` (5 gates); delete the "legacy" copy | one gate pipeline | 🔴 live path is the "legacy" one |
| B3 | Delete `handlers/entry_gate_coordinator.py` — gate logic must live only in `quant/decision/gates/` | no backdoor gate coordinator | 🟠 |
| B4 | Pick one `EventBus`: `quant/contracts/event_store.py` vs `quant/events.py` | one event store contract | 🟠 |
| B5 | Pick one bar/candle type: `value_objects.OHLC` vs `quant/bars.Bar` vs `brokers/.../value_objects.OHLC` | one canonical bar | 🟠 |
| B6 | Pick one VWAP band type: `quant/vwap.py:VWAPState` vs `quant/contracts/vwap_bands.py:VWAPBands` | one VWAP band | 🟡 |
| B7 | Reconcile domain entities: `shared/entities/models.py` vs `quant/contracts/entities.py` | one entity contract; fix `shared → brokers` dependency inversion | 🟠 |

**Gate (per batch):** reference scan shows zero importers of the deleted copy; focused unit tests for the surviving copy pass; the deterministic `QuantEngine` golden-file test stays byte-identical.

**Batch order:** B7 (contracts, no execution risk) → B4/B5/B6 (plumbing) → B1/B2/B3 (execution-critical, only after shadow parity).

---

## Phase C — Legacy switchover (P2, after replay parity)

This is the point where the system goes from "two engines" to "one engine".

1. **Build the replay-parity harness first** (blocker for C): feed one recorded tape through the live `TradingEngine` path and the deterministic `quant/runtime.py:QuantEngine`; assert identical `AuctionState → Decision → Signal → Order` outputs. Store a golden tape in CI. `QUANT_RECORD_REPLAY` must capture decisions/fills, not just bars+auction.
2. Promote `QuantEngine` to the live entry path; run `AMTAnalyzer`'s legacy entry path only in shadow for comparison.
3. Delete the `if QUANT_EXECUTION_MODE == ...` branching in `session_event_router._try_execute_quant_decision` and `quant_bridge`. Replace mode with the event-source abstraction (`LiveFeed | ReplaySource | HistoricalFile | Simulator`). Paper/live are now broker-adapter concerns, not decision-logic branches.
4. Delete the legacy gate pipeline and legacy `AMTAnalyzer` entry path once parity is proven on the golden tape (16% VAL divergence and the VWAP-definition difference documented in `docs/AMT_UNIFICATION.md` must be resolved *before* this deletion, or the surviving kernel must be shown to be the correct one).
5. Resolve the Decimal/float split: one canonical numeric type (`Decimal` for money/prices, documented float only for indicator math). Remove the `float()` normalization hack in `session_event_router`.

**Gate:** replay == live byte-for-byte on the golden tape; paper acceptance gate passes; staged one-position live pilot before full live authority.

---

## Phase D — Shotgun-surgery / SRP refactor

The god objects and scattered writes identified in §4.3 of the review.

1. Flatten the 4-deep `execute_signal` chain (`trading_session._execute_signal → router.execute_signal → entry_coordinator.execute_signal` plus the 2 bypass calls). Extract an `EntryDecision` value object to replace the ~20-arg `execute_entry_path` signature.
2. Give one owner to each piece of session state: `_last_exec_mono` (4 writers), `_pending_decision` (4), `last_quant_decision` (3), `_agent_decision` (3). Move each behind a single accessor.
3. Define one concurrency rule (the async tick loop → `asyncio.to_thread` → `threading.Lock` boundary) and apply it uniformly to `AMTService`, `QuantBridge`, `DBFallbackBuffer`, and `session._lock`.
4. Decompose the god objects into focused modules without changing behavior: `trading_session.py` (1,226 lines), `session_event_router.py` (957), `quant/amt/analyzer.py` (1,378). Split the analyzer into composable kernels (profile / vwap / legs / IB), the router into a thin entry router + a gate runner.

**Gate:** existing unit + system tests green after each step (behavior-preserving refactor only).

---

## Phase E — Frontend = pure projection

1. Remove `frontend/components/chart/AMTLevelsOverlay.ts::calculateVWAPColor` — the server must send VWAP band positions/colors; the UI renders, never derives.
2. Remove the synthetic forward-fill / `mergeCandleData` fabrication in `frontend/hooks/useServerTradingSystem.ts` — the server sends authoritative candles with a `source: EXCHANGE | SYNTHETIC` provenance field; the UI must not invent candles.
3. Remove any remaining `dataSource: 'DHAN' | 'SERVER'` direct-broker config flag (dead; no Dhan WS client exists in the frontend).
4. Ensure the wire contract is generated once (`scripts/generate_types.py`) and consumed by both backend DTOs and `frontend/types_generated.ts`.

**Gate:** frontend typecheck/build clean; no indicator/market math remains in `frontend/`.

---

## Phase F — Hardening / deployability

1. **Tests:** un-skip or delete every `@pytest.mark.skip` test (11 files currently carry skip markers). Skips are false "green"; each must either be made to run or be removed with a reason.
2. **Type checking:** add `mypy` (strict, incremental per package) to CI alongside the existing `ruff` + `compileall` + pytest steps.
3. **Replay-parity CI gate:** add the golden-tape comparison as a blocking CI step.
4. **Dependencies:** settle the `requirements.txt` vs `requirements-mlx.txt` split — document the CPU vs Apple-Silicon matrix in `README`/`docs`; ensure CI installs the CPU set deterministically.
5. **Deploy:** verify `start.sh`, `start_paper.sh`, `start_preflight.sh`, `start_deferred.sh`, `start_mcx.sh` all resolve the selected interpreter and `PYTHONPATH=backend:.` consistently (no hard-coded `venv/bin/uvicorn` or machine-specific paths).

**Gate:** CI green including mypy + parity; all launch scripts pass preflight from a clean checkout.

---

## Multi-agent execution order

| Agent | Mission | Phase | Gate to pass |
|---|---|---|---|
| A — Dead code | P0 leftovers + stale docs + venv hygiene | A | suite green |
| B — Duplicate consolidation | B1–B7 unify gates/Signal/VWAP/EventBus | B | golden-file + parity green |
| C — Legacy switchover | replay harness → promote `QuantEngine` → delete mode fork | C | replay == live byte-for-byte |
| D — Shotgun-surgery refactor | flatten `execute_signal`; `EntryDecision` VO; one concurrency owner | D | unit tests green |
| E — Frontend projection | remove UI math/forward-fill/direct-broker flag | E | frontend build clean |
| F — Hardening | un-skip tests; mypy; parity CI gate; launch scripts | F | CI gate passing |

**Sequencing constraint:** B and C are the only execution-critical phases. A, D, E can run in parallel with B. C must follow B (it deletes what B consolidates). F runs last and certifies the whole thing.

## Safety rules (applies to every agent)

1. Never delete from the live entry path based on file size, name, or an old audit alone — scan all source/tests/scripts/docs for references first.
2. Preserve the current live engine until the quant path has production bar-close integration + paper evidence + replay parity.
3. Keep paper/live broker adapters, exit/watchdog, reconciliation, and idempotent-close code intact until contract tests pass.
4. Every batch lands as a discrete commit that passes `compileall` + focused tests; execution-path batches additionally require the replay/parity or integration gate.
5. No credential changes, no `git push`, no live-market actions as part of this work.
