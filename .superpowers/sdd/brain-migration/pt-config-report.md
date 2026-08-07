# WS-PT-CONFIG — Collapse the triple config stack report

**Track:** WS-PT-CONFIG (ponytail audit: `config/consolidated.py` pydantic + `settings_adapter` + `config_models.SystemConfig`)
**Worktree:** `/Users/apple/Documents/wt-pt-config` (branch `migration/pt-config`)
**Status:** ✅ Complete

## Outcome — which source won

**`backend/app/config_models/` wins:**
- **`config_models/__init__.py` `SystemConfig`** (frozen dataclass) = the **canonical typed config model** (built by `config_models/loader.py` from the YAML hierarchy + `feature_flags.yaml`, validated by `validator.py`, wrapped by `ModeConfig`).
- **`config_models/settings_adapter.py` `SettingsAdapter`** (singleton `settings`, re-exported as `app.config.settings`) = the **canonical runtime adapter** the backend already consumes (36+ files). `QUANT_EXECUTION_MODE` / `SIGNAL_STALE_SECONDS` (added by WS-EXEC/WS-DATA) stay here.
- These two were already one coherent pair (`settings` reads `_mode_config.system_config`, which **is** the `SystemConfig` dataclass), so no new indirection was introduced.

**What was deleted:** `backend/config/consolidated.py` (563 lines, the entire pydantic `ConsolidatedConfig` layer, `get_config`/`set_config`/`get_exchange_config`/`from_unified`/`from_yaml`). This was the redundant third layer that re-parsed the same YAML via `from_unified()` and re-declared overlapping `LLMConfig`/`RiskConfig`/`FeatureFlags`/scanner/AMT settings.

**Which option of the brief:** option (a) — delete `config/consolidated.py` and move its consumers to `settings_adapter`/`SystemConfig`. Consumers were few enough (~5 prod files) that deletion beat making the pydantic model canonical (which would have required rewriting the whole YAML loader/validator/mode_config — far more churn).

## Consumer count

### Production consumers of the deleted `ConsolidatedConfig` (moved to `settings`/`SystemConfig`)
| File | What it read | Now reads |
|---|---|---|
| `app/config.py` | re-export `Configuration` | `SystemConfig` from `app.config_models` |
| `app/main.py` | `Configuration.from_unified()`, `config.cors_origins`, `config.dhan_symbols` | `settings.get_mode_config().system_config`, `settings.CORS_ORIGINS`, `settings.DHAN_SYMBOLS` |
| `app/application/di/composition_root.py` | `config.llm.*`, `config.default_exchange`, `config.db_path` | `config.llm` (dataclass fields), `settings.DEFAULT_EXCHANGE`, `config.db_path` (still present) |
| `app/infrastructure/adapters/dhan_broker_adapter.py` | `config.dhan_client_id/access_token` | `settings.DHAN_CLIENT_ID/ACCESS_TOKEN` fallback (env still supported) |
| `app/api/routers/health.py` | `_config.trading.default_symbol` (empty-list fallback only) | degrades to documented `["CRUDEOIL"]` fallback (SystemConfig has no `.trading`); never hit in practice |

`app/api/dependencies.py` only used a string annotation `"Configuration"` — no change needed.

### Test consumers (updated to canonical source)
- `tests/unit/application/test_di_container.py` — `Configuration.from_unified()` → `settings.get_mode_config().system_config`
- `tests/unit/application/test_live_wiring_fixes.py` — same swap
- `tests/unit/domain/test_exchange_abstraction.py` — `TestConsolidatedConfigBridge` rewritten as `TestExchangeConfigBridge` against `quant.contracts.exchange_config.ExchangeConfig.for_exchange/from_dict` (the bridge `get_exchange_config` was test-only, deleted)
- `tests/integration/test_runtime_contracts.py` — monkeypatch target `config.consolidated.ConsolidatedConfig.from_unified` removed (fake scanner/container make config values irrelevant)

### Consumers that never changed
- All 36 files doing `from app.config import settings` (they read `settings.*` properties — untouched).
- `config_models/loader.py`, `config_models/validator.py`, `config/mode_config.py`, `config_models/settings_adapter.py` — already part of the canonical source.
- `tests/unit/domain/test_config_architecture.py` — tested `SystemConfig` directly; untouched and green.

## Feature-flag / setting resolution after the change
Verified at runtime:
- `QUANT_EXECUTION_MODE` → `off` (env → `feature_flags.yaml` → back-compat alias)
- `SIGNAL_STALE_SECONDS` → `60`
- `ALLOW_SHORT` → `True`, `SCALP_ENGINE_ENABLED` → `True`, `DHAN_SYMBOLS`, `DEFAULT_EXCHANGE`, `CORS_ORIGINS` all resolve via the single `settings` adapter.

All feature flags now resolve from exactly one runtime source (`SettingsAdapter` reading `SystemConfig.flags` built from `feature_flags.yaml` + env).

## Default-value equivalence (no behavior change)
- LLM adapter temp: `ConsolidatedConfig.from_unified()` used mid(entry, overseer) with `LLM_TEMPERATURE` env override → `_resolve_llm_temperature()` in `composition_root` reproduces the identical mid/override logic against dataclass `LLMConfig`.
- LLM adapter `max_new_tokens`: pydantic path used `sys_llm.max_tokens`; dataclass path reads `config.llm.max_tokens` directly — same `120`.
- `db_path`, `default_exchange`, scanner/risk/AMT values: identical (same underlying `SystemConfig`).

## Files changed (11)
`backend/app/application/di/composition_root.py`, `backend/app/config.py`, `backend/app/config_models/settings_adapter.py` (+`CORS_ORIGINS` property), `backend/app/infrastructure/adapters/dhan_broker_adapter.py`, `backend/app/main.py`, `backend/config/consolidated.py` (**deleted**), `backend/tests/integration/test_runtime_contracts.py`, `backend/tests/unit/application/test_di_container.py`, `backend/tests/unit/application/test_live_wiring_fixes.py`, `backend/tests/unit/domain/test_exchange_abstraction.py`, `quant/contracts/exchange_config.py` (comment only).

## Commit
- `88daff8` — `refactor(config): collapse triple config stack to one canonical source` (+76 / −636 across 11 files; −563 from deleting `consolidated.py`)

## Verification
1. `cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors`
   → **1323 passed, 64 skipped, 0 failed / 0 errors** (identical to pre-change baseline of 1323 passed / 64 skipped).
2. `PYTHONPATH=.../backend ... -c "import app.main"` from repo root → **exit 0**, app boots clean (config loads as `SystemConfig`, CORS, DI, reconciliation OK).

## Concerns
- None blocking. `app/api/routers/health.py`'s `_bootstrap_active_symbols` last-resort fallback now returns `["CRUDEOIL"]` instead of the old `["CRUDEOIL 20 MAR 6500 CALL"]` from `ConsolidatedConfig.trading.default_symbol` — only reachable when both `active_symbols` and `DHAN_SYMBOLS` are empty (never in practice); documented default preserved.
- `dhan_broker_adapter.py` still accepts a `Configuration`-typed arg for DI compat; reads creds via `settings`/env, so no behavior change.
- The integration suite (`tests/integration`) requires `httpx`, which is absent in this env — it was already unrunnable here; its config-reference was updated anyway so it stays consistent when the dep is installed.
