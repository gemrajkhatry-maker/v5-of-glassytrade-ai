# Phase 1 Track A4 — Session & options cluster → `quant/amt/session/`

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track A4.

**Goal:** Port the session-context / NPOC / EIA / option-scanner-selector / futures-provider / symbol-registry / IB cluster into `quant/amt/session/`. Same move-with-shim + parity recipe as prior tracks. One commit per module; every commit leaves quant + backend suites green.

**Step 0 (first commit): move the sync-boundary helper into `quant/contracts/`**
- Copy `ensure_sync_adapter_result` and `ensure_async_adapter_result` from `backend/app/core/async_boundary.py` into `quant/contracts/sync_boundary.py` (verbatim, same module docstring). Leave the original `backend/app/core/async_boundary.py` in place (it has other consumers).
- Commit: `feat(quant): move sync/async boundary helpers to quant.contracts`.

**Modules to move (leaf-first):**

1. `backend/app/domain/services/symbol_registry.py` → `quant/amt/session/symbol_registry.py`
   - Exports: `SymbolRegistry`. Imports `app.domain.models.exchange_config` → `quant.contracts.exchange_config`.
2. `backend/app/domain/services/initial_balance_engine.py` → `quant/amt/session/ib_engine.py`
   - Exports: `IBLocation`, `IBState`, `InitialBalanceEngine`. Pure.
3. `backend/app/domain/services/ib_breakout_scalp.py` → `quant/amt/session/ib_scalp.py`
   - Exports: `IBScalpType`, `IBScalpSignal`, `IBBreakoutScalpEngine`. Imports `ib_engine.IBState/IBLocation` → `quant.amt.session.ib_engine`.
4. `backend/app/domain/services/one_min_bar_engine.py` → `quant/amt/session/one_min_bar.py`
   - Exports: `OneMinBarState`, `OneMinBarEngine`. Pure.
5. `backend/app/domain/fabio_ai/services/eia_calendar.py` → `quant/amt/session/eia.py`
   - Exports: `EIAWindow`, `EIACalendar`. Imports `app.shared.timezones.IST` → `quant.contracts.timezones.IST`.
6. `backend/app/domain/fabio_ai/services/session_context.py` → `quant/amt/session/context.py`
   - Exports: `SessionInfo`, `get_session`, `opening_relation`, `get_session_info`, `classify_gap`, `prior_profile_key`, `persist_prior_profile`, `load_prior_profile`, `is_expiry_day`, `seconds_to_close`, `opening_inventory_bias`, `get_ib_window`, `get_vwap_anchors`, `get_sub_session`, `is_late_session`, `get_amt_time_window`.
   - Imports: `app.shared.timezones.IST` → `quant.contracts.timezones.IST`; `app.core.async_boundary.ensure_sync_adapter_result` → `quant.contracts.sync_boundary.ensure_sync_adapter_result`.
7. `backend/app/domain/fabio_ai/services/session_context_factory.py` → `quant/amt/session/context_factory.py`
   - Exports: `SessionContextFactory`. Imports `session_context.get_session_info` → `quant.amt.session.context.get_session_info`; `app.domain.models.exchange_config.ExchangeConfig` → `quant.contracts.exchange_config.ExchangeConfig`; `symbol_registry.SymbolRegistry` → `quant.amt.session.symbol_registry.SymbolRegistry`.
8. `backend/app/domain/fabio_ai/services/npoc_tracker.py` → `quant/amt/session/npoc.py`
   - Exports: `NPOCTracker`. Imports `app.core.async_boundary` → `quant.contracts.sync_boundary`; `app.domain.ports.npoc` → `quant.contracts.ports.npoc`.
9. `backend/app/domain/services/underlying_futures_provider.py` → `quant/amt/session/futures_provider.py`
   - Exports: `build_futures_symbol`, `extract_option_date`, `InstrumentConfig`, `DualFeedMapping`, `UnderlyingFuturesProvider`.
   - **Sanctioned logic tweak:** the default `config_path` is computed from `Path(__file__).parent.parent.parent.parent / "config" / "instruments.json"` — verify where that resolves AFTER the move; adjust the number of `.parent` hops so it loads the SAME `config/instruments.json` file the backend loaded (compare by resolved absolute path; the file content must be identical). Keep `config_path` injectable. Document the final resolved path in your report.
