# WS-DHANDUP — Broker adapter dedup + DhanFacade liveness verdict

**Worktree:** `/Users/apple/Documents/wt-ws-dhandup` (branch `migration/ws-dhandup`). Work ONLY there.

**Context:** The ponytail audit flagged `DhanFacade` (1,151 lines) as a redundant one-liner API layer, but WS-PT-BROKERS kept it because `brokers/broker/dhan/application/broker.py` references it. Also, the backend has TWO broker adapters: `backend/app/infrastructure/adapters/dhan_adapter.py` (legacy) and `backend/app/infrastructure/adapters/dhan_broker_adapter.py` (new), plus the `brokers/` package's `DhanBroker`. This looks like a 3-layer broker stack.

**Tasks:**
1. **Map the stack:** read `brokers/broker/dhan/application/{facade.py, broker.py, __init__.py}` and `backend/app/infrastructure/adapters/{dhan_adapter.py, dhan_broker_adapter.py}`. Determine, with grep evidence:
   - Is `DhanFacade` genuinely reachable from any production path (not just its own test + scripts)? Who calls `DhanFacade` vs `DhanBroker` vs the adapters?
   - Do the two backend adapters (`dhan_adapter` vs `dhan_broker_adapter`) duplicate each other? Who uses each?
2. **Produce `docs/BROKER_STACK_REVIEW.md`** (in the worktree; do NOT commit — report its path) with a wiring diagram + the verdict: which layer is canonical, which is dead weight.
3. **Apply only SAFE removals:**
   - If `DhanFacade` is truly dead from production (only its test + scripts call it), delete it + its test, and re-point `brokers/broker/dhan/application/__init__.py` / `broker.py` if they re-export it.
   - If one backend adapter is dead (not wired in `composition_root.py`/`main.py`), delete it + its tests.
   - If both adapters are live, do NOT delete — report and recommend.
4. Guard: the live broker path (order placement, market data) must be unchanged. Verify the backend broker tests pass after any deletion.

**Verify:** `cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit/infrastructure/test_dhan*.py tests/unit/infrastructure/test_lot_size.py -q --tb=short` (must stay green) and `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest brokers/tests -q --tb=short` (from repo root).

**Commits:** `refactor(brokers): delete dead DhanFacade layer` (only if provably dead), and/or `refactor(backend): delete dead broker adapter` (only if provably dead).

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-dhandup-report.md` (wiring map + verdict + what was deleted). Reply: status, commits, test counts, concerns.
