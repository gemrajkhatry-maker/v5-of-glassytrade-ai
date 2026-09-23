# Pre-Deployment Remediation Program — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear all NO-GO blockers from `docs/reviews/2026-09-23-predeployment-system-review.md`, then apply the zero-risk deletion wave and SSoT deepening so the system is deployable, testable, and behaviorally correct.

**Architecture:** Sequenced waves on one branch: (1) commit baseline + fix red money-path tests, (2) wire observability (feed health + silent-path events + metrics canary), (3) zero-risk deletions, (4) SSoT merges (SessionClock, instruments, DecisionContext, drive departure) as separate commits with parity tests. Hot path stays direct-call; EventBus gains observability events only — no new broker. ADR-0001 crossings, ADR-0002 IBroker gap (GATED — composition moves only), ADR-0003 metrics split respected; update stale ADR-0003 when MetricsCollector is reconciled.

**Tech Stack:** Python 3.13, pytest (+ `--timeout`), ruff, FastAPI, SQLite WAL, asyncio/threads.

**Source of truth for findings:** `docs/reviews/2026-09-23-predeployment-system-review.md` (blockers B-1..B-9, DELETE D1..D20, MERGE table, §5 target architecture).

## Global Constraints

- **No stash chains** (`git stash push`/`pop` never chained) — 3 stashes exist; leave them alone.
- **Never `git add -A`** — path-scoped commits only.
- **Implementers do not push**; controller commits after task review.
- **Do NOT touch:** `wiring_advisor`, `laya_advisor`, `timesfm_*` (except D14 param removal), `llm/*`, env `LLM_*`/`TIMESFM_*`/`LAYA_*`/`MLX_*`/`OPENROUTER_API_KEY`, AI/UI cards, `gap_architecture.workflow.{html,json}` until D16 (move/delete as a pair with hygiene prefix update), entry authority `AmtScalpingStrategy.should_enter`, exit authority `ExitManager → PositionManager → ExitEngine`.
- **Do NOT migrate `IBroker` ↔ `IBrokerPort`** (ADR-0002 GATED).
- **Named crossings only** for float↔Decimal (ADR-0001): `to_broker_signal`, `broker_position_to_fill`, `position_to_row`/`row_to_position`, Dhan converters.
- **Advisors never gate** — no change to `decision_loop` post-DecisionProduced notify ordering.
- **TDD:** failing test first for every behavior change; watch it fail; minimal green.
- **Gates every task:** `.venv/bin/python -m ruff check quant backend/app brokers shared tests backend/tests` GREEN; task's covering pytest file(s) green.
- **Merge gate (end of each wave):** `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture tests/quant/decision tests/quant/execution tests/quant/runtime tests/quant/test_multiplexed_feed.py -q --timeout=30` — known pre-existing failures listed per wave; only NEW failures block.
- **Known pre-existing red (do not "fix" blindly):** drive 4, setup_lifecycle 2, lvn 1, VA-clamp 2, opposing_signal_exit 2, positive_approval 1, ledger truthfulness 2, tests/system 6, fabio_india 2. Wave tasks either make them green or record explicit sign-off in the progress ledger.
- **No new dependencies.** No partial fixes. Deletion preferred over refactoring.
- **Ledger:** append every completed task to `.superpowers/sdd/progress.md`.
- **Restart live session only via** `./start.sh nse` or `./start.sh mcx clean` (env from `backend/.env`).

## File Structure (program)

