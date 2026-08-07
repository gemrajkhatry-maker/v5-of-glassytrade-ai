# WS-DHANDUP — Broker adapter dedup + DhanFacade liveness verdict — REPORT

Worktree: `/Users/apple/Documents/wt-ws-dhandup` (branch `migration/ws-dhandup`)
Committed: `a787c22` `refactor(brokers): delete dead DhanFacade layer`

## Wiring map (with grep evidence)

```
  backend/app/application/di/composition_root.py
        │  register_singleton(IMarketData)          register_singleton(IBroker) [live]
        ▼                                           ▼
  dhan_adapter.py  DhanMarketDataAdapter     dhan_broker_adapter.py  DhanBrokerAdapter
        │  (composition_root.py:178-180)            │  (composition_root.py:183-189)
        └──────────────────┬────────────────────────┘
                           ▼
   brokers/broker/dhan/application/broker.py  →  DhanBroker   ← CANONICAL
                           ▲
   brokers/gateway.py:117 BrokerGateway(DHAN) also constructs DhanBroker directly

   brokers/broker/dhan/application/facade.py  →  DhanFacade   ← DEAD
```

| Layer | Reachable from production | Callers |
|---|---|---|
| `DhanFacade` (`application/facade.py`, 1,151 lines) | **NO** | only `dhan/__init__.py` + `dhan/application/__init__.py` re-exports, its own test `tests/test_facade.py`, and a code comment in `broker.py:747`. No `scripts/`, `backend/`, `quant/`, `frontend/` reference. |
| `DhanBroker` (`application/broker.py`) | **YES** | `brokers/gateway.py:117`; `dhan_adapter.py:103`; `dhan_broker_adapter.py:36`. |
| `dhan_adapter.py` (`DhanMarketDataAdapter`) | **YES** | `composition_root.py:178-180` (IMarketData port); `backend/scripts/verify_scanner_goldm_silverm.py:30`; unit tests. |
| `dhan_broker_adapter.py` (`DhanBrokerAdapter`) | **YES** | `composition_root.py:183-189` (IBroker port, live mode); unit tests. |

## Verdict

1. **`DhanFacade` is dead weight** — a redundant one-liner wrapper over `DhanBroker`, reachable from
   no production path (only its own test + package re-exports). **DELETED.**
2. **`DhanBroker` is canonical** — every live path (gateway, market-data adapter, order adapter)
   funnels through it. Kept unchanged.
3. **The two backend adapters are NOT duplicates and both are live** — they implement different ports
   (`IMarketData` vs `IBroker`), both wired in `composition_root.py`. **Neither deleted.** Per brief,
   since both are live: kept and recommend keeping; they intentionally share `DhanBroker`.

## What was deleted

- `brokers/broker/dhan/application/facade.py` (DhanFacade + `Trade` + `PnLReport` dataclasses, 1,151 lines)
- `brokers/broker/dhan/tests/test_facade.py` (675 lines, facade tests)
- Re-exports of `DhanFacade` / `Trade` / `PnLReport` removed from `brokers/broker/dhan/__init__.py`
  and `brokers/broker/dhan/application/__init__.py`; stale "used by DhanFacade" comment fixed in
  `broker.py:747`.

Guard note: `DhanExchangeResolver` (used by live `DhanBroker`) previously had its only test coverage
inside `test_facade.py`. To keep the live path's coverage, the resolver + `ResolvedExchange` tests
(16 tests) were split into a new `brokers/broker/dhan/tests/test_exchange_resolver.py` before the
facade test was deleted.

## Verification (green, unchanged from baseline)

- `cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit/infrastructure/test_dhan*.py tests/unit/infrastructure/test_lot_size.py -q --tb=short`
  → **37 passed**
- `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest brokers/tests -q --tb=short` (repo root)
  → **152 passed, 7 skipped** (1 pre-existing PytestUnknownMark warning on `integration` mark)
- `brokers/broker/dhan/tests/test_exchange_resolver.py` → **16 passed**
- `import brokers.broker.dhan` clean; no `DhanFacade`/`Trade`/`PnLReport` in `__all__`.

## Review doc

`docs/BROKER_STACK_REVIEW.md` written in the worktree — **NOT committed** (per brief, `docs/*.md` is
excluded from commits).

## Concerns

- None blocking. The pre-existing `PytestUnknownMarkWarning` (`integration` mark) and the 7 skips in
  `brokers/tests` predate this change and are unrelated.
