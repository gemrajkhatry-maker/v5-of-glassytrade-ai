# Wave-5 Plan: Architecture Review Follow-Up (money path, event loop, contract)

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development. Four parallel lanes
> (A–D) in worktrees; lanes own disjoint files. Checkbox tracking.

**Goal:** Close the defects surfaced by the 2026-08-29 read-only architecture review
(`.workbuddy-ai/memory/2026-08-29.md`). Ordered by blast radius, not by effort:

1. The cross-engine risk ceiling barely binds — `PortfolioRiskAuthority` allows 95% of capital
   as open risk and 95% as realized loss before the global kill fires.
2. A non-idempotent `POST /orders` is retried up to 3× on network error, and the broker-side
   dedup key is missing on the two close paths most likely to be retried. **This can duplicate
   live orders.**
3. Two critical startup health checks are hardcoded `"ok"`, so readiness asserts what it never tests.
4. CPU-bound `deepcopy` + recursive deep-compare runs on the asyncio event loop at 2 Hz × N symbols.
5. Money is `float` end-to-end in the execution path while `Portfolio` uses `Decimal`.

Everything else the review found is either small enough to fold into a lane or deferred
with a note — see **Deferred**.

**Architecture:** No new abstractions. Lane A tightens existing limits and unifies capital state.
Lane B makes the HTTP retry layer method-aware and closes the idempotency gap. Lane C moves
snapshot work off the event loop and makes two health checks real. Lane D removes the third
copy of the WS contract and fixes frontend render churn. Every deliberate ceiling carries a
`# ponytail:` comment.

**Tech Stack:** Python 3.13, pytest, React 19 + vitest. No new dependencies.

## Global Constraints

- Base: `2602fe0` · Branch: `fix/w5-money-safety`
- Lanes: worktrees `../v5-w5-lane{A,B,C,D}`, branches `w5-{A,B,C,D}`
- `.venv/bin/python -m pytest`; stage ONLY explicit paths; **NEVER `git add -A`**
  (the working tree carries unrelated user WIP)
- Every task starts with a **failing test** that reproduces the defect, then the fix
- Validation per lane: targeted suites + FULL `tests/quant -q`, `backend/tests -q`,
  and `frontend` `npm test` (Lane D only). Document base pre-existing failures, never fix around them
- Small diffs. If a task wants to grow past ~150 lines of change, stop and ledger it

---

## Lane A — `quant/execution` + `quant/multi_engine.py` (risk ceiling, capital, money)

### Task A1: `PortfolioRiskAuthority` limits must actually bind

Today: `quant/execution/portfolio_risk.py:28-29` ships
`max_portfolio_risk_pct=0.95` and `max_portfolio_daily_loss_pct=0.95`. On ₹10L that permits
₹9.5L of aggregate open risk and a ₹9.5L realized loss before the global kill fires — the
cross-engine ceiling this class exists to provide effectively does not exist. The comment
literally says "aggressive".

**Files:** `quant/execution/portfolio_risk.py`, `quant/multi_engine.py` (construction site ~:260),
new `tests/quant/execution/test_portfolio_risk_limits.py`

- [ ] **Step 1: Failing test** — construct a 4-engine book where each engine is individually
      within `SessionRisk` limits; assert the authority rejects the 3rd/4th entry under the new
      caps, and that a realized loss at the new daily cap halts new entries.
- [ ] **Step 2:** Replace the 0.95 defaults with conservative values (open risk ≈ 3× the
      per-trade risk, daily loss ≈ 3× the per-symbol daily cap) and thread them from
      configuration rather than literals — the plan deliberately does **not** hardcode a number
      here; the implementer derives it from `risk_per_trade_pct` and `max_daily_loss_pct` already
      in `SystemConfig`. `# ponytail:` the derivation.
- [ ] **Step 3:** suites `tests/quant/execution -q tests/quant -q`.
      Commit: `fix(quant): make portfolio risk ceiling bind — derive caps from config, not 95%`

### Task A2: One capital book, not one per engine

Today: `quant/multi_engine.py:1002-1003` builds a **fresh** `Portfolio()` per live engine, so
N `LiveOMS` instances each hold a full ₹10L book. Capital state is duplicated N ways with no
reconciliation between them.

**Files:** `quant/multi_engine.py` (`:1002-1014`), `quant/execution/live_oms.py`,
new `tests/quant/execution/test_shared_portfolio.py`

- [ ] **Step 1: Failing test** — two engines, each entering a position; assert the shared book
      reflects both, and that a drawdown in engine 1 throttles sizing in engine 2.