| Area | Files | Responsibility |
|------|-------|----------------|
| Baseline | existing uncommitted Fix A/B/C files | commit first — freeze review baseline |
| Wave 1 red fixes | `backend/tests/unit/infrastructure/test_dhan_ledger_truthfulness.py` + `dhan_broker_adapter.py` (only if code wrong); `tests/system/*` + underlying money-path bugs | B-1, B-2 |
| Wave 2 health | `quant/brokers/multiplexed_feed.py`, `backend/app/api/routers/health.py`, `quant/multi_engine.py` snapshot | surface feed drops/silence/poll |
| Wave 2 events | `quant/events.py` (catalogue), `quant/engine/tick_handler.py`, `quant/amt_engine.py`, `quant/decision/pipeline.py` | DecisionDeferred, AMTFailure, GateError |
| Wave 2 metrics | `backend/app/core/metrics.py`, `quant/engine/decision_loop.py`, composition | increment real counters; canary |
| Wave 3 deletions | D1–D20 targets + their tests | zero-risk removals |
| Wave 4 SSoT | SessionClock, InstrumentRegistry, ContextSource, DriveTracker | architecture candidates 1–3,5 |

---

## Wave 0 — Baseline freeze (B-9)

### Task 0: Commit Fixes A/B/C + review docs

**Files:**
- Modify: commit only (no code edits)
- Include: `backend/app/application/di/composition_root.py`, `backend/tests/unit/application/test_composition_root.py`, `quant/brokers/gateway.py`, `quant/brokers/multiplexed_feed.py`, `quant/runtime.py`, `tests/quant/test_multiplexed_feed.py`, `docs/reviews/2026-09-23-predeployment-system-review.md`, `docs/reviews/2026-09-23-architecture-review.html` (if moved into repo) — **only files that belong**; leave `automation/reports/*` untracked.

**Interfaces:**
- Produces: clean `git status` (except intentional untracked junk) as Wave 1+ BASE commit.

- [ ] **Step 1: Verify gates on the working tree**

Run: `.venv/bin/python -m ruff check quant backend/app brokers shared tests backend/tests && .venv/bin/python -m pytest tests/quant/test_multiplexed_feed.py tests/architecture -q --timeout=30`
Expected: ruff CLEAN; tests pass (architecture may have its known set — record exact counts).

- [ ] **Step 2: Stage path-scoped**

```bash
git add backend/app/application/di/composition_root.py \
  backend/tests/unit/application/test_composition_root.py \
  quant/brokers/gateway.py quant/brokers/multiplexed_feed.py quant/runtime.py \
  tests/quant/test_multiplexed_feed.py \
  docs/reviews/2026-09-23-predeployment-system-review.md
git status --short  # confirm no automation/reports, no secrets
```

- [ ] **Step 3: Commit**

```bash
git commit -m "fix: composition scan, arrival freshness, late_tick grace; add predeploy review"
```

- [ ] **Step 4: Record BASE**

Run: `git rev-parse HEAD` → save as `WAVE0_BASE` in `.superpowers/sdd/progress.md`.

---

## Wave 1 — Money-path red (B-1, B-2) — BLOCKERS

### Task 1: Ledger truthfulness green (B-2)

**Files:**
- Test: `backend/tests/unit/infrastructure/test_dhan_ledger_truthfulness.py` (already red — 2 tests)
- Likely modify: `backend/app/infrastructure/adapters/dhan_broker_adapter.py` (cancel/timeout/partial-fill persist path ~`:251-268`)
- Do not touch: live broker wire protocol beyond persistence of UNKNOWN/RECONCILIATION_REQUIRED

**Interfaces:**
- Consumes: order poll terminal/non-terminal semantics in `dhan_broker_adapter`
- Produces: durable row status UNKNOWN (not CANCELLED) on cancel-after-timeout; partial-fill frozen-by-cancel persisted — same guarantees tests already assert

- [ ] **Step 1: Run the 2 failing tests; capture exact assertion diffs**

Run: `.venv/bin/python -m pytest backend/tests/unit/infrastructure/test_dhan_ledger_truthfulness.py -q --timeout=60`
Expected: FAIL ×2 (`test_cancel_failure_after_timeout_persists_unknown_not_cancelled`, `test_partial_fill_frozen_by_cancel_is_persisted`). Paste failure text into report file.

