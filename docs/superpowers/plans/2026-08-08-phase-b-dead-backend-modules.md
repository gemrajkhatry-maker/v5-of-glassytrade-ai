# Phase B — Delete Dead Backend Modules (Safe-Only Wave)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax.

**Goal:** Delete the 13 truly-dead backend modules (zero importers anywhere — production AND tests) and the 3 broken scripts flagged in `.superpowers/audit-2026-08-08/backend-audit.md` and `tests-brokers-shared-audit.md`. Pure removals — no runtime behavior changes because nothing imports these files.

**Scope decision (user sign-off, 2026-08-08):** "Safe-only first." This wave deletes ONLY zero-importer files. The 12 production-dead-but-test-covered modules (each imported by passing tests) are DEFERRED to Phase B2, which requires test-file surgery and a separate review. `shared/conversion.py` is a confirmed AUDIT ERROR — it is LIVE (`database.py:20` imports `to_float`) and is NOT deleted.

**Safety principle:** Every deletion is gated by a grep proving ZERO importers in production + tests + brokers + scripts. If any safety-gate grep finds a real importer, STOP and do not delete (report back instead).

**Verified facts (coordinator pre-check, 2026-08-08):**
- All 13 files below have ZERO importers (grep across `backend/app`, `backend/tests`, `quant`, `brokers`, `backend/scripts`, excluding `__pycache__` and the file itself). No `__init__.py` re-exports them; no `conftest.py`/`pyproject.toml`/`pytest.ini` reference them.
- The 3 scripts import modules deleted in earlier commits (`app.application.handlers.llm_overseer_handler`, `app.domain.services.oi_wall_detector`, `backend.quant.execution.risk_sizing`) — they are broken at import time and referenced nowhere in docs/README/tests.
- **Kept (corrected from audit):** `shared/conversion.py` (live via `database.py:20`), `shared/resilience.py` (live via `brokers/gateway.py`, `observability.py`), `shared/entities/` (live via `schemas.py`, `gateway.py`, `broker/types.py`, `broker/entities.py`), `app/shared/mode.py` (live via `composition_root.py`), `shared/__init__.py` (empty, keep). Kept files do NOT import the deleted `config.py`/`error_handling.py`.
- `backend/app/domain/models/exchange.py` is now orphaned: audit said KEEP because `composition_root.py:305` used it, but Phase A deleted that factory. Re-verified: ZERO importers remain, no `__init__` re-export. Included in this wave.
- Baseline to record before first commit: full backend unit suite green except the 2 known pre-existing failures (`TestAIHistory::test_history_endpoint_exists` order-dependent flake; `test_long_signal_builds_valid_rr` float precision) — proven pre-existing at base `6d55603`.

## Files

**Delete (13 dead modules):**
- `backend/app/application/ports/trade_journal.py` (ITradeJournal — zero refs)
- `backend/app/application/protocols.py` (zero refs)
- `backend/app/domain/ops/mobile_alerts.py` (zero refs)
- `backend/app/domain/ops/self_healing.py` (zero refs)
- `backend/app/domain/models/exchange.py` (orphaned after Phase A — zero refs)
- `backend/app/infrastructure/adapters/telegram_adapter.py` (zero refs)
- `backend/app/infrastructure/mlx_gpu_lock.py` (zero refs)
- `backend/app/infrastructure/transformers_quiet.py` (zero refs)
- `backend/app/shared/config_features.py` (zero refs)
- `backend/app/shared/depth_dto.py` (zero refs)
- `backend/app/shared/logging.py` (zero refs)
- `backend/app/shared/symbol_utils.py` (zero refs)
- `shared/config.py` (root, zero refs)
- `shared/error_handling.py` (root, zero refs)

**Delete (3 broken scripts):**
- `backend/scripts/walkthrough_architecture.py`
- `backend/scripts/demo_oi_wall_detection.py`
- `backend/scripts/oi_wall_integration_example.py`

**NOT in scope (deferred to Phase B2):** `application/candle_aggregator.py`, `application/utils.py`, `core/llm_circuit_breaker.py`, `domain/ops/position_reconciliation.py`, `infrastructure/adapters/data_generator.py`, `delta_profile_adapter.py`, `lgbm_probability_adapter.py`, `live_engine_server.py`, `live_gateway.py`, `strategies/mcx_strategy.py`, `strategies/nse_strategy.py`, `shared/parsing.py` — all have passing-test importers (~16 test files). Also NOT in scope: `shared/conversion.py` (LIVE).

## Global Constraints

- **quant purity is a hard constraint:** `quant.*` may NEVER import `app.*`. None of these deletions touch quant. Verify with grep after each commit.
- **NEVER `git add -A` / `git add .`.** Stage exact paths only. `graphify-out/`, `.superpowers/`, and `backend/graphify-out/` are untracked artifacts that MUST never be committed.
- Backend tests run from `backend/`: `cd backend && ../.venv/bin/python3 -m pytest <path> -q --no-header`.
- Never commit failing tests. Commit after each task with `chore:`/`refactor:` prefix.
- If any safety-gate grep (Step 1 of each task) finds a real importer, STOP and report. Do not delete.

