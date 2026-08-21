# Stable Futures/Options Startup and Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current `stable_6` worktree use one coherent futures/options startup and market-data flow so option AMT profiles are populated, startup snapshots are complete, and unchanged profiles do not redraw the chart every tick.

**Architecture:** Keep `QuantCoordinator` and `MultiplexedMarketFeed` as the owners. Build the current futures topology before accepting persisted contracts, validate the persisted cache against that topology, and pass one option→futures mapping through engine creation. Futures engines consume primary queues; option engines consume dedicated reader copies. Register engines before starting threads. Keep the existing frontend value comparison as the only redraw guard.

**Tech Stack:** Python 3.13, pytest, stdlib queues/locks, FastAPI WebSocket deltas, React/TypeScript, Vitest, Vite.

## Global Constraints

- Modify the current worktree; do not reset or discard existing user changes.
- No new dependencies, coordinator, producer loop, WebSocket, cache abstraction, or render abstraction.
- Do not change AMT thresholds, trading gates, sizing, or strategy behavior.
- Persisted contracts are a cache; never delete them before replacement selection succeeds.
- Every non-trivial behavior change gets a focused regression test.
- Keep unrelated pre-existing scanner failures separate.

---

### Task 1: Validate persisted contracts against the futures topology

**Files:**
- Modify: `quant/multi_engine.py`
- Test: `tests/quant/test_multi_engine_startup.py` (create if absent)

**Interfaces:** `QuantCoordinator._scan()` continues returning `list[str]`; topology validation remains internal to the coordinator.

- [x] Add failing tests for: option-only persisted files are rejected when futures are enabled; complete futures+options files are reused; exchange-mismatched files are rejected.
- [x] Run: `pytest -q tests/quant/test_multi_engine_startup.py -vv`; confirm the option-only case fails against current behavior.
- [x] Resolve required futures before accepting a persisted selection. Accept the cache only when every required future is present and persisted options map to those futures; otherwise use the existing scanner path.
- [x] Bound option slots so total engines do not exceed configured `n`: `max(0, total_slots - len(futures_symbols))`. Do not silently start extra engines.
- [x] Run: `pytest -q tests/quant/test_multi_engine_startup.py -vv`.

### Task 2: Build one authoritative option→futures mapping

**Files:**
- Modify: `quant/multi_engine.py`
- Test: `tests/quant/test_multi_engine_startup.py`

**Interfaces:** `_spawn_engine(symbol, underlying_symbol=None)` or an equivalent existing signature; mapping is produced once during startup/rescan.

- [x] Add a failing test covering NIFTY and BANKNIFTY options and proving roots cannot cross-map.
- [x] Resolve roots once with `ExchangeConfig.for_exchange(exchange).extract_underlying()` and build `futures_by_root` plus `option_underlyings` during topology construction.
- [x] Pass the resolved future into `_spawn_engine`; remove per-spawn dictionary reconstruction.
- [x] Preserve the existing explicit premium fallback only for unmapped options, with one startup log naming the option/root.
- [x] Run: `pytest -q tests/quant/test_multi_engine_startup.py -k mapping -vv`.

### Task 3: Make engine registration and reader lifecycle race-safe

**Files:**
- Modify: `quant/multi_engine.py`
- Modify: `quant/brokers/multiplexed_feed.py`
- Modify: `quant/brokers/live_gateway.py`
- Test: `tests/quant/test_multi_engine_startup.py`
- Test: `tests/quant/test_multiplexed_feed.py`

**Interfaces:** Primary gateways keep current behavior; reader gateways receive copied ticks and close with the same `None` sentinel semantics.

- [x] Add a lifecycle test proving an engine is visible in `_engines` before its thread can snapshot.
- [x] Register engine, gateway, thread, and optional reader gateway under the coordinator lock before `thread.start()`.
- [x] Add a two-reader test proving primary, reader one, and reader two each receive every ordered futures tick.
- [x] Add a shutdown test proving closing one reader does not unsubscribe the futures primary queue and all blocked readers unblock.
- [x] Run: `pytest -q tests/quant/test_multi_engine_startup.py tests/quant/test_multiplexed_feed.py -vv`.

