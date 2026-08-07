# WS-ENV Report — integration + brokers suites green

**Worktree:** `/Users/apple/Documents/wt-ws-env` (branch `migration/ws-env`)
**Interpreter:** `/Users/apple/miniconda3/envs/amt_313/bin/python` (httpx 0.28.1, pyotp 2.10.0)

## Status: DONE — all four suites green (0 failed / 0 errors)

| Suite | Passed | Skipped | Failed | Errors |
|-------|-------:|--------:|-------:|-------:|
| backend `tests/unit` | 1330 | 61 | 0 | 0 |
| backend `tests/integration` | 156 | 24 | 0 | 0 |
| backend `tests/validation` | 52 | 4 | 0 | 0 |
| `brokers/tests` | 152 | 7 | 0 | 0 |
| **Totals** | **1690** | **96** | **0** | **0** |

## Commits (2, on `migration/ws-env`)

1. `a6cda7d` **fix(test): align stale integration contract + trading_state getattr guard**
2. `046f68f` **fix(test): market-hours guard for live streaming tests**

## What was fixed

### Real product bug (unblocked by httpx install)
- `backend/app/application/services/trading_session.py:456,717` — `session.trading_state` was accessed directly on `SessionState`, a dataclass that never declares the field; `set_symbol_trading_state()` sets it dynamically, so fresh sessions raised `AttributeError` and dropped every tick (`test_client_driven_tick` WebSocket test). Changed both sites to `getattr(session, "trading_state", "TRADABLE")`, matching the existing `get_symbol_trading_state()` pattern.

### Stale tests exposed by the config-collapse / UI-field-cut refactors
- `tests/integration/test_runtime_contracts.py:612` — the fake `_mode_config` monkeypatch lacked `system_config`, which `app/main.py:221` now reads after commit `88daff8`; added `system_config` to the `SimpleNamespace`.
- `tests/integration/test_frontend_integration.py` — `test_client_driven_tick` and `test_portfolio_dto_keys` asserted `stats`, `history`, `playbookGuard`, `explainabilityMonitor`, `modelWeights` that were deliberately removed from the snapshot/DTO contract in `6afc4e9` (frontend + unit test already updated; integration tests left stale). Dropped dead-key assertions and pruned the mock payload to the current contract.
- `tests/integration/test_e2e_trading_lifecycle.py:77` — dropped the stale `"stats" in state` assertion (same deliberate removal).

### Test isolation bug (persistent journal state)
- `tests/integration/test_api_endpoints.py::test_compute_stats_empty` — POSTs `closedTrades: []`, which the router treats as "empty body → journal fallback" (`build_stats_from_journal`), so it returned trades accumulated in the persistent `live_trading_logs/journal_*.jsonl`. Overrode `get_trade_journal` with an empty stub so the test is deterministic.

### Task 2 — market-hours guard for live-data tests
- `brokers/tests/test_integration_market_data.py` — added `_skip_if_market_closed(market)` alongside `_skip_if_no_creds()`. It derives windows from `quant.contracts.timezones.IST` (no hardcoded UTC offsets): NSE 09:15–15:30 IST, MCX evening 17:00–23:00 IST. Applied to the live Dhan tests that need live prints: `test_get_quote_nifty` (NSE), `test_get_quotes_batch` (NSE), `test_get_option_chain_nifty` (NSE), and `test_stream_ticker_2_ticks` (MCX evening, `stream_full` on CRUDEOIL). Verified at run time: NSE guard active during market hours, MCX guard skips when the evening session is closed even with creds set. `test_get_expiries_nifty` and `test_get_historical_crudeoil` are static/historical (24/7) and were left unguarded to avoid over-skipping. Pre-existing timeout-fallback skip (`Only N tick(s) received`) retained as a second safety net.

### Task 4 — httpx/pyotp ImportError tests
- None existed. `test_optimizations.py` uses `pytest.importorskip("httpx")`, which is now a real (passing) test rather than a skip; no test asserted an ImportError that is now wrong.

## Concerns
- **Live tests need creds to truly exercise the guard.** DHAN_* env vars are not set in this shell, so live Dhan tests SKIP at `_skip_if_no_creds()`; the market-hours guard was validated by direct invocation with creds forced. A CI job with real creds outside market hours is needed to confirm end-to-end.
- `brokers/tests` still emits a `PytestUnknownMarkWarning` for `pytest.mark.integration` (mark not registered in a pytest.ini). Harmless but noisy; registering the mark would silence it.
- The persistent `glassytrade.db` / `live_trading_logs/` are gitignored runtime artifacts but can leak state into API tests (the `test_compute_stats_empty` fix removes the only known dependency).