10. `backend/app/domain/fabio_ai/services/option_selector.py` → `quant/amt/session/selector.py`
    - Exports: `OptionSelectorConfig`, `OptionSelection`, `ThetaCheck`, `OptionSelector`. Pure (uses datetime/date only).
11. `backend/app/domain/fabio_ai/services/option_scanner.py` → `quant/amt/session/scanner.py`
    - Exports: `ScanResult`, `OptionScannerService`, `ContractSwitchGuard`.
    - Imports `app.core.async_boundary.ensure_sync_adapter_result` → `quant.contracts.sync_boundary.ensure_sync_adapter_result`. It uses stdlib `ThreadPoolExecutor`/`as_completed` — those stay (stdlib). The broker is injected via `__init__`; do not change the interface. This is a sync-safe module (all broker calls go through `ensure_sync_adapter_result`), so move it whole — no async-shell split needed.

**Import-rewrite map (for moved files):**
- `app.domain.trading.models.*` → `quant.contracts.*`
- `app.domain.constants` → `quant.contracts.constants`
- `app.shared.timezones` → `quant.contracts.timezones`
- `app.core.async_boundary` → `quant.contracts.sync_boundary`
- `app.domain.models.exchange_config` → `quant.contracts.exchange_config`
- `app.domain.ports.<x>` → `quant.contracts.ports.<x>`
- `app.domain.services.symbol_registry` → `quant.amt.session.symbol_registry`
- `app.domain.services.initial_balance_engine` → `quant.amt.session.ib_engine`
- `app.domain.services.ib_breakout_scalp` → `quant.amt.session.ib_scalp`
- `app.domain.fabio_ai.services.session_context` → `quant.amt.session.context`
- `app.domain.fabio_ai.services.eia_calendar` → `quant.amt.session.eia`

**Shims** at each legacy path: `from quant.amt.session.<name> import *  # noqa: F401,F403`. Consumers that must keep working via shims: `amt_analyzer.py` (session_context functions, InitialBalanceEngine, option_selector), `trading_session.py` (InitialBalanceEngine, IBBreakoutScalpEngine, OneMinBarEngine, OptionSelector, session_context), `exit_coordinator.py`/`session_event_router.py`/`phase_manager.py`/`session_phase_manager.py` (get_session_info), `dhan_adapter`/`main.py` (option scanner, futures provider), `health.py` (OptionScannerService lazy).

**Tests to port** (find under `backend/tests/`; port ALL hits): session_context, session_context_factory, npoc_tracker, eia_calendar, option_scanner, option_selector, underlying_futures_provider, symbol_registry, initial_balance_engine, ib_breakout_scalp, one_min_bar_engine → `tests/quant/amt/session/`. (Also port any `test_sync_boundary`/`test_async_boundary` for the helper to `tests/quant/contracts/test_sync_boundary.py`.)

**Parity tests** via `assert_parity` (legacy shim vs moved) on fixed inputs:
- `session_context`: `get_session`, `classify_gap`, `opening_relation`, `seconds_to_close`, `is_expiry_day`, `get_sub_session` on fixed timestamps/dates.
- `eia_calendar`: `EIACalendar.is_suppressed`/`get_next_release` on fixed datetimes (patch the calendar's static data identically for both).
- `initial_balance_engine`: a fixed 30-candle series → `update`/`is_complete`/`ib_high`/`ib_low`/`classify_breakout`.
- `ib_breakout_scalp`: fixed `evaluate_setup_a` inputs.
- `option_selector`: fixed `select_strike`/`check_theta` inputs.
- `one_min_bar_engine`: a fixed tick stream.
- `symbol_registry` / `futures_provider`: fixed symbol lookups (futures_provider with an injected config path).
- Skip parity for scanner methods that hit the network/broker (note which you skipped).

**Verification (after EACH module):**
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
Report pass/skip/error counts; the 4 pre-existing errors (gymnasium + 3 httpx) must be unchanged.

**Zero-backend-import rule:** `grep -rn "import app\.\|from app\." quant/amt --include=*.py` → only `quant/amt/profile/factory.py`'s sanctioned `amt_analyzer` `# TODO(migration)`.

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-a4-report.md`: commit hashes, the futures_provider resolved default config path, parity-skips and why, test tails, remaining `# TODO(migration)` imports. Return: status, commits, one-line test summary, concerns.
