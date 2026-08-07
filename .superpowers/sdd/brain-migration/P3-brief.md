# Phase 3 — Delete the legacy brain + shims (audit "kill legacy + delete shims")

**Worktree:** `/Users/apple/Documents/wt-gt-P3` (branch `migration/P3`). Work ONLY there. Never touch `/Users/apple/Documents/v5-of-glassytrade-ai`.

**Context:** The entire brain now lives in `quant/`. Backend consumers were import-swapped to `quant.*` in Phase 2, but ~18 straggler files still import through the legacy `app.domain.*` shims (those shims exist in `backend/app/domain/`). This task (a) swaps the stragglers, (b) relocates the 6 ops modules that legitimately STAY in the backend, (c) deletes the entire legacy brain + all shims, (d) cleans up config/scripts.

## Step 1 — Swap all straggler imports

Targets (files importing `app.domain.*` outside the `backend/app/domain/` tree). For each, replace the legacy shim path with the canonical `quant.*` path using this map (or grep the symbol in `quant/`):
- `app.domain.trading.models.{value_objects,entities,enums,utils,aggregates,event_store,events,initial_balance,volume_profile,vwap_bands,cvd,trading_context}` → `quant.contracts.<same>`
- `app.domain.trading.events` → `quant.contracts.events` ; `app.domain.trading.event_store` → `quant.contracts.event_store`
- `app.domain.ports.{storage,broker,market_data,notifications,notification_adapter,llm_inference,probability_inference,npoc,delta_profile,exchange_strategy,config_port}` → `quant.contracts.ports.<same>`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.models.exchange_config` → `quant.contracts.exchange_config`
- `app.domain.models.{exchange,market_state}` → **STAY** (`app.domain.models.exchange` / `app.domain.models.market_state`) — keep these imports; they are config/exchange models that remain in backend.
- `app.domain.services.{startup_reconciliation,position_reconciliation,self_healing,mobile_alerts,gate_rejection_tracker,latency_tracker}` → **STAY**, but the module paths change to `app.domain.ops.<same>` after Step 3 — swap them in the same commit as the ops relocation.

Files to swap (grep `grep -rln "from app.domain\|import app.domain" backend/app --include="*.py" | grep -v __pycache__ | grep -v "^backend/app/domain/"`; expect ~18 files incl. `dhan_broker_adapter.py`, `session_event_logger.py`, `gap_detector.py`, `events/resilient_wrapper.py`, `events/handler.py`, `stream_manager.py`, `tick_processor.py`, `session_cache.py`, `watchdog_manager.py`, `data_generator.py`, `telegram_adapter.py`, `null_notification_adapter.py`, `database.py`, `metrics.py`, `main.py`, `composition_root.py`, `startup_contracts.py`).

Do NOT change logic. If a swap would create a circular import (quant already imports zero `app.*`, so this should not happen), fall back to a `# TODO(p3)` comment and report it.

## Step 2 — Verify zero stragglers
`grep -rn "from app.domain\|import app.domain" backend/app --include="*.py"` (excluding `backend/app/domain/` itself) must return ONLY: `app.domain.ops.*` (after Step 3) and `app.domain.models.{exchange,market_state}`.

## Step 3 — Relocate ops modules (they STAY in backend)
`git mv` these 6 from `backend/app/domain/services/` → `backend/app/domain/ops/`:
`position_reconciliation.py`, `startup_reconciliation.py`, `self_healing.py`, `mobile_alerts.py`, `gate_rejection_tracker.py`, `latency_tracker.py`.
Update their internal imports (they import `quant.contracts.*` and `app.domain.ports.*` → `quant.contracts.ports.*`) and their importers to `app.domain.ops.<same>`. Create `backend/app/domain/ops/__init__.py`.

