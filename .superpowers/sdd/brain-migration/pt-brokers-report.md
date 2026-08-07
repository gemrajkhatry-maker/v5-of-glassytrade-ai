# WS-PT-BROKERS Report — ponytail audit adoption in `brokers/`

**Worktree:** `/Users/apple/Documents/wt-pt-brokers` (branch `migration/pt-brokers`)
**Date:** 2026-08-07
**Status:** DONE — all adopted deletions applied, verified, committed.

## Summary

Removed ~4,925 lines of dead/demo weight from `brokers/`. All required verification suites pass. No live backend coupling was touched.

## Deleted files (grep-first, zero live references confirmed)

### Commit 1 — `27f5571 chore(brokers): delete demo scripts and dead broker modules` (23 files, −4,704 lines)

| File | Reason |
|---|---|
| `brokers/scripts/api_patterns.py` | demo entry point |
| `brokers/scripts/demo_option_scanner.py` | demo entry point |
| `brokers/scripts/fetch_heg_data.py` | demo entry point |
| `brokers/scripts/integration_guide.py` | demo entry point |
| `brokers/scripts/live_api_demo.py` | demo entry point |
| `brokers/scripts/option_scanner_rx.py` | demo entry point |
| `brokers/scripts/test_20level_depth_live.py` | demo entry point |
| `brokers/scripts/test_connection.py` | demo entry point |
| `brokers/scripts/test_full_quote_and_depth_live.py` | demo entry point |
| `brokers/scripts/test_new_features.py` | demo entry point |
| `brokers/scripts/test_nse_mcx_live.py` | demo entry point |
| `brokers/scripts/test_scanner_dhan_integration.py` | demo entry point |
| `brokers/scripts/test_tcs_all_feeds_live.py` | demo entry point |
| `brokers/scripts/verify_e2e_nse_mcx.py` | demo entry point |
| `brokers/broker/bulk_historical.py` | only importers were `brokers/scripts/` + orphaned test |
| `brokers/broker/dhan/infrastructure/http_client_sync.py` | only importer was `dhan/infrastructure/__init__.py` re-export + one test (zero live callers). NOTE: no `brokers/broker/http_client_sync.py` exists; the audit target mapped to the dhan infrastructure sync helper (legacy sync-only path, main path is async `DhanHttpClient`). |
| `brokers/broker/symbol_matcher.py` | dup of `brokers/broker/utils/symbol.py` (`SymbolMatcher`); only importer was `brokers/scripts/` + orphaned test |
| `brokers/broker/mcx_futures.py` | only importer was `brokers/scripts/` + orphaned test |
| `brokers/tests/test_bulk_historical.py` | orphaned (module deleted) |
| `brokers/tests/test_symbol_matcher.py` | orphaned (module deleted) |
| `brokers/tests/test_mcx_futures.py` | orphaned (module deleted) |

Edits in Commit 1:
- `brokers/broker/dhan/infrastructure/__init__.py` — dropped `DhanHttpClientSync` re-export
- `brokers/broker/dhan/tests/test_auth_wiring.py` — removed orphaned `TestSyncClientSetToken`

### Commit 2 — `27bde38 chore(brokers): remove dead DhanConfig fields + TOTP → pyotp` (10 files, −221 lines)

| File | Change |
|---|---|
| `brokers/broker/dhan/application/config.py` | removed dead `DhanConfig` fields `retry_delay`, `rate_limit_per_second`, `circuit_breaker_threshold`, `circuit_breaker_timeout` (parsed from env, never passed on — confirmed: `broker.py` only reads `client_id/access_token/base_url/ws_url/timeout/totp_secret/pin`); removed their env parsing in `from_env` and `with_access_token`; dropped now-unused `RATE_LIMIT_DEFAULT` import |
| `brokers/broker/dhan/infrastructure/totp_generator.py` | **deleted** — replaced with `pyotp.TOTP(...)` used directly in `auth_provider.py` (`with_offset`/window-offset support kept via new `_generate_totp_code(window_offset)` helper) |
| `brokers/broker/dhan/infrastructure/auth_provider.py` | uses `pyotp.TOTP` directly (`self._totp`), guarded import (env lacks pyotp — preserved graceful degradation); added `_generate_totp_code(window_offset=0)` |
| `brokers/broker/dhan/infrastructure/__init__.py` | dropped `TOTPGenerator`/`TOTPGenerationError` exports |
| `brokers/broker/dhan/__init__.py` | dropped `TOTPGenerator`/`TOTPGenerationError` exports |
| `brokers/tests/test_dhan_broker.py` | removed orphaned `TestTOTPGenerator` class + dead-field assertion |
| `brokers/broker/dhan/tests/test_application.py` | removed dead-field assertions |
| `brokers/broker/dhan/tests/test_infrastructure.py` | `_totp_generator` → `_totp` |
| `brokers/broker/dhan/tests/test_auth_wiring.py` | `_totp_generator` → `_totp` |
| `brokers/broker/dhan/tests/conftest.py` | dropped dead fields from `dhan_config` fixture |