- [ ] **Step 2: Root-cause with systematic-debugging (read code path first)**

Read `dhan_broker_adapter` cancel + poll + persist; compare to test expectations. Identify: wrong status written, missing persist call, or race. Do NOT weaken the test — tests encode the prior incident contract.

- [ ] **Step 3: Minimal fix + re-run**

```bash
.venv/bin/python -m pytest backend/tests/unit/infrastructure/test_dhan_ledger_truthfulness.py -q --timeout=60
```
Expected: PASS (all tests in file).

- [ ] **Step 4: Full file + neighbors**

```bash
.venv/bin/python -m pytest backend/tests/unit/infrastructure -q --timeout=60
```
Expected: no NEW failures vs recorded baseline.

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/adapters/dhan_broker_adapter.py
git commit -m "fix(ledger): persist UNKNOWN on cancel-timeout; persist partial-fill frozen by cancel"
```

### Task 2: tests/system money-path E2E green (B-1)

**Files:**
- Test: `tests/system/test_paper_protocol.py` (4 failures), `tests/system/test_quant_execution_e2e.py` (1), `tests/system/test_quant_runtime_e2e.py` (1)
- Modify production only where the test encodes a real invariant (see review Path A/B)

**Interfaces:**
- Produces: `pytest tests/system` → 0 failed

Known failing tests (verify first, list may grow):
1. `test_paper_protocol::test_no_trade_without_approved_decision`
2. `test_paper_protocol::test_fills_follow_fill_price_convention`
3. `test_paper_protocol::test_each_position_closes_exactly_once`
4. `test_paper_protocol::test_ws_contract_carries_quant_decision_on_approved_bars`
5. `test_quant_execution_e2e::test_aggression_long_session_drives_paper_fill`
6. `test_quant_runtime_e2e::test_runtime_state_fills_frontend_contract`

- [ ] **Step 1: Run suite; dump failures**

```bash
.venv/bin/python -m pytest tests/system -q --timeout=120 2>&1 | tee /tmp/system-red.txt
```
Expected: 6 failed (or document delta).

- [ ] **Step 2: Triage each failure — classify as (a) product bug, (b) test drift, (c) depends on Wave-0 commit**

For (a): write failing-test confirmation if missing, fix production (minimal), re-run. For (b): only adjust test if review shows the invariant changed for a load-bearing reason — record in ledger. For (c): re-run after Task 0.

- [ ] **Step 3: Re-run until green**

```bash
.venv/bin/python -m pytest tests/system -q --timeout=120
```
Expected: `0 failed`.

- [ ] **Step 4: Merge-gate sample**

```bash
.venv/bin/python -m pytest tests/quant/execution tests/architecture -q --timeout=60
```
Expected: no NEW failures.

- [ ] **Step 5: Commit**

```bash
git add tests/system <modified files>
git commit -m "fix(e2e): money-path paper protocol and runtime frontend contract"
```

### Task 3: Fabio India integration (part of B-7 triage)

**Files:**
- Test: `tests/integration/test_fabio_india_scenarios.py` (2 failures — GATE_REJECTED mid-candle body 38% < 60%)

- [ ] **Step 1: Run and read gate reasons**

```bash
.venv/bin/python -m pytest tests/integration/test_fabio_india_scenarios.py -q --timeout=60
```

- [ ] **Step 2: Decide fix vs sign-off**

If strategy threshold drift is unintentional → fix product or fixture to restore intended scenario. If intentional from full-AMT-fidelity plan → mark test `xfail(strict=False)` **only with ledger sign-off line** `B-7 fabio_india: accepted, reason=...`. Prefer product/fixture fix.

- [ ] **Step 3: Green or signed xfail; commit**

```bash
git add tests/integration/test_fabio_india_scenarios.py  # or product file
git commit -m "test: fabio india scenarios <fixed|signed-off>"
```

**Wave 1 exit gate:** `pytest tests/system backend/tests/unit/infrastructure/test_dhan_ledger_truthfulness.py tests/integration/test_fabio_india_scenarios.py -q` → 0 failed (or only signed xfails). Append `Wave 1 complete (BASE..HEAD)` to ledger.

---

## Wave 2 — Observability & silent-failure kill (B-3, B-4, B-6)

### Task 4: Surface feed health on /health (B-3)

**Files:**
- Modify: `quant/brokers/multiplexed_feed.py` (public snapshot accessor if needed — `silent_symbols`, `_drop_counts`, poll-fallback flag, producer alive)
- Modify: `backend/app/api/routers/health.py` (`/health` coordinator block)
- Modify: `quant/multi_engine.py` if feed handle must be reached from coordinator
- Test: `tests/quant/test_multiplexed_feed.py`, `backend/tests/unit/api/test_health*.py` (create/extend)

**Interfaces:**
- Produces: `/health` JSON gains `feed: { silentSymbols: [...], dropCounts: {...}, pollFallback: bool, producerAlive: bool }`; degraded when `silentSymbols` non-empty while market open OR `pollFallback` true for >60s OR `producerAlive` false.

- [ ] **Step 1: Failing test — health includes feed block**

```python
# backend/tests/unit/api/test_health_feed.py
def test_health_exposes_feed_silence_and_drops(monkeypatch):
    # arrange coordinator/feed double with silent_symbols(["X"]) and _drop_counts {"late_tick:X": 3}
    # act GET /health
    # assert body["checks"]["feed"]["silentSymbols"] == ["X"]
    # assert body["checks"]["feed"]["dropCounts"]["late_tick:X"] == 3
    # assert body["status"] in ("degraded", "ok") per market-open rules in test