- [ ] **Step 2:** Hoist a single `Portfolio` to the coordinator and pass it to every
      `LiveOMS`. Verify `IBroker.execute_order` consumers (`dhan_broker_adapter.py`) tolerate a
      shared, concurrently-mutated book — if any path assumes engine-local ownership, ledger it
      and add the guard rather than reverting to per-engine books.
- [ ] **Step 3:** `tests/quant -q`. Commit: `fix(quant): share one capital book across engines`

### Task A3: `Decimal` money in the execution path

Today: `quant/execution/order.py` is `open_price: float`, `size: float`, `realized_pnl: float`,
`pnl: float`; `Position`, `Fill`, and `Signal` follow suit. Meanwhile
`quant/contracts/aggregates.py::Portfolio` uses `Decimal` — and `quant/ws_adapter.py:32-33`
converts it straight back to float at the WS boundary. Two numeric regimes meet at the edge.

**Files:** `quant/execution/order.py`, `quant/position_manager.py`, `quant/execution/oms.py`,
`quant/execution/live_oms.py`, `quant/execution/risk.py`, new
`tests/quant/execution/test_decimal_money.py`

- [ ] **Step 1: Failing test** — a laddered exit sequence where float accumulation gives a
      different realized P&L than exact decimal arithmetic (pick quantities/prices that expose
      it, e.g. repeated 0.1 steps); assert exact equality with the decimal result.
- [ ] **Step 2:** Migrate `Position` / `Fill` / `Signal` money fields to `Decimal`. Keep the
      WS boundary float (frontend is JS) but make the conversion explicit and single-sited.
      `# ponytail:` every remaining float boundary.
- [ ] **Step 3:** `tests/quant -q tests/quant/execution -q`.
      Commit: `refactor(quant): decimal money across the execution path`

> Lane A owns `quant/execution/*` and `quant/multi_engine.py`. If A3 proves larger than ~150
> lines, land A1+A2 and ledger A3.

---

## Lane B — `brokers/` + `backend/app/infrastructure/adapters/` (order safety)

### Task B1: Never auto-retry a non-idempotent order POST

**This is the highest-severity defect in the review.** Today: `http_client.py:485-513` retries on
`DhanNetworkError` and `aiohttp.ClientError` for **all methods, including `POST /orders`**, up to
`max_retries=3`. A request that reached Dhan but lost its response gets re-sent. Since 5xx maps to
`DhanNetworkError`, a broker-side blip can duplicate a live order. `DhanTimeoutError` and
`DhanRateLimitError` are already correctly excluded — only the network path is wrong.

**Files:** `brokers/broker/dhan/infrastructure/http_client.py`,
new `brokers/tests/test_order_retry_safety.py`

- [ ] **Step 1: Failing test** — a `POST /orders` that succeeds server-side but raises
      `DhanNetworkError` on response read; assert exactly **one** request was attempted and the
      caller receives an `OrderStateUnknown` signal (not a silent success, not a retry).
- [ ] **Step 2:** Make `_execute_with_retry` method-aware: never auto-retry non-idempotent verbs.
      Surface a distinct error so callers can reconcile via `get_order_status` instead.
- [ ] **Step 3:** `brokers/tests -q` + `backend/tests -q`.
      Commit: `fix(broker): never retry non-idempotent order POST`

### Task B2: Idempotency key on every order path

Today: `dhan_broker_adapter.py:220` sets `order.user_order_id` (→ broker `correlationId`) on the
`execute_order` path only. `close_position` (`:386-394`) and `_market_fallback_close` (`:652-660`)
do **not** — and those are exactly the paths Task B1 stops from being blindly retried, so they
need the dedup backstop most.

**Files:** `backend/app/infrastructure/adapters/dhan_broker_adapter.py`,
`tests/backend/unit/infrastructure/test_dhan_broker_adapter.py` (extend)

- [ ] **Step 1: Failing test** — assert a stable, deterministic `user_order_id` is present on
      close orders and on the market-fallback close, and that it differs per logical close
      (not per retry).
- [ ] **Step 2:** Set it on both paths. Derive it from position id + close reason, not from
      wall-clock, so a retry carries the same key.
- [ ] **Step 3:** `backend/tests -q`. Commit: `fix(broker): idempotency key on close + fallback close`

### Task B3: Delete dead `retry_on_status` config

`http_client.py:97` defines `retry_on_status = (408, 429, 500, 502, 503, 504)` and **nothing reads
it** — retry behavior is governed by exception type. Anyone tuning that tuple gets no effect, which
is worse than not having it.