---

### Task B1: Delete the 8 zero-importer backend modules with NO test impact

**Files:**
- Delete: `backend/app/application/ports/trade_journal.py`
- Delete: `backend/app/application/protocols.py`
- Delete: `backend/app/domain/ops/mobile_alerts.py`
- Delete: `backend/app/domain/ops/self_healing.py`
- Delete: `backend/app/domain/models/exchange.py`
- Delete: `backend/app/infrastructure/adapters/telegram_adapter.py`
- Delete: `backend/app/infrastructure/mlx_gpu_lock.py`
- Delete: `backend/app/infrastructure/transformers_quiet.py`

- [x] **Step 1: Safety-gate greps (must all be EMPTY)**

Run (from repo root):
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rn "ports.trade_journal\|from app.application.ports import trade_journal\|ITradeJournal" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "application.protocols\|from app.application import protocols" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "ops.mobile_alerts\|MobileAlertSystem\|from app.domain.ops import mobile_alerts" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "ops.self_healing\|OrderRejectionHandler\|from app.domain.ops import self_healing" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "domain.models.exchange\|from app.domain.models import Exchange\|app.domain.models import" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "adapters.telegram_adapter\|from app.infrastructure.adapters import telegram_adapter\|TelegramNotifier" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "mlx_gpu_lock\|MLXGPU" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "transformers_quiet\|QUIET_LOGGING\|transformers_logging" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
```
Expected: no output for all 8. If any hit is a REAL importer (not the file itself, not `quant` self-references), STOP and report.

- [x] **Step 2: Record baseline (before deletions)**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit -q --no-header 2>&1 | tail -3`
Expected: ~green (record pass/skip counts + the 2 known pre-existing failures if present).

- [x] **Step 3: Delete the 8 files**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git rm backend/app/application/ports/trade_journal.py backend/app/application/protocols.py backend/app/domain/ops/mobile_alerts.py backend/app/domain/ops/self_healing.py backend/app/domain/models/exchange.py backend/app/infrastructure/adapters/telegram_adapter.py backend/app/infrastructure/mlx_gpu_lock.py backend/app/infrastructure/transformers_quiet.py
```

- [x] **Step 4: Confirm no dangling refs after deletion**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit -q --no-header 2>&1 | tail -3`
Expected: same baseline as Step 2 (no NEW failures from the deletions).

- [x] **Step 5: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add backend/app/application/ports/trade_journal.py backend/app/application/protocols.py backend/app/domain/ops/mobile_alerts.py backend/app/domain/ops/self_healing.py backend/app/domain/models/exchange.py backend/app/infrastructure/adapters/telegram_adapter.py backend/app/infrastructure/mlx_gpu_lock.py backend/app/infrastructure/transformers_quiet.py
git commit -m "refactor: delete 8 zero-importer dead backend modules"
```
(Note: `git rm` already stages; the `git add` is a safety no-op for the tracked ones. Verify with `git status` that NO artifact files got staged — if they did, `git reset` them and re-stage exact paths.)

---

### Task B2: Delete the 6 dead `shared/` modules (app + root)

**Files:**
- Delete: `backend/app/shared/config_features.py`
- Delete: `backend/app/shared/depth_dto.py`
- Delete: `backend/app/shared/logging.py`
- Delete: `backend/app/shared/symbol_utils.py`
- Delete: `shared/config.py` (root — LIVE neighbors conversion.py/resilience.py/entities/ stay)
- Delete: `shared/error_handling.py` (root)

- [x] **Step 1: Safety-gate greps (must all be EMPTY)**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rn "app.shared.config_features\|from app.shared import config_features\|FeatureFlags" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "app.shared.depth_dto\|DepthDTO\|from app.shared import depth_dto" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "app.shared.logging\|from app.shared import logging\|trading_context\|setup_logging" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "app.shared.symbol_utils\|from app.shared import symbol_utils\|is_spot_symbol\|normalize_symbol" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "from shared.config import\|from shared import config\b\|import shared.config" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
grep -rn "from shared.error_handling import\|from shared import error_handling\|import shared.error_handling" --include="*.py" backend/app backend/tests quant brokers backend/scripts | grep -v __pycache__
```
Expected: no output for all 6. Note `shared/config.py` MUST NOT be confused with `app/shared/mode.py` (KEEP — live in composition_root). Do not delete `mode.py`.

- [x] **Step 2: Confirm the KEPT root shared files don't depend on the deleted ones**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rn "from shared.config\|from shared.error_handling" shared/conversion.py shared/resilience.py shared/entities/ shared/__init__.py
```
Expected: no output (verified by coordinator; re-confirm).

- [x] **Step 3: Delete the 6 files**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git rm backend/app/shared/config_features.py backend/app/shared/depth_dto.py backend/app/shared/logging.py backend/app/shared/symbol_utils.py shared/config.py shared/error_handling.py
```