```
Run: `.venv/bin/python -m pytest backend/tests/unit/api/test_health_feed.py -q` → FAIL (no `feed` key).

- [ ] **Step 2: Feed snapshot API**

Add `MultiplexedMarketFeed.health_snapshot() -> dict` returning `silent_symbols()`, `dict(_drop_counts)`, `self._poll_fallback` (thread the flag from `dhan_adapter` stream switch — if adapter-owned, store on feed when `stream_full` falls back), `self._producer_thread_alive()`.

- [ ] **Step 3: Wire into health router** via coordinator (same path as `staleEngines`). Market-open gate: reuse `is_market_open` (do not add a 9th clock — call `symbol_registry.is_market_open`).

- [ ] **Step 4: Green + ruff + commit**

```bash
.venv/bin/python -m pytest backend/tests/unit/api/test_health_feed.py tests/quant/test_multiplexed_feed.py -q --timeout=30
git add quant/brokers/multiplexed_feed.py backend/app/api/routers/health.py quant/multi_engine.py backend/tests/unit/api/test_health_feed.py
git commit -m "feat(health): surface feed silence, drop counts, poll fallback on /health"
```

### Task 5: Count queue drop-oldest + rate-limit honesty

**Files:**
- Modify: `quant/brokers/multiplexed_feed.py` `_put_tick`
- Test: `tests/quant/test_multiplexed_feed.py`

- [ ] **Step 1: Failing test** — fill a queue to max, push one more, assert `dropCounts["queue_full:<sym>"] == 1` (and oldest evicted).
- [ ] **Step 2: Implement counter** in `except queue.Full` before evict.
- [ ] **Step 3: Green; also include rate-limited warning detail with running count** (already in `_note_drop` — ensure queue_full path calls `_note_drop`).
- [ ] **Step 4: Commit** `feat(feed): count and report queue_full drop-oldest`.

### Task 6: AMTFailure event every failure (B-4a)

**Files:**
- Modify: `quant/amt_engine.py:613-620` (`_amt_fail_logged` once-then-silent)
- Modify: `quant/events.py` if new event type needed (or reuse log+counter only — prefer event `AMTFailure` if EventBus already has generic pattern; else counter `amt_failures_total` + ERROR log every time)
- Test: `tests/quant/test_amt_engine*.py` or new

**Decision (locked):** every AMT analyze exception logs ERROR **and** increments `amt_failures_total`; snapshot field `AMT_FAILING` when last failure <60s. Emit EventBus event only if a free event slot exists without new bus code — otherwise counter+log satisfies B-4.

- [ ] **Step 1: Failing test** — analyzer raises twice; assert 2 ERROR logs (caplog) and counter == 2; second failure does not silently return only stale DTO without signal (emit set).
- [ ] **Step 2: Remove once-only gate**; keep stale-DTO return (decision freshness still gated by Task 7) but always signal failure.
- [ ] **Step 3: Green; commit** `fix(amt): report every analyze failure, not only the first`.

### Task 7: DecisionDeferred observable (B-4b)

**Files:**
- Modify: `quant/engine/tick_handler.py:117-146` (`_decide_if_macro_fresh` silent return)
- Modify: `quant/engine/decision_loop.py:305-328` (debounce block — docstring says emits nothing)
- Test: existing decision_loop/tick_handler tests + new

- [ ] **Step 1: Failing tests**
  - stale DTO → skip decide: caplog has `DecisionDeferred reason=STALE_DTO` (or counter+snapshot).
  - debounce block: same with `reason=DEBOUNCE`; startup/exposure blocks already log — add counter for consistency only if trivial.
- [ ] **Step 2: Implement deferred logging/counter** — no behavior change to blocking.
- [ ] **Step 3: Green; commit** `feat(decision): observe decision deferrals (stale DTO, debounce)`.

### Task 8: GateError ≠ veto (pipeline honesty)

**Files:**
- Modify: `quant/decision/pipeline.py:34-35`
- Modify: `quant/decision/result.py` if adding distinct reason prefix (keep `gate_no`)
- Test: `tests/quant/decision/test_gate_pipeline_matrix.py`

- [ ] **Step 1: Failing test** — gate that raises → `GateResult(gate_no, False, "GATE_ERROR: ...")` and counter/log ERROR (not just reason string buried in block_reasons).
- [ ] **Step 2: Implement** — still fail-closed; distinguish prefix + ERROR log.
- [ ] **Step 3: Green; commit** `fix(gates): GATE_ERROR is fail-closed and logged, not a silent veto`.

### Task 9: Metrics canary + wire dead counters (B-6)

**Files:**
- Modify: `backend/app/core/metrics.py` (declare only what increments)
- Modify: `quant/engine/decision_loop.py:256` (`ticks_processed` per-decision mislabel — see review)
- Modify: `composition_root.py` set `deps["trades_executed"]` counter **or** delete the dead counter
- Delete or fix: `quant/execution/coordinator_metrics.py` (D7 — if this task runs before Wave 3, prefer delete-with-D7; if metrics wanted, fix attribute names and wire `/api/metrics/summary`)

**Locked decision:** **Delete** `coordinator_metrics.py` (D7) in Wave 3; Wave 9 only ensures `/api/metrics` series that remain actually increment (`ticks_processed_total` on real tick handler path, `decisions_evaluated_total`, `trades_executed_total` or remove).

- [ ] **Step 1: Failing tests** — after N ticks / M decisions / 1 paper trade, counter values match (unit-level, inject registry).
- [ ] **Step 2: Fix increment sites; delete or wire `trades_executed`.**
- [ ] **Step 3: Green; commit** `fix(metrics): counters increment; remove lying series`.

### Task 10: Bridge write failure latch (B-5 partial)

**Files:**
- Modify: `quant/events.py:228-235` or `quant/persistence_bridge.py` to set `PersistenceHealth` / snapshot `DEGRADED_BRIDGE_WRITE` on handler exception
- Test: `tests/quant/persistence` or event bus test

- [ ] **Step 1: Failing test** — storage.save raises → health latch set + snapshot field; not log-only.
- [ ] **Step 2: Implement latch** (same channel as event-append failure).
- [ ] **Step 3: Green; commit** `fix(persistence): latch bridge write failures`.

**Wave 2 exit gate:** health/feed tests + decision/amt/pipeline/metrics/persistence tests green; merge-gate sample; ledger line `Wave 2 complete`.

---

## Wave 3 — Zero-risk deletions (D1–D20 safe subset)

Parallelizable via **dispatching-parallel-agents** ONLY for non-overlapping files; **subagent-driven-development still one implementer at a time** per its rules — execute sequentially unless tasks touch disjoint paths AND controller serializes commits. Default: **sequential tasks**.

### Task 11: D1 + D3 + D11 (pure dead, no test retarget)

**Files:** `quant/decision/data_quality.py`, `backend/app/application/di/container.py`, `backend/app/application/di/composition_root.py`, `backend/app/api/dependencies.py`, `backend/app/main.py`, `backend/tests/integration/test_frontend_integration.py:26`

- [ ] Step 1: Confirm grep 0 prod callers for each (evidence in review §3).
- [ ] Step 2: Delete `conviction_allowed`, `_ALLOWED_CONVICTION`, `container.register`, `Configuration` singleton binding, `MarketDataDep`/`ActiveSymbolsDep`, `app.state.graph`/`service_graph` lines + vestigial test write.
- [ ] Step 3: `pytest tests/quant/decision/test_single_data_quality_authority.py backend/tests/unit/application tests/architecture -q --timeout=30` → green.
- [ ] Step 4: Commit `chore: remove dead DI and data-quality shims (D1,D3,D11)`.

### Task 12: D2 pyramid duplicate + engine/__init__ trim

- [ ] Step 1: Retarget `tests/quant/test_eod_force_close.py` imports → `from quant.engine.exit_manager import close_lingering_pyramids`.
- [ ] Step 2: Delete `quant/runtime.py` copy (`:189-283`); drop re-export from `quant/engine/__init__.py`.
- [ ] Step 3: `pytest tests/quant/test_eod_force_close.py tests/quant/test_exit_manager.py -q --timeout=30` → green.
- [ ] Step 4: Commit `refactor: single close_lingering_pyramids in exit_manager (D2)`.

### Task 13: D4 + D7 + D14 + D15 (no-ops and dead params)

- [ ] Step 1: Delete analyzer `:686-706` dead statements (+ `:693`); delete `coordinator_metrics.py` + `test_coordinator_metrics.py`; remove `timesfm_forecast` param + 2 pass-throughs; delete bias aggregators `runtime:443-452`.
- [ ] Step 2: `pytest tests/quant/amt/test_analyzer.py tests/quant/execution -q --timeout=60` (VA-clamp known red — no NEW fails).
- [ ] Step 3: Commit `chore: delete dead analyzer lines, coordinator_metrics, timesfm_forecast, bias aggregators`.

### Task 14: D5 + D6 + D16 (files and artifacts)

- [ ] Step 1: `git rm quant/contracts/options_converter.py backend/app/infrastructure/storage/sqlite_storage.py`; `git rm quant/decision/gap_architecture.workflow.html quant/decision/gap_architecture.workflow.json` **only if** `test_repo_hygiene` forbids or review D16 says remove — also `git rm` tracked `automation/reports/monitor_report_*.json` and extend `tests/architecture/test_repo_hygiene.py` FORBIDDEN_PREFIXES with `automation/reports/`, `quant/decision/*.workflow.*`.
- [ ] Step 2: `pytest tests/architecture/test_repo_hygiene.py tests/architecture -q`.
- [ ] Step 3: Commit `chore: remove dead modules and tracked artifacts (D5,D6,D16)`.

### Task 15: D9 + D17 (selector lots, keep_highest)

- [ ] Step 1: Delete `selector.compute_lot_size` + `compute_option_lot_size`; rehome 4 tests in `tests/quant/decision/test_option_signal_translation.py` to `SessionRisk.position_size` **or** delete redundant assertions if they only tested the dead function (prefer rehome).
- [ ] Step 2: Delete `keep_highest` param + fix docstring; delete or flip `test_lvn_keeps_lowest_strength_in_cluster` to match always-max policy (this clears 1 known red).
- [ ] Step 3: `pytest tests/quant/decision/test_option_signal_translation.py tests/quant/amt/profile/test_lvn_detector.py -q`.
- [ ] Step 4: Commit `chore: drop dead selector sizing and ignored keep_highest (D9,D17)`.

### Task 16: D10 + D12 + D13 + D18

- [ ] Step 1: Delete `PerEntityCircuitBreaker`, `get_position_circuit`; remove write-dead globals from `/metrics` display **or** wrap AMT/session ops — **locked: remove from metrics endpoint** (decorative today).
- [ ] Step 2: Delete no-op settings line, `GapFillConfig` + yaml `gap_fill:`, `short_signals_enabled` from 4 yamls + loader/validator refs.
- [ ] Step 3: Delete `detect_gap_fill_fade` + `test_gap_fill_fade.py` + `ctx.gap_profile_*` + builder mapping (keep DTO `gapProfile*` keys).
- [ ] Step 4: Delete DTO aliases `departedAndReapproached`, `driveDepartedAndReapproached`; simplify `context_builder:318-324` and `submission_handler:348` to single `driveEntryValid` read (coordinate with Wave 4 DriveTracker — if Wave 4 not started, only remove unused alias reads carefully; **if tests reference aliases, update tests in same commit**).
- [ ] Step 5: Green subset; commit `chore: dead config, resilience, gap-fade, drive aliases (D10,D12,D13,D18)`.

**Wave 3 exit:** merge-gate + `pytest tests/architecture -q` green; ledger `Wave 3 complete`.

---

## Wave 4 — SSoT deepening (architecture top picks)

Each task = one sibling plan expansion if needed; TDD parity test first.

### Task 17: SessionClock (8 clocks → 1)

**Files:** `quant/contracts/timezones.py` (authority), `quant/amt/session/context.py` (phase table + delete `MCX_SUB_SESSIONS` or reconcile), `quant/decision/gate_session_phase.py` (delete hardcoded clock + `_parse_time` — call `get_session_info`), `brokers/broker/market_info.py` `is_market_open` → delegate, `quant/probability/features.py` derive, tests `test_gate1_phase_permissions.py`, new `tests/architecture/test_session_clock_consistency.py`.

- [ ] Step 1: **Failing parity test** — for a table of timestamps × {NSE,MCX}, `gate_session_phase` decision ≡ `session_gates.allow` ≡ `symbol_registry.is_market_open` (entry-window vs open-window assertions defined carefully: gate entry ⊆ open).
- [ ] Step 2: Reconcile MCX 23:00 vs 23:15 vs 23:30 — **owner rule:** phase table force-exit 23:00, market open until 23:30, gate 1 uses phase table only (no independent clock). Document in `context.py`.
- [ ] Step 3: Delete gate constants; market_info delegates; features derive hours from timezones.
- [ ] Step 4: Green; commit `refactor(session): SessionClock single authority`.

### Task 18: InstrumentRegistry parity (GOLD/GOLDM)

- [ ] Step 1: **Failing parity test** — load `instruments.json` lot/tick vs `instrument_registry._SPECS` for every root; currently GOLD/GOLDM fail.
- [ ] Step 2: Fix `instruments.json` GOLD=100, GOLDM=10 (registry truth); remove lot/tick/strike from json if only used for display — futures_provider reads session/range_bar only; strip lot/tick keys or make loader ignore them.
- [ ] Step 3: Remove `market_info` independent STEP tables (derive registry); remove selector lot fallbacks (raise via registry).
- [ ] Step 4: Extend RULE-13 to validate instruments.json if it still carries numeric specs.
- [ ] Step 5: Green; commit `fix(instruments): registry is SSoT; fix GOLD/GOLDM swap`.

### Task 19: DecisionContext single owner

- [ ] Step 1: Extract `ContextSource` (or make `DecisionContextBuilder` the sole entry); three `_build_context` wrappers become one-line calls with **one** position expression `pm.current_position or state.position` (per dual-authority direction — pick pm-first for execution book, state fallback, **same in all three**).
- [ ] Step 2: Failing tests: authority tests stop needing `loop._build_context = lambda` — construct via builder.
- [ ] Step 3: Thread `range_bars_*` through all paths (fixes thesis-flip warmup gap).
- [ ] Step 4: Green; commit `refactor(context): one DecisionContext construction owner`.

### Task 20: Drive departure first-class (top architecture candidate)

- [ ] Step 1: Failing tests — feed `[100, 106, 100]` → D2 without tests knowing `DEPARTURE_TICKS`; clear 4 drive + 2 setup_lifecycle red if root cause is interface (else fix tracker logic under TDD).
- [ ] Step 2: `DriveTracker.observe(...)` owns departure; DTO emits `departed` + `driveCount` + `entryValid` (not 4 aliases); `SetupEvidence` derives from tracker.
- [ ] Step 3: Resolve SECOND_DRIVE trend vs reversion — **owner decision required** before merging model_router vs gate tables; default proposal: SECOND_DRIVE = reversion (matches gate_session_phase + broker_mapper); change `model_router._TREND_SETUPS` to remove it **only after** product sign-off recorded in ledger.
- [ ] Step 4: Green incl. previously red drive/setup tests; commit `feat(drive): departure as first-class observation`.

**Wave 4 exit:** merge-gate; known red only remaining signed items; ledger.

---

## Wave 5 — Persistence honesty + Day-1 (B-5 rest, alerts)

### Task 21: Document + test real rebuild path
- [ ] Fix docs claiming EventStore fold rebuilds positions — code uses SQLite+seed (`runtime:856-859`); add test that restart restores from rows; either implement journal replay **or** mark journal write-only in docs (locked: **docs + test the SQLite path; no new replay engine this program**).
- [ ] Non-lifecycle publish-before-append: add comment + crash-window test or flip StopMoved to append-first — **locked: flip StopMoved to append-before-publish** for consistency (TDD).

### Task 22: Day-1 alert runbook
- [ ] Add `docs/runbooks/2026-09-23-day1-alerts.md` with the review §E4 list mapped to `/health`, `/health/ready`, log patterns, `/api/metrics` canaries.
- [ ] No code.

**Wave 5 exit:** persistence tests + docs; program merge-gate.

---

## Final — Program closeout

- [ ] Dispatch final whole-branch review (subagent-driven-development final reviewer + requesting-code-review template) on `WAVE0_BASE..HEAD`.
- [ ] Full merge gate + `pytest tests/system backend/tests/unit/infrastructure/test_dhan_ledger_truthfulness.py`.
- [ ] Restart `./start.sh mcx clean` (or nse); verify `/health` feed block, 0 late_tick flood, decisions flowing.
- [ ] Update review doc: blockers B-1..B-9 → status table.
- [ ] finishing-a-development-branch (merge/PR decision — human).

---

## Parallelism map (dispatching-parallel-agents where safe)

| Safe parallel investigations | Never parallel edits |
|------------------------------|----------------------|
| Triage tests/system vs ledger (different files) — still **commit serially** | Same file (feed, health, context) |
| Wave 3 D-tasks on disjoint files after Wave 2 | Money-path + gates concurrently |
| Explore/root-cause subagents in parallel | Multiple implementers (SDD rule) |

## Progress ledger hooks

After each task review clean: append `Task N: complete (commits <base>..<head>, review clean)` to `.superpowers/sdd/progress.md`.