**Files:** `brokers/broker/dhan/infrastructure/http_client.py`
- [ ] Remove the field (or wire it, if B1's design wants status-driven retry — prefer removal;
      exception-driven is the correct model here). Commit: `chore(broker): drop dead retry_on_status`

### Task B4: Dropped WS ticks must be observable

Today: `brokers/broker/dhan/infrastructure/websocket_client.py:434-440` handles `QueueFull` by
dropping the oldest message with **no counter and no log**. A stalled consumer silently loses
ticks and nothing downstream can tell.

**Files:** `brokers/broker/dhan/infrastructure/websocket_client.py`, `brokers/tests/`
- [ ] Add a monotonic drop counter, log at WARN on first drop and periodically (not per packet),
      and expose the counter for the health/observability router.
      Commit: `fix(broker): count and log dropped websocket ticks`

---

## Lane C — `backend/app` (shell integrity + event loop)

### Task C1: Make the two fake startup health checks real

Today: `backend/app/main.py:95-96`:
```python
checks["strategy_runtime"] = "ok"  # QuantCoordinator owns the decision brain
checks["position_close_contract"] = "ok"  # delegated to the coordinator/broker
```
Both keys are in `critical_keys` (`:117-124`), which decides `ok` vs `degraded`. Readiness
therefore reports two critical checks as unconditionally green.

**Files:** `backend/app/main.py`, `backend/tests/unit/test_startup_contracts.py` (new)

- [ ] **Step 1: Failing test** — a coordinator that is missing / failed to start, and a broker
      without a close contract; assert status is `degraded` and each check names its failure.
- [ ] **Step 2:** Actually probe both: `strategy_runtime` verifies the coordinator resolved and
      `start()` did not fail (`app.state.engine_start_failed`); `position_close_contract` verifies
      the broker exposes `close_position` and the coordinator exposes a halt/close path.
- [ ] **Step 3:** `backend/tests -q`. Commit: `fix(backend): make startup health checks real`

### Task C2: Get snapshot diffing off the asyncio event loop

Today: `backend/app/api/websocket/gameloop.py:344-350` polls `coordinator.snapshot(s)` **synchronously
on the event loop** for every symbol every 0.5s, then runs `copy.deepcopy` (`:310`, `:350`) and
recursive `_deep_equal` (`:46-72`) over the whole snapshot. That is CPU-bound work on the loop that
also serves HTTP — 8 symbols × 2 Hz.

Compounding it: `_compute_delta` is **top-level-key granularity**. One changed leaf inside the
~60-field `amt` DTO re-sends the entire blob, so the compression under-delivers exactly when the
payload is largest.

**Files:** `backend/app/api/websocket/gameloop.py`, `backend/tests/unit/test_gameloop_delta.py` (new)

- [ ] **Step 1: Failing/benchmark test** — measure event-loop blocking for 8 symbols over ~10
      cycles; assert a bound. Then assert a delta containing only one changed `amt` leaf is
      smaller than the full `amt` blob.
- [ ] **Step 2:** Move snapshot retrieval + diff computation into a worker thread
      (`asyncio.to_thread`) and await it; only `ws.send_json` stays on the loop.
- [ ] **Step 3:** Diff the large nested blobs (`amt`, `portfolio.positions`) one level deeper so a
      single changed leaf does not resend the whole structure. `# ponytail:` any remaining
      coarse key.
- [ ] **Step 4:** `backend/tests -q`. Commit: `perf(backend): offload ws delta computation, diff nested blobs`

---

## Lane D — WS contract + `frontend/`

### Task D1: One source of truth for the WS contract

Today the snapshot shape is hand-mirrored in **three** places: `quant/ws_contract.py` (the
`WSSnapshot` dataclass), `quant/ws_adapter.py::view_state_to_ws`, and `frontend/types.ts`.
`ws_contract.py` itself says "Generate TypeScript types (future)" — so drift is manual and
silent. `validate_ws_snapshot` exists but nothing calls it in the send path; it is test-only.

**Files:** `quant/ws_contract.py`, `quant/ws_adapter.py`, `frontend/types.ts`,
`backend/app/api/websocket/gameloop.py`

- [ ] **Step 1:** Make `view_state_to_ws` build through `WSSnapshot` so there is exactly one
      producer of the wire shape.
- [ ] **Step 2:** Call `validate_ws_snapshot` on the send path in dev/test builds (guard by env —
      never allocate this on the hot path in prod) and log loudly on drift.