- [x] **Step 4: Boot + suite sanity**

Run: `cd backend && ../.venv/bin/python3 -c "from app.application.di.composition_root import compose_container; from app.config import settings; mode=settings.get_mode_config(); c=compose_container(mode.system_config if mode else None); print('container ok')"` → prints `container ok`.
Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit -q --no-header 2>&1 | tail -3` → matches baseline.

- [x] **Step 5: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add backend/app/shared/config_features.py backend/app/shared/depth_dto.py backend/app/shared/logging.py backend/app/shared/symbol_utils.py shared/config.py shared/error_handling.py
git commit -m "refactor: delete 6 zero-importer dead shared modules"
```
Verify `git status` — only these 6 staged. If `graphify-out/` or `backend/graphify-out/` got staged, `git reset` them.

---

### Task B3: Delete the 3 broken scripts

**Files:**
- Delete: `backend/scripts/walkthrough_architecture.py` (imports deleted `app.application.handlers.llm_overseer_handler`)
- Delete: `backend/scripts/demo_oi_wall_detection.py` (imports deleted `app.domain.services.oi_wall_detector`)
- Delete: `backend/scripts/oi_wall_integration_example.py` (imports deleted `oi_wall_detector` + nonexistent `backend.quant.execution.risk_sizing`)

- [x] **Step 1: Confirm the scripts are broken at import time**

Run: `cd backend && ../.venv/bin/python3 -c "import walkthrough_architecture"` (from `backend/scripts`), likewise for the other two. Expected: ImportError/ModuleNotFoundError referencing the deleted modules.

- [x] **Step 2: Confirm no production/test/docs references to the scripts**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rn "walkthrough_architecture\|demo_oi_wall_detection\|oi_wall_integration_example" --include="*.py" --include="*.md" --include="*.toml" backend docs README.md pyproject.toml 2>/dev/null | grep -v __pycache__ | grep -v "graphify-out" | grep -v ".superpowers"
```
Expected: only self-references (the script files themselves) remain.

- [x] **Step 3: Delete the 3 scripts**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git rm backend/scripts/walkthrough_architecture.py backend/scripts/demo_oi_wall_detection.py backend/scripts/oi_wall_integration_example.py
```

- [x] **Step 4: Confirm nothing else breaks**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit -q --no-header 2>&1 | tail -3` → matches baseline (scripts are not tested).

- [x] **Step 5: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add backend/scripts/walkthrough_architecture.py backend/scripts/demo_oi_wall_detection.py backend/scripts/oi_wall_integration_example.py
git commit -m "chore: delete 3 broken scripts referencing deleted modules"
```

---

### Task B4: Final verification

- [x] **Step 1: Full backend unit+integration suite**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit tests/integration -q --no-header 2>&1 | tail -3`
Expected: green except the 2 KNOWN pre-existing failures (documented; not regressions).

- [x] **Step 2: Confirm all 16 deletions landed**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && for f in backend/app/application/ports/trade_journal.py backend/app/application/protocols.py backend/app/domain/ops/mobile_alerts.py backend/app/domain/ops/self_healing.py backend/app/domain/models/exchange.py backend/app/infrastructure/adapters/telegram_adapter.py backend/app/infrastructure/mlx_gpu_lock.py backend/app/infrastructure/transformers_quiet.py backend/app/shared/config_features.py backend/app/shared/depth_dto.py backend/app/shared/logging.py backend/app/shared/symbol_utils.py shared/config.py shared/error_handling.py backend/scripts/walkthrough_architecture.py backend/scripts/demo_oi_wall_detection.py backend/scripts/oi_wall_integration_example.py; do [ -f "$f" ] && echo "STILL EXISTS: $f"; done; echo "check complete"`
Expected: prints only `check complete` (no "STILL EXISTS" lines).

- [x] **Step 3: Verify quant purity + no orphan dirs**

Run:
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rn "from app\.\|import app\." --include="*.py" quant | grep -v __pycache__
grep -rn "from app\.\|import app\." --include="*.py" shared | grep -v __pycache__
```
Expected: no output (quant and shared never import app).

- [x] **Step 4: Verify git history is clean of artifacts**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && git log --oneline -5 && git status --short`
Expected: 3 new commits (`refactor:` x2, `chore:` x1) on top of `5d816b4`; working tree shows ONLY untracked artifacts (`graphify-out/`, `backend/graphify-out/`, `.superpowers/`, plan docs) — never staged.

---

## Definition of Done

- [x] All 16 files deleted (13 dead modules + 3 broken scripts)
- [x] Zero test impact — backend suite green except the 2 documented pre-existing failures
- [x] `container ok` boot check passes
- [x] quant + shared purity preserved (no `from app` imports)
- [x] Deferred test-covered modules documented for Phase B2; `shared/conversion.py` confirmed LIVE and kept
- [x] No artifacts (graphify-out/.superpowers) in any commit
