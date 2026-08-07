# WS-PT-DI Report — Dead DI registrations + dead event/circuit code + dead flags

**Branch:** `migration/pt-di` (worktree `/Users/apple/Documents/wt-pt-di`)
**Date:** 2026-08-07
**Status:** ✅ COMPLETE — all 3 commits landed, verification green.

Grep-first guard applied to the whole repo (`backend/app`, `backend/tests`, `quant/`, `tests/`, `brokers/`). Anything with a live reference was kept and reported below.

---

## Commit 1 — `refactor(backend): remove dead DI registrations and adapters`

### DELETED (provably unreferenced outside the composition root)
- DI registration `INotification → NullNotificationAdapter` in `backend/app/application/di/composition_root.py`
  (`_notification_port()` getter, `_create_notification_adapter()` factory, registration block).
- DI registration `INPOC → NPOCAdapter` in `composition_root.py`
  (`_npoc_port()` getter, `_create_npoc_adapter()` factory, registration block).
- `backend/app/infrastructure/adapters/null_notification_adapter.py`
- `backend/app/infrastructure/adapters/npoc_adapter.py`

Evidence: the only non-DI references to these were self-references. The live `INotificationAdapter`
port (`quant.contracts.ports.notification_adapter`) used by `telegram_adapter.py`, `mobile_alerts.py`,
`trading_session.py` is a DIFFERENT port and was untouched. `INPOC` port + `NPOCTracker`
(`quant/amt/session/npoc.py`) are live and were kept — only the dead adapter wrapper + registration were removed.
Nothing in `app/` or tests ever calls `container.resolve(INotification)` / `container.resolve(INPOC)`.

### KEPT WITH REFERENCES (reported)
- **`IDeltaProfile → delta_profile_adapter`** — KEPT. `backend/tests/unit/test_delta_profile.py`
  (17 test cases) imports `DeltaProfileAdapter` directly. Deleting breaks the suite → keep + report.
- **`IExchangeStrategy → mcx_strategy/nse_strategy`** — KEPT. `backend/tests/unit/domain/test_exchange_abstraction.py`
  imports `NSEExchangeStrategy`/`MCXExchangeStrategy` directly AND `test_di_container_wiring`
  resolves `IExchangeStrategy` from the real `compose_container()`. Deleting breaks the suite → keep + report.
- Files kept: `backend/app/infrastructure/adapters/delta_profile_adapter.py`,
  `backend/app/infrastructure/strategies/{mcx_strategy,nse_strategy}.py`.

---

## Commit 2 — `refactor(backend): remove dead event store and circuit-breaker shim`

### DELETED
- `backend/app/core/events.py` — `EventStore`/`Event`/`publish_event` (test-only). Sole valid reference
  was its test file; test deleted. NOTE: `brokers/scripts/demo_option_scanner.py` and
  `brokers/scripts/test_scanner_dhan_integration.py` import `app.core.events.EventBus` — a symbol that
  **never existed** in that module (they also import dead `app.data.*` / `app.engine.*`). They are already-broken
  demo scripts in WS-PT-BROKERS scope; not valid references, deletion cannot break them further.
- `backend/tests/unit/core/test_events.py` — orphaned test of the deleted store.
- `backend/app/application/events/` package — `__init__.py`, `handler.py`, `resilient_wrapper.py`.
  Zero external callers (grep over repo: only intra-package imports). Confirmed and deleted.
- `backend/app/core/circuit_breaker.py` (123-line shim over `shared.resilience`) — replaced the sole
  production reference and deleted the shim.
- `backend/tests/unit/core/test_circuit_breaker.py` — orphaned test of the deleted shim.

### REPLACED
- `backend/app/api/routers/observability.py` — import swapped from
  `app.core.circuit_breaker import get_amt_circuit, get_session_circuit` →
  `shared.resilience import get_amt_circuit, get_session_circuit`.
  `shared.resilience.CircuitBreaker.get_metrics()` returns the identical key set
  (`state`, `failure_count`, `success_count`, `last_failure_time`), so `/metrics/circuit-breakers` is unchanged.
- `shared/resilience.py` was NOT modified (it already exposes `get_amt_circuit()` / `get_session_circuit()`
  / `get_position_circuit()` globals).