- [ ] **Step 3:** Add a contract test that fails when `frontend/types.ts::InstrumentState` keys
      diverge from `WS_SNAPSHOT_KEYS`. `# ponytail:` real codegen remains future work.
- [ ] Commit: `chore(contract): single ws snapshot producer + drift test`

### Task D2: Frontend render and type correctness

Small, independent, all in one lane:

- `frontend/App.tsx:48` — `useMemo(() => Object.keys(instruments), [Object.keys(instruments).join(',')])`
  is a stringly-typed dependency array; it works but defeats `exhaustive-deps` and breaks if two
  symbol sets ever stringify alike. Depend on `instruments` directly and memoize the keys.
- `frontend/hooks/useServerTradingSystem.ts:686` — `instruments[activeSymbol] || createInstrumentState(...)`
  allocates a fresh object **every render** while the symbol is pending, breaking referential
  equality for every downstream consumer. Hoist to a `useMemo`.
- `:690-701` — `isHalted` / `haltReason` recompute over all instruments on every render, unmemoized.
- 112 `any` usages frontend-wide. Not required to clear all, but the WS-visible ones should go:
  `useServerTradingSystem.ts:289` (history mapping), `:458` (`merged: any`), and
  `ChartScene.tsx:267,272` (stashing `_lastW`/`_lastH` on the chart instance via `as any` — use a ref).
- `ChartScene.tsx:1115` — the `React.memo` comparator compares only `data.length`, so an in-place
  update to the last candle of equal length never re-renders. That is *intentional* (ticks arrive
  via `tickBus`), but it means chart state has two update paths and the coupling is implicit.
  Document it at the comparator and add a regression test pinning the split.

**Files:** `frontend/App.tsx`, `frontend/hooks/useServerTradingSystem.ts`,
`frontend/components/ChartScene.tsx`, `frontend/tests/`

- [ ] Commit: `fix(frontend): stable instrument identity, memoized halt state, typed ws mapping`

---

## Deferred (ledgered, not this wave)

- **`AMTAnalyzer.analyze()` is a single ~460-line method** (`quant/amt/analyzer.py:355-818`) — the
  largest maintainability problem in `quant/`, but splitting it is a behavioral-refactor risk that
  needs its own wave with golden-trace parity, not a passenger here.
- **God objects**: `auth_provider.py` (1094), `symbol_mapper.py` (912),
  `dhan_broker_adapter.py` (1082), `storage/database.py` (990), `trade_journal.py` (1031).
  Split opportunistically when a lane touches them for another reason.
- **`brokers/` DI inversion is cosmetic** — `DhanBroker.create()` imports concrete infra
  (`broker.py:186,215`) and mutates private attrs (`:243-245`). Ports are not substitutable
  without editing application code. Fix when the library next gains a second adapter.
- **`backend/app/domain/` is empty** (3 telemetry helpers, 384 LOC, no entities). The backend is a
  transport shell over `quant/`, which is a defensible design — the directory names just oversell
  it. Rename or populate; do not do both.
- **No `modify_order`** anywhere in the broker port or backend. Order status is a bare string
  (`entities.py:691`, `status: str = "PENDING"`) with set-membership predicates and **no transition
  validation** — nothing prevents `REJECTED → FILLED`. Worth a dedicated order-state-machine task.
- **Dead code / stale comments**: `quant/runtime.py:1193 _check_pyramid` is defined but never
  called from production (pyramiding itself *is* live via `position_manager.py:227-228` — only the
  wrapper is orphaned). `quant/contracts/ports/broker.py:11` claims `LiveOMS` "is currently dead
  code", which is stale — it is wired at `multi_engine.py:1005`. Both are one-line deletions;
  sweep them at the end of the wave rather than burning a task.
- **Repo hygiene**: 8+ AI-agent config dirs in root, a bundled `backend/venv/` (9,878 files), a
  2.4 MB `backend_e2e.log`, two `glassytrade.db`. Gitignore cleanup, no code risk.

## Self-Review

Every task opens with a failing test that reproduces the observed defect, so "did it work" is
decided by the suite rather than by inspection. Lane file ownership is disjoint (A: `quant/execution`
+ `multi_engine`; B: `brokers/` + `backend/.../adapters`; C: `backend/app` minus adapters; D:
`frontend/` + `quant/ws_{contract,adapter}`), so the four lanes can run without merge conflict —
the one overlap is `quant/ws_adapter.py` in Lane D, which nothing else touches. A3 is the largest
task and is explicitly capped; if it outgrows the cap it gets ledgered rather than rushed, because
a half-migrated numeric regime is worse than a consistently float one.