## Step 4 — Strategy modules
`backend/app/domain/fabio_ai/strategy/` has `protocols.py`, `setup_detector.py`, `fabio_detectors.py`, `squeeze_detector.py` (squeeze already moved to `quant.amt.market.squeeze` in Track A2). Check importers of `protocols`/`setup_detector`/`fabio_detectors` (`grep -rln "fabio_detectors\|setup_detector\|strategy.protocols" backend --include="*.py"`). If `backend/app/config_models/loader.py` imports from them, MOVE the imported symbols into `quant/amt/strategy/` (move the 3 files, rewrite imports, leave shims is NOT possible since the whole fabio_ai tree is deleted — so instead move the files AND swap the loader's import to `quant.amt.strategy.*` in the same commit). If they are dead (no real importers besides each other), `git rm` them and report. Do the same for any other dead files in `fabio_ai/strategy/`.

## Step 5 — trade_aggregate duplicate
`backend/app/domain/trading/models/trade_aggregate.py` (770-line event-sourced aggregate, the Q-02 duplicate). Its only importer is `backend/app/domain/trading/models/__init__.py`. Check whether ANY code imports `Trade`/`create_trade`/`trade_aggregate` symbols: `grep -rn "trade_aggregate\|create_trade\|\.get_position()" backend/app backend/tests --include="*.py" | grep -v "backend/app/domain/trading/models/trade_aggregate.py"`. If no real consumers, `git rm` it and report. If consumers exist, DO NOT delete — swap them to `quant.contracts.aggregates` if the API matches, otherwise keep the file at `app.domain.ops/trade_aggregate.py` and report.

## Step 6 — Delete the legacy brain + all shims
After Steps 1–5, delete (git rm -r) the ENTIRE legacy brain tree:
- `backend/app/domain/fabio_ai/` (all shims + strategy leftovers)
- `backend/app/domain/probability/` (all shims)
- `backend/app/domain/trading/` (models/ services/ events.py event_store.py — all shims)
- `backend/app/domain/ports/` (all shims)
- `backend/app/domain/services/` (only the 6 ops files remain after Step 3 — after moving them out, the dir is empty; delete it)
- `backend/app/domain/constants.py` (shim)
- `backend/app/domain/models/exchange_config.py` (shim)
- `backend/app/shared/timezones.py` (shim — verify `grep -rn "app.shared.timezones" backend --include="*.py"` is empty first)
- `backend/app/domain/models/exchange.py` and `market_state.py`: KEEP (referenced).
- `backend/app/domain/__init__.py` and `backend/app/domain/ops/` remain.
After deletion: `grep -rn "app.domain.fabio_ai\|app.domain.probability\|app.domain.trading\|app.domain.ports\|app.domain.constants\|app.domain.services" backend/app --include="*.py"` must be EMPTY.

## Step 7 — Scripts/config cleanup
- `backend/start_preflight.sh` syntax-checks backend files — update any path references to deleted dirs (or verify it globs safely).
- `backend/.importlinter` — update to the new layout (domain only has ops + models).
- `backend/pytest.ini` / `conftest.py` — confirm no references to deleted modules.
- `backend/STARTUP_RUNBOOK.md` if it references brain paths.

## Step 8 — Verify
```bash
cd /Users/apple/Documents/wt-gt-P3/backend
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors
cd /Users/apple/Documents/wt-gt-P3
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
```
Report exact counts. The 4 pre-existing env errors (gymnasium + 3 httpx) are acceptable; ANY new failure must be fixed or explained. Also run `cd /Users/apple/Documents/wt-gt-P3 && /Users/apple/miniconda3/envs/amt_313/bin/python -c "import app.main; import quant; import app.domain.ops"` to prove the app still imports.

**Commit:** split into logical commits: (1) `refactor(backend): swap straggler imports to quant.*`, (2) `refactor(backend): relocate ops modules to app.domain.ops`, (3) `refactor(quant): move strategy detectors to quant.amt.strategy` (if moved), (4) `refactor(backend): delete legacy brain + shims`, (5) `chore(backend): update scripts/config for brain migration`.

**Report contract:** write to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/P3-report.md`: files swapped, ops relocation, strategy decision (moved vs deleted), trade_aggregate decision (deleted vs kept + consumers), dirs deleted, scripts updated, test counts. Reply: status, commit hashes, test counts, concerns.