### Commit 3 — ML deps (`torch/transformers/peft/accelerate`)

**NOT NEEDED — already clean.** `brokers/requirements.txt` never contained torch/transformers/peft/accelerate; verified **zero imports** of these across the worktree (`grep` for `import torch|transformers|peft|accelerate` → no matches). They exist only in `backend/requirements.txt` (out of scope — backend ValentiniTrainer). No commit created for this item.

## Guard results — LIVE coupling (kept, not deleted)

- `brokers/gateway.py` (`BrokerGateway`, `BrokerFactory`) — **LIVE**, kept. Re-exported by `brokers/__init__.py`; used by `brokers/tests/test_gateway.py`, `test_broker_interface.py`, `test_e2e_nse_mcx.py`, `test_integration_market_data.py`.
- `brokers/broker/ports.py` (`IBrokerPort`, `CircuitBreakerWrapper`) — **LIVE**, kept. `CircuitBreakerWrapper` used by `gateway.py`; `IBrokerPort` re-exported by `brokers/` and `brokers/broker/`.
- `brokers/broker/dhan/application/facade.py` (`DhanFacade`) — **LIVE**, kept. Re-exported by `brokers/broker/dhan/__init__.py` and `dhan/application/__init__.py`.
- `brokers/broker/types.py`, `brokers/broker/entities.py`, `brokers/broker/dhan/application/broker.py` (`DhanBroker`) — **LIVE**, kept. Imported by backend:
  - `backend/app/infrastructure/adapters/dhan_broker_adapter.py` → `Exchange`, `Instrument`, `Order`, `OrderStatus`, `OrderType`, `OptionType`, `DhanBroker`, `DhanError`
  - `backend/app/infrastructure/adapters/dhan_adapter.py` → `DhanBroker`, `Instrument`, `OptionType`, `Exchange`
- No deletion touched `types.py`, `entities.py`, `ports.py`, `gateway.py`, `facade.py`, or `dhan/application/broker.py`.

## Verification (exact counts)

| Suite | Result |
|---|---|
| `pytest brokers/tests -q --tb=short` | **152 passed, 7 skipped, 0 failed** |
| `cd backend && pytest tests/unit/infrastructure/test_dhan_adapter_v2.py test_dhan_broker_adapter.py test_lot_size.py -q --tb=short` | **35 passed** (0 failed) — live broker coupling intact |

Supplementary check (`brokers/tests` + `brokers/broker/dhan/tests`): 486 passed / 11 failed / 9 skipped. All 11 failures are **pre-existing in this env** (verified by stashing my changes: base = 13 failures including the 2 `TestTOTPGenerator` class tests; the remaining 11 are the pyotp-missing TOTP tests + unrelated `TestStreamFull` ×2 + `test_feed_type_constants`). Net effect of this workstream: 13 → 11 failures. The env (`amt_313`) does not have `pyotp` installed even though `brokers/requirements.txt` declares `pyotp>=2.9.0`; `auth_provider.py` keeps a guarded import so the live path degrades gracefully, exactly as the old `TOTPGenerator` did.

## Concerns

1. **`http_client_sync` path mismatch:** plan said `broker/http_client_sync.py` (top-level) — that file never existed; the only one is `brokers/broker/dhan/infrastructure/http_client_sync.py` (zero live callers). Deleted that one as the clear audit target.
2. **`pyotp` not installed in `amt_313` env:** TOTP auto-generation is inert until the env is provisioned with `requirements.txt`. Behavior unchanged from before (old code had the same `ImportError` guard); flagged so provisioning isn't assumed.
3. **Commit 3 omitted** (nothing to drop — `brokers/requirements.txt` was already clean; torch/transformers/peft/accelerate live only in `backend/requirements.txt`).
4. No `.superpowers/`, `docs/superpowers/plans/`, or `docs/*.md` files were committed; the only main-repo write is this report.