---

## Commit 3 — `refactor(backend): remove dead feature flags`

All 6 flags were config-stack-only (no production code read them to gate behavior). Each flag's only
"gated code" was config plumbing, which was removed with it.

### DELETED (flag definitions + their gated/usage code)
- `backend/app/config_models/__init__.py` — removed from `FeatureFlags`:
  `duckdb_storage`, `initial_balance_engine`, `correlation_guard`, `iv_vix_features`,
  `shap_feature_pruning`, `llm_entry_gate`.
- `backend/app/config_models/loader.py` — removed the 6 constructor kwargs + 6 startup-log entries.
- `backend/app/config_models/validator.py` — removed **RULE-3** (`llm_entry_gate` must be false in live).
  This was the only code gated by a target flag; unreachable because the flag is hardcoded false and
  never set true in any env. (RULE-1/2/4+ numbering kept as-is; RULE-3 simply no longer exists.)
- `backend/config/consolidated.py` — removed `llm_entry_gate` Field + its merge mapping line.
- `backend/config/feature_flags.yaml` — removed all 6 flag entries (plus their comments).
- `backend/config/environments/live.yaml` — removed `correlation_guard: true`.
- `backend/tests/unit/domain/test_config_architecture.py` — removed `test_rule3_live_requires_llm_entry_gate_false`;
  updated `test_defaults` (dropped `llm_entry_gate` assert) and `test_immutable`
  (now mutates `llm_overseer` — frozen dataclass still raises `AttributeError`).

### KEPT FLAGS / NON-ISSUES
- `llm_entry_gate`: no live code is gated by it. The real LLM entry feature runs off
  `feature_enabled(settings, Feature.LLM_EXECUTION)` + `session_event_router.trigger_llm_entry()`,
  which are independent of the dead flag. Deleting the flag does not disable LLM entry.
- `initial_balance_engine`: shares a name with the LIVE `InitialBalanceEngine` in `quant/amt/session/`.
  That engine is NOT gated by the config flag (`tests/quant/amt/session/test_ib_engine.py::test_initial_balance_engine_parity`
  tests the engine directly). Only the dead config flag was removed; the engine is untouched.

---

## Verification

| Check | Result |
|---|---|
| Baseline `pytest tests/unit` (pre-change) | 1323 passed, 64 skipped, 0 failed, 0 errors |
| Final `pytest tests/unit -q --tb=short --continue-on-collection-errors` | **1311 passed, 64 skipped, 0 failed, 0 errors** |
| `PYTHONPATH=backend python -c "import app.main"` (from repo root) | **SMOKE OK** (config loads, FeatureFlags no longer lists `llm_entry_gate`) |
| `git status` | clean; on `migration/pt-di` |

Test-count delta (−12) == exactly the removed test bodies (8 circuit-breaker + 3 event-store + 1 RULE-3).

## Commits (3)
1. `4d2ffed refactor(backend): remove dead DI registrations and adapters`
2. `c452bef refactor(backend): remove dead event store and circuit-breaker shim`
3. `c54af16 refactor(backend): remove dead feature flags`

## Concerns
1. **Broken legacy demo scripts** — `brokers/scripts/{demo_option_scanner,test_scanner_dhan_integration}.py`
   still import the never-existent `app.core.events.EventBus` and dead `app.data.*`/`app.engine.*` modules.
   Already broken pre-change; owned by WS-PT-BROKERS. Flagging so they aren't mistaken for live references later.
2. **Stale generated artifacts** (not committed, harmless):
   - `backend/shared.egg-info/SOURCES.txt` still lists deleted `null_notification_adapter.py` and the
     already-stale `initial_balance_engine.py` — regenerated on next `pip install -e`.
   - `.hypothesis/constants/*` and `.pytest_cache/v/cache/nodeids` still contain deleted symbol names — regenerated by tooling.
3. **Not deleted (by design, guard)** — `delta_profile_adapter` and `mcx/nse_strategy` are kept because
   their test files (`test_delta_profile.py`, `test_exchange_abstraction.py`) exercise them directly and one
   test resolves `IExchangeStrategy` from the real container. If a future pass deletes those tests, the
   registrations/adapters become removable.