### Task 4: Verify option AMT uses futures while quotes remain option-local

**Files:**
- Modify: `tests/quant/test_underlying_feed.py`
- Modify: `tests/quant/test_multi_engine_startup.py`
- Modify implementation only if a test identifies a coordinator/feed boundary defect.

- [x] Add a synthetic coordinator test with one future and two options sharing its root.
- [x] Assert option bars/profile inputs use futures prices, option LTP/depth still use option ticks, and the futures primary stream is not starved.
- [x] Run: `pytest -q tests/quant/test_multi_engine_startup.py tests/quant/test_underlying_feed.py tests/quant/test_multiplexed_feed.py -vv`.
- [x] Do not modify `QuantEngine` AMT logic or thresholds to make this test pass.

### Task 5: Lock down WebSocket delta and snapshot aliasing

**Files:**
- Modify only if required: `backend/app/api/websocket/gameloop.py`, `quant/state.py`
- Test: `tests/test_gameloop_delta.py`

- [x] Add/extend a test proving a later snapshot mutation cannot mutate the previous delta baseline.
- [x] Prove unchanged nested AMT/profile content does not produce a false delta while live quote changes still do.
- [x] Keep deep-copying at the WebSocket boundary; do not add copies throughout the projector without a failing test.
- [x] Run: `pytest -q tests/test_gameloop_delta.py backend/tests -k 'delta or coordinator' -vv`.

### Task 6: Preserve chart redraw stability

**Files:**
- Modify only if required: `frontend/components/ChartScene.tsx`
- Test: `frontend/tests/components/ChartScene.test.tsx`

- [x] Add a regression test using two separately decoded but equal profile-object arrays.
- [x] Keep value comparison limited to overlay-rendered fields; do not add JSON stringification or another throttle/cache layer.
- [x] Run from `frontend/`: `npx tsc --noEmit`, `npm test -- --run`, and `npm run build`.

### Task 7: Final duplicate-flow and scope review

**Files:** All files changed by Tasks 1–6.

- [x] Search: `rg -n 'extract_underlying|add_reader|underlying_gateway|thread.start|warmHistoryForSymbols' quant backend frontend`.
- [x] Confirm one startup mapping, one feed producer, one reader registration path, and one frontend profile stabilization path.
- [x] Run: `git diff --check` and `python -m compileall -q quant backend/app`.
- [x] Run the focused Python suite, all frontend tests, type-check, and build.
- [x] Report unrelated scanner failures separately; do not modify them as part of this work.
- [x] Review `git diff --stat` and `git status --short`; preserve unrelated user files and do not perform cleanup or merge actions without approval.

---

## Verification Evidence (run against the working tree, 2026-08-20)

All gates green; nothing was committed (user asked to check only).

- **Python (plan-scoped):** `pytest tests/quant/test_multi_engine_startup.py tests/quant/test_multiplexed_feed.py tests/quant/test_underlying_feed.py tests/test_gameloop_delta.py -q` → **28 passed**.
- **Frontend:** `npm test -- --run` → **206 passed** (19 files); `npx tsc --noEmit` → clean; `npm run build` → built in 6.76s.
- **`git diff --check`** → clean. `python -m compileall -q quant backend/app` → clean.
- **Backend log (live, not assumed):** all 6 option contracts log `wiring AMT on underlying futures feed <ROOT> FUT` (CRUDEOIL/GOLDM/SILVERM CALL+PUT); count of `"running AMT on the option premium"` warnings = **0**.
- **Unrelated failures kept separate:** `tests/integration/test_fabio_india_scenarios.py` (untracked, not in plan scope) has 4 failures from pre-existing API drift (`DecisionContext(setup_evidence=...)`, `SessionRisk.position_size(lot_size=...)`). Not modified.

**Working-tree diff (uncommitted):** `quant/multi_engine.py`, `quant/brokers/multiplexed_feed.py`, `quant/brokers/live_gateway.py`, `frontend/components/ChartScene.tsx`, `frontend/components/MarketSidebar.tsx`, `frontend/vite.config.ts`, plus test files. See `git status --short`.
