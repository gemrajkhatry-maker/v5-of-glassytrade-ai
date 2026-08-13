# Phase B2 — Delete Test-Covered Dead Backend Modules (Reviewed Wave)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax.

**Goal:** Resolve the 12 production-dead-but-test-covered backend modules deferred from Phase B, plus one production-dead utility with no test dead-code. This wave does NOT blindly delete tests — it classifies each module and handles it appropriately:
- **7 clean deletions** (module + its dedicated test file, nothing else tested)
- **1 test-fixture relocation** (`data_generator.py` is a synthetic-OHLCV generator used by 5 test files that test LIVE quant analyzers — it moves to `backend/tests/`, NOT deleted)
- **2 strategy deletions with surgical test trim** (NSE/MCX strategies, mixed test file)
- **1 dead-module deletion with trivial test cleanup** (`live_engine_server.py` — one unused `# noqa: F401` import)
- **1 migration to quant** (`application/utils.py` — `parse_symbol_metadata` + `is_market_open` are real domain logic with 9 passing tests and NO quant duplicate; they move to quant's canonical symbol home)

**Scope decision (user sign-off, 2026-08-08):** One wave for A (7 clean deletes) + B (move fixture) + C (3 trims). For `application/utils.py`: **migrate into quant** (preserve the 9 tests), do not delete.

**Audit-error corrections verified by coordinator:**
- `data_generator.py` is NOT dead — it's a deterministic synthetic OHLCV generator (`generate_market_data(days, start_price, regime)`) used as a test fixture by `test_amt_analyzer.py` (~20 call sites), `test_footprint_analyzer.py`, `test_session_reset.py`, `test_prediction_engine.py`, `test_phase1_leaf_components.py`. It moves to `backend/tests/` so those 5 LIVE-quant test files keep working.
- `application/utils.py` was flagged "duplicates quant" but `quant/amt/session/symbol_registry.py` only does exchange detection (`exchange_for`/`is_mcx`/`is_nse`/`is_option`) — it does NOT compute strike/DTE/moneyness (`parse_symbol_metadata`) or market hours (`is_market_open`). quant's `probability/features.py` consumes `moneyness_pct`/`dte_normalized`/`option_type_flag` — the exact fields `parse_symbol_metadata` produces. Migration target: `quant/amt/session/symbol_registry.py` (canonical symbol/exchange/option home, audit-nominated).
- `time_to_epoch()` (in `application/utils.py`) is FULLY dead (zero refs anywhere) — it is NOT migrated, only the two tested functions are.
- `test_feature_alignment.py` also has `test_feature_alignment_training_vs_live` + `test_probability_feature_contract_metadata` (lines 21-58) which test LIVE quant probability features — KEEP those.

## Files

**Delete (7 modules + their test files):**
- `backend/app/application/candle_aggregator.py` + `backend/tests/unit/application/test_lee_ready_spike.py` (6 tests, only CandleAggregator)
- `backend/app/core/llm_circuit_breaker.py` + `backend/tests/unit/core/test_llm_circuit_breaker.py`
- `backend/app/domain/ops/position_reconciliation.py` + `backend/tests/unit/domain/services/test_position_reconciliation.py`
- `backend/app/infrastructure/adapters/delta_profile_adapter.py` + `backend/tests/unit/test_delta_profile.py`
- `backend/app/infrastructure/adapters/lgbm_probability_adapter.py` + `backend/tests/unit/infrastructure/test_probability_adapter_contract.py`
- `backend/app/infrastructure/adapters/live_gateway.py` + `backend/tests/unit/infrastructure/test_live_gateway.py`
- `backend/app/shared/parsing.py` + `backend/tests/unit/test_shared_parsing.py`

**Move (1 test fixture):**
- `backend/app/infrastructure/adapters/data_generator.py` → `backend/tests/helpers/market_data.py` (create `backend/tests/helpers/__init__.py` if needed). Update 5 test files' imports from `from app.infrastructure.adapters.data_generator import generate_market_data` → `from helpers.market_data import generate_market_data` (or conftest-relative path — match existing test conventions).

**Delete + surgical trim (1 module, 1 test file):**
- `backend/app/infrastructure/strategies/nse_strategy.py` + `mcx_strategy.py`
- Trim `backend/tests/unit/domain/test_exchange_abstraction.py`: DELETE `TestNSEExchangeStrategy` (lines 202-231), `TestMCXExchangeStrategy` (lines 233-286), the two imports on lines 19-20, and the two consistency tests `test_mcx_strategy_uses_config_thresholds` + `test_nse_strategy_uses_config_thresholds` (lines 371-385). KEEP `TestExchangeConfig`, `TestSymbolRegistry`, `TestSessionContextFactory`, `TestExchangeConfigBridge`, `test_registry_matches_config_underlyings`, `test_di_container_wiring` (Phase A-modified), `test_no_domain_imports_config`.

**Delete + trivial test cleanup (1 module, 1 test file):**
- `backend/app/infrastructure/adapters/live_engine_server.py`
- `backend/tests/unit/infrastructure/test_live_engine_server.py`: remove line 9 `from app.infrastructure.adapters.live_engine_server import run_live_engine  # noqa: F401` (unused side-effect import). KEEP all tests (they test live QuantEngine/view_state_to_ws).

**Migrate to quant (1 module + 9 tests preserved):**
- `backend/app/application/utils.py` → move `parse_symbol_metadata` + `is_market_open` (plus their constants `_MONTH_MAP`, `_SYMBOL_RE`, `_EXCHANGE_HOURS`, `_NSE_OPENIST`/`_NSE_CLOSEIST`/`_MCX_OPENIST`/`_MCX_CLOSEIST`, `IST_ZONE`) into `quant/amt/session/symbol_registry.py`. DO NOT migrate `time_to_epoch` (fully dead). Delete `backend/app/application/utils.py`.
- Update `backend/tests/unit/infrastructure/test_feature_alignment.py` imports (lines 60-126): `from app.application.utils import ...` → `from quant.amt.session.symbol_registry import ...`. KEEP the 2 quant-probability tests (lines 21-58). All 11 test functions survive.

## Global Constraints

- **quant purity is a hard constraint:** `quant.*` may NEVER import `app.*`. The migration ADDS to quant from stdlib+quant only — verify with grep after.
- **NEVER `git add -A` / `git add .`.** Stage exact paths only. `graphify-out/`, `backend/graphify-out/`, `.superpowers/`, `docs/superpowers/plans/*.md` must NEVER be committed.
- Backend tests run from `backend/`: `cd backend && ../.venv/bin/python3 -m pytest <path> -q --no-header`. Quant tests from repo root: `.venv/bin/python3 -m pytest tests/quant -q --no-header`.
- Never commit failing tests. The 2 KNOWN pre-existing failures (`TestAIHistory::test_history_endpoint_exists` order-dependent flake; `test_long_signal_builds_valid_rr` float precision) are documented and NOT regressions.
- `quant/amt/session/symbol_registry.py` must remain import-safe (add imports `re`, `datetime`, `zoneinfo` at top of the module — do not create circular imports; it already imports `quant.contracts.exchange_config`).

---

### Task B2-A: Delete 7 dead modules + their dedicated test files

- [x] **Step 1: Safety-gate greps (must show ONLY the test file + the module itself)**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "candle_aggregator\|CandleAggregator" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
grep -rln "llm_circuit_breaker\|LLMCircuitBreaker" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
grep -rln "position_reconciliation" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
grep -rln "delta_profile_adapter\|DeltaProfileAdapter" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
grep -rln "lgbm_probability_adapter\|LGBMProbabilityAdapter" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
grep -rln "live_gateway\|LiveGateway" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
grep -rln "shared.parsing\|from app.shared import parsing\|is_mcx_symbol" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
```
Expected for each: ONLY the module file + its dedicated test file (and possibly the quant port `delta_profile.py` for delta_profile — that port file STAYS in quant, Phase C may audit it separately). If any OTHER production file or test appears, STOP and report.

- [x] **Step 2: Record baseline**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit -q --no-header 2>&1 | tail -3`
Record pass/skip/fail counts.

- [x] **Step 3: Delete the 7 module + 7 test pairs**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git rm backend/app/application/candle_aggregator.py backend/tests/unit/application/test_lee_ready_spike.py
git rm backend/app/core/llm_circuit_breaker.py backend/tests/unit/core/test_llm_circuit_breaker.py
git rm backend/app/domain/ops/position_reconciliation.py backend/tests/unit/domain/services/test_position_reconciliation.py
git rm backend/app/infrastructure/adapters/delta_profile_adapter.py backend/tests/unit/test_delta_profile.py
git rm backend/app/infrastructure/adapters/lgbm_probability_adapter.py backend/tests/unit/infrastructure/test_probability_adapter_contract.py
git rm backend/app/infrastructure/adapters/live_gateway.py backend/tests/unit/infrastructure/test_live_gateway.py
git rm backend/app/shared/parsing.py backend/tests/unit/test_shared_parsing.py
```

- [x] **Step 4: Confirm no dangling refs**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit -q --no-header 2>&1 | tail -3`
Expected: baseline − 7 files' test counts (pass count drops by ~the number of deleted tests; 0 new failures).

- [x] **Step 5: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git commit -m "refactor: delete 7 test-covered dead backend modules + their tests"
```
Verify `git status` shows only these 14 deletions staged. If artifacts appear, `git reset` them.

---

### Task B2-B: Relocate data_generator.py test fixture into tests/

- [x] **Step 1: Verify the fixture consumers are all tests**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "data_generator\|generate_market_data" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
```
Expected: only the 5 test files + the module itself. If any production file appears, STOP and report.

- [x] **Step 2: Create the tests/helpers location**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
ls backend/tests/
```
Check for an existing `helpers/` or `conftest.py`. If no `helpers/` dir, create `backend/tests/helpers/__init__.py`. Match existing test conventions for intra-test imports (check how other test files import shared test code, if any).

- [x] **Step 3: Move the module and update imports**

`git mv backend/app/infrastructure/adapters/data_generator.py backend/tests/helpers/market_data.py`
(Note: the module imports only stdlib + `quant.contracts.value_objects` — verify with `grep -n "^import\|^from"` after move; it must not import `app.*`.)
Update the 5 test files' import line:
`from app.infrastructure.adapters.data_generator import generate_market_data` → `from helpers.market_data import generate_market_data`
(Run pytest from `backend/`, so `tests/helpers` is importable as `helpers` only if `tests/` is on path — verify how `conftest.py`/pytest config handles it. If `helpers` isn't importable, use `from tests.helpers.market_data import generate_market_data` and adjust. Confirm with the 5 test files passing.)

- [x] **Step 4: Run the 5 consumer test files**

Run:
```bash
cd backend && ../.venv/bin/python3 -m pytest tests/unit/domain/test_amt_analyzer.py tests/unit/domain/test_footprint_analyzer.py tests/unit/domain/test_session_reset.py tests/unit/domain/test_prediction_engine.py tests/runtime_validation/test_phase1_leaf_components.py -q --no-header 2>&1 | tail -5
```
Expected: all pass except the 1 KNOWN float-precision failure in `test_phase1_leaf_components.py` (`test_long_signal_builds_valid_rr` — pre-existing).

- [x] **Step 5: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add backend/tests/helpers/market_data.py backend/tests/helpers/__init__.py backend/tests/unit/domain/test_amt_analyzer.py backend/tests/unit/domain/test_footprint_analyzer.py backend/tests/unit/domain/test_session_reset.py backend/tests/unit/domain/test_prediction_engine.py backend/tests/runtime_validation/test_phase1_leaf_components.py
git add -u backend/app/infrastructure/adapters/data_generator.py 2>/dev/null || git rm backend/app/infrastructure/adapters/data_generator.py
git commit -m "refactor: relocate data_generator test fixture to tests/helpers/market_data.py"
```
Verify: `git show --stat HEAD` shows the move + import updates only.

---

### Task B2-C1: Delete NSE/MCX strategies + surgically trim test_exchange_abstraction.py

- [x] **Step 1: Safety-gate greps**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "nse_strategy\|mcx_strategy\|NSEExchangeStrategy\|MCXExchangeStrategy" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
```
Expected: only the 2 modules + `test_exchange_abstraction.py`. If any other file, STOP and report.

- [x] **Step 2: Trim the test file**

In `backend/tests/unit/domain/test_exchange_abstraction.py`:
- Remove lines 19-20 (`from app.infrastructure.strategies.nse_strategy import NSEExchangeStrategy` / `mcx_strategy`).
- Remove `class TestNSEExchangeStrategy` block entirely (lines ~202-231).
- Remove `class TestMCXExchangeStrategy` block entirely (lines ~233-286).
- Remove `test_mcx_strategy_uses_config_thresholds` + `test_nse_strategy_uses_config_thresholds` from `TestAbstractionLayerConsistency` (lines ~371-385).
- KEEP everything else (TestExchangeConfig, TestSymbolRegistry, TestSessionContextFactory, TestExchangeConfigBridge, test_registry_matches_config_underlyings, test_di_container_wiring, test_no_domain_imports_config).
- Update the module docstring if it references the strategy classes.

- [x] **Step 3: Delete the 2 modules**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git rm backend/app/infrastructure/strategies/nse_strategy.py backend/app/infrastructure/strategies/mcx_strategy.py
```

- [x] **Step 4: Verify the trimmed test + no dangling refs**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit/domain/test_exchange_abstraction.py -q --no-header`
Expected: green (all KEPT tests pass; strategy tests gone).
Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "NSEExchangeStrategy\|MCXExchangeStrategy" --include="*.py" backend/app backend/tests | grep -v __pycache__`
Expected: no output.

- [x] **Step 5: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git commit -m "refactor: delete dead NSE/MCX exchange strategies + trim mixed test"
```
Verify `git show --stat HEAD`: 2 deletions + 1 modified test file.

---

### Task B2-C2: Delete live_engine_server.py + drop unused test import

- [x] **Step 1: Safety-gate grep**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "live_engine_server\|run_live_engine" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
```
Expected: only the module + `test_live_engine_server.py`. If any other, STOP and report.

- [x] **Step 2: Remove the unused import line from the test**

In `backend/tests/unit/infrastructure/test_live_engine_server.py`, delete line 9: `from app.infrastructure.adapters.live_engine_server import run_live_engine  # noqa: F401`. KEEP all test bodies (they test live QuantEngine + view_state_to_ws).

- [x] **Step 3: Delete the module**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git rm backend/app/infrastructure/adapters/live_engine_server.py
```

- [x] **Step 4: Verify the test still passes**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit/infrastructure/test_live_engine_server.py -q --no-header`
Expected: green.

- [x] **Step 5: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git commit -m "refactor: delete dead live_engine_server adapter + drop unused import"
```

---

### Task B2-D: Migrate parse_symbol_metadata + is_market_open into quant

- [x] **Step 1: Confirm current test count**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit/infrastructure/test_feature_alignment.py -q --no-header 2>&1 | tail -2`
Record: 11 tests currently (2 quant-probability + 3 parse_symbol_metadata + 5 is_market_open + 1 parse error = 11; record actual). Note the parquet-dependent test (`test_feature_alignment_training_vs_live`) may SKIP if poc3 parquets missing — that's fine.

- [x] **Step 2: Add the two functions to quant/amt/session/symbol_registry.py**

Append to `quant/amt/session/symbol_registry.py`:
- `parse_symbol_metadata(symbol: str, spot: float = 0.0) -> dict` — port verbatim from `backend/app/application/utils.py:26-96` (includes `_SYMBOL_RE`, `_MONTH_MAP`, IST_ZONE logic, expiry/dte/moneyness computation). Adapt imports: add `re`, `datetime` (`datetime`, `date`, `time as dtime`), `zoneinfo`. Reuse `from quant.contracts.timezones import IST` for the tzinfo (check how the module currently imports; add `IST_ZONE = ZoneInfo("Asia/Kolkata")` or use `IST` — prefer the existing quant `IST` constant to avoid a duplicate ZoneInfo).
- `is_market_open(ts: str | None = None, exchange: str | None = None) -> bool` — port verbatim from `utils.py:98-124` (includes `_EXCHANGE_HOURS` dict + NSE/MCX open/close constants).
- Add a short module docstring note that these were migrated from the backend application layer (2026-08-08) so future readers know the canonical home.
- DO NOT port `time_to_epoch` (fully dead — zero refs; confirm with grep in Step 4).

**quant purity:** the additions must NOT import `app.*` or `shared.*`. Only stdlib + `quant.contracts.timezones`.

- [x] **Step 3: Update test_feature_alignment.py imports**

Replace all `from app.application.utils import parse_symbol_metadata` / `from app.application.utils import is_market_open` (lines 61, 70, 78, 86, 91, 98, 104, 113, 126) with `from quant.amt.session.symbol_registry import parse_symbol_metadata` / `is_market_open`.
KEEP `test_feature_alignment_training_vs_live` (imports quant.probability.features) and `test_probability_feature_contract_metadata`.

- [x] **Step 4: Verify time_to_epoch is dead + app.utils deletion safe**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rn "time_to_epoch" --include="*.py" backend/app backend/tests quant brokers | grep -v __pycache__
```
Expected: only `backend/app/application/utils.py:126` (the def itself). If any importer, STOP and report.

- [x] **Step 5: Delete the app wrapper**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git rm backend/app/application/utils.py
```

- [x] **Step 6: Verify tests pass (backend + quant)**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit/infrastructure/test_feature_alignment.py -q --no-header 2>&1 | tail -2`
Expected: same count as Step 1 (all 11 — minus any parquet-skip — still present, now importing from quant).
Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && .venv/bin/python3 -m pytest tests/quant -q --no-header 2>&1 | tail -2`
Expected: quant suite green (no regression from adding the functions).

- [x] **Step 7: Verify quant purity of the migration**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -n "from app\.\|import app\.\|from shared\|import shared" quant/amt/session/symbol_registry.py
```
Expected: no output.

- [x] **Step 8: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add quant/amt/session/symbol_registry.py backend/tests/unit/infrastructure/test_feature_alignment.py
git rm backend/app/application/utils.py
git commit -m "refactor: migrate symbol metadata + market-hours utils into quant"
```

---

### Task B2-E: Final verification

- [x] **Step 1: Full backend unit+integration suite**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit tests/integration -q --no-header 2>&1 | tail -3`
Expected: green except the 2 KNOWN pre-existing failures. Confirm NO new failures (count should reflect deletions: fewer tests, same failures).

- [x] **Step 2: Full quant suite**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && .venv/bin/python3 -m pytest tests/quant -q --no-header 2>&1 | tail -2`
Expected: green.

- [x] **Step 3: Confirm all deletions landed + moves correct**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
for f in backend/app/application/candle_aggregator.py backend/app/core/llm_circuit_breaker.py backend/app/domain/ops/position_reconciliation.py backend/app/infrastructure/adapters/delta_profile_adapter.py backend/app/infrastructure/adapters/lgbm_probability_adapter.py backend/app/infrastructure/adapters/live_gateway.py backend/app/shared/parsing.py backend/app/infrastructure/strategies/nse_strategy.py backend/app/infrastructure/strategies/mcx_strategy.py backend/app/infrastructure/adapters/live_engine_server.py backend/app/application/utils.py; do [ -f "$f" ] && echo "STILL EXISTS: $f"; done
[ -f backend/tests/helpers/market_data.py ] && echo "fixture moved OK" || echo "FIXTURE MISSING"
grep -rln "from app.infrastructure.adapters.data_generator" --include="*.py" backend/tests | grep -v __pycache__ || echo "no stale data_generator imports"
echo "check complete"
```
Expected: no "STILL EXISTS" lines, "fixture moved OK", "no stale data_generator imports".

- [x] **Step 4: Verify quant purity across whole repo**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rn "from app\.\|import app\." --include="*.py" quant shared | grep -v __pycache__
```
Expected: no output.

- [x] **Step 5: Verify git history clean of artifacts**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && git log --oneline -6 && git status --short`
Expected: 5 new commits (`refactor:` x5) on top of `3da3a35`; working tree shows ONLY untracked artifacts (graphify-out/, backend/graphify-out/, .superpowers/, plan docs) — never staged.

---

## Definition of Done

- [x] 7 dead modules + their test files deleted (A)
- [x] `data_generator.py` relocated to `backend/tests/helpers/market_data.py`, 5 live-quant test files still pass (B)
- [x] NSE/MCX strategy modules deleted; `test_exchange_abstraction.py` trimmed to live-only tests (C1)
- [x] `live_engine_server.py` deleted; its test file passes after dropping 1 unused import (C2)
- [x] `parse_symbol_metadata` + `is_market_open` migrated to `quant/amt/session/symbol_registry.py`; all 9 tests preserved; `time_to_epoch` confirmed dead and NOT migrated (D)
- [x] Full backend + quant suites green (except 2 documented pre-existing failures)
- [x] quant + shared purity preserved (no `from app` imports)
- [x] No artifacts (graphify-out/.superpowers) in any commit
