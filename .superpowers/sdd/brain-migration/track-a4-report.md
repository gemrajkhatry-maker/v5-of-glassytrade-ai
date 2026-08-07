# Track A4 Report — Session/options/IB cluster → `quant/amt/session/`

**Branch:** `stable_4`
**Status:** DONE
**Date:** 2026-08-06

## Summary

Ported the session-context / NPOC / EIA / option-scanner-selector / futures-provider / symbol-registry / IB cluster from the backend brain into `quant/amt/session/` using the move-with-shim + parity recipe from prior tracks. Step 0 moved the sync/async boundary helpers into `quant/contracts/sync_boundary.py`. Eleven modules moved leaf-first, one commit each, all logic byte-identical (import rewrites only, plus the one sanctioned `futures_provider` config-path tweak). Re-export shims left at every legacy path. Both quant + backend suites stay green throughout. The only remaining `# TODO(migration)` backend import in `quant/amt/` is the sanctioned Track A5 one.

## Commits (in order, deps first)

| Commit | Description |
|---|---|
| `8ffbffa` | `feat(quant): move sync/async boundary helpers to quant.contracts` — `quant/contracts/sync_boundary.py` (verbatim copy of `backend/app/core/async_boundary.py`, original left in place) + `tests/quant/contracts/test_sync_boundary.py` |
| `d934f5d` | `refactor(quant): move symbol_registry from backend brain` → `quant/amt/session/symbol_registry.py` |
| `1b1acb8` | `refactor(quant): move initial_balance_engine from backend brain` → `quant/amt/session/ib_engine.py` |
| `dc6657d` | `refactor(quant): move ib_breakout_scalp from backend brain` → `quant/amt/session/ib_scalp.py` |
| `a017337` | `refactor(quant): move one_min_bar_engine from backend brain` → `quant/amt/session/one_min_bar.py` |
| `e0c3b02` | `refactor(quant): move eia_calendar from backend brain` → `quant/amt/session/eia.py` |
| `4cdbfcb` | `refactor(quant): move session_context from backend brain` → `quant/amt/session/context.py` |
| `8d5c182` | `refactor(quant): move session_context_factory from backend brain` → `quant/amt/session/context_factory.py` |
| `7ce29c2` | `refactor(quant): move npoc_tracker from backend brain` → `quant/amt/session/npoc.py` |
| `283468d` | `refactor(quant): move underlying_futures_provider from backend brain` → `quant/amt/session/futures_provider.py` |
| `ab99abf` | `refactor(quant): move option_selector from backend brain` → `quant/amt/session/selector.py` |
| `7614610` | `refactor(quant): move option_scanner from backend brain` → `quant/amt/session/scanner.py` |

All 11 source moves used `git mv` (history preserved). Each legacy path now holds a re-export shim:
`from quant.amt.session.<name> import *  # noqa: F401,F403` with a "Delete in Phase 3" docstring.

## Import-rewrite map applied

- `app.domain.trading.models.*` → `quant.contracts.*` (ib_engine, one_min_bar: `value_objects.OHLC`; context_factory TYPE_CHECKING `value_objects.OHLC`)
- `app.shared.timezones` → `quant.contracts.timezones` (eia, context, one_min_bar: `IST`)
- `app.core.async_boundary` → `quant.contracts.sync_boundary` (context, npoc, scanner: `ensure_sync_adapter_result`)
- `app.domain.models.exchange_config` → `quant.contracts.exchange_config` (symbol_registry, context_factory: `ExchangeConfig`)
- `app.domain.ports.npoc` → `quant.contracts.ports.npoc` (npoc: `INPOC`/`NPOCRecord`/`NPOCResult`)
- `app.domain.services.symbol_registry` → `quant.amt.session.symbol_registry` (context_factory)
- `app.domain.services.initial_balance_engine` → `quant.amt.session.ib_engine` (ib_scalp: `IBState`, `IBLocation`)
- `app.domain.fabio_ai.services.session_context` → `quant.amt.session.context` (context_factory: `get_session_info`)
- `app.domain.fabio_ai.services.eia_calendar` → `quant.amt.session.eia` (n/a — no intra-cluster import)

Verified via diff: every moved module's logic is byte-identical to its pre-move source (only import lines changed), except the sanctioned `futures_provider` default `config_path` tweak below.

## Sanctioned logic tweak — `futures_provider` default `config_path`

Before the move, `Path(__file__).parent.parent.parent.parent / "config" / "instruments.json"` resolved to:
`/Users/apple/Documents/v5-of-glassytrade-ai/backend/config/instruments.json` (from `backend/app/domain/services/`).

After the move, the same 4-parent expression resolves to `<repo-root>/config/instruments.json`, which does **not** exist. Adjusted to:
`Path(__file__).parent.parent.parent.parent / "backend" / "config" / "instruments.json"`

**Final resolved default path (documented):**
`/Users/apple/Documents/v5-of-glassytrade-ai/backend/config/instruments.json`

Verified equal to the pre-move resolved absolute path, and file content is byte-identical (`read_bytes()` equal). `config_path` remains injectable (used by all ported/parity tests). A dedicated test (`test_futures_provider_default_path_resolves_same_file` in `tests/quant/amt/session/test_futures_provider_parity.py`) pins this resolution.

## Zero-backend-import rule

`grep -rn "import app\.\|from app\." quant/amt --include=*.py` → exactly one hit:

```
quant/amt/profile/factory.py:17:from app.domain.fabio_ai.services.amt_analyzer import IncrementalVolumeProfile
```

(with its `# TODO(migration): switch to quant.amt.analyzer once Track A5 lands` comment). This is the only sanctioned Track A5 import — satisfies the brief.

## Tests

### Ported backend unit tests → `tests/quant/amt/session/`

| Ported file | Source |
|---|---|
| `test_symbol_registry.py` | `backend/tests/unit/domain/test_exchange_abstraction.py::TestSymbolRegistry` + `backend/tests/unit/domain/test_exchange_isolation.py::TestExchangeIsolation` (registry parts) |
| `test_ib_engine.py` | `backend/tests/unit/domain/test_ib_and_short.py::TestInitialBalanceEngine` |
| `test_ib_scalp.py` | no dedicated backend test existed (zero grep hits) — new unit tests mirroring port style |
| `test_one_min_bar.py` | no dedicated backend test existed (zero grep hits) — new unit tests mirroring port style |
| `test_eia.py` | `backend/tests/unit/domain/test_eia_calendar.py` |
| `test_context.py` | `backend/tests/unit/domain/test_session_context.py` |
| `test_context_factory.py` | `backend/tests/unit/test_session_context_factory.py` |
| `test_npoc.py` | `backend/tests/unit/test_npoc_tracker.py` |
| `test_futures_provider.py` | `backend/tests/unit/domain/test_underlying_futures.py` |
| `test_selector.py` | `backend/tests/unit/domain/test_option_scanner.py::TestOptionSelector` |
| `test_scanner.py` | `backend/tests/unit/domain/test_option_scanner.py::TestOptionScannerService` (un-skipped) + the two standalone mini-chain config tests |
| `test_sync_boundary.py` (`tests/quant/contracts/`) | no backend test existed — new unit tests for the moved helper |

The `TestOptionScannerService` class carries a pre-existing `pytest.mark.skip(reason="Pre-existing option scanner assertion")` in the backend suite. The ported tests actually pass against the mock broker (verified), so the port runs them — except `test_scanner_passes_exchange_string`, which has a pre-existing wrong assertion (`NIFTY` auto-detects as `NFO`, not `MCX`); it keeps the pre-existing skip with an explanatory reason, consistent with Track A3's treatment of pre-existing skips.

### Parity tests (via `assert_parity` from `tests.quant.parity`)

| Parity file | Cases | Result |
|---|---|---|
| `test_symbol_registry.py` | `exchange_for`/`is_mcx`/`is_nse`/`is_option` across 20 fixed symbols; `all_underlyings` | PASS |
| `test_ib_engine.py` | fixed 30-candle series → `update`/`state`, `ib_high`/`ib_low`/`ib_mid`/`ib_width`/`is_complete`, `classify_breakout` | PASS |
| `test_ib_scalp.py` | 7 fixed `evaluate_setup_a` input sets (IB-not-complete, zero-width, volume/CVD rejections, valid LONG/SHORT retest, no breakout) | PASS |
| `test_one_min_bar.py` | fixed 40-tick stream across 4 1-min bars → per-tick `OneMinBarState` | PASS |
| `test_eia.py` | `is_suppressed` across 7 fixed ET datetimes (incl. boundaries), `get_next_release` across 3 (static schedule identical on both sides, no patching needed) | PASS |
| `test_context.py` | `get_session` (13 timestamps), `classify_gap` (7), `opening_relation` (4), `seconds_to_close` (5), `is_expiry_day` (5), `get_sub_session` (5×2 exchanges), `get_session_info` (3 markets × 13 timestamps) | PASS |
| `test_npoc_parity.py` | `active_npocs` + `get_active_npocs` (incl. lookback) after fixed add sequence; duplicate-skip | PASS |
| `test_futures_provider_parity.py` | `get_mapping` for 8 fixed symbols (same injected config path on both sides); `build_futures_symbol`/`extract_option_date`; default-path resolution pinned to same file | PASS |
| `test_selector.py` | `select_strike` (7 underlyings × LONG/SHORT), `select_strike` with a fixed gamma×volume chain, `check_theta` (3 options × 3 hold/target combos) | PASS |
| `test_scanner_parity.py` | config maps equality + `_score_contract` across 4 fixed inputs | PASS |

### Parity skips and why

- **Scanner network/broker paths** (`scan_top_n`, `_scan_underlying_for_contracts`, `_detect_momentum`, `ContractSwitchGuard` timing logic) — skipped: they call `broker.get_option_chain` via `ensure_sync_adapter_result` (real broker I/O) or depend on `time.time()`. Behavior is covered by the ported unit tests with a mocked broker; `_score_contract` (pure) is parity-compared.

## Test tails

- **Quant suite** (repo root): `pytest tests/quant -q --tb=short` → **825 passed, 5 skipped**. Baseline (start of track) was 672 passed, 4 skipped; +153 (ported + parity + sync-boundary tests).
- **Session cluster only**: `pytest tests/quant/amt/session -q --tb=short` → **147 passed, 1 skipped**.
- **Backend unit suite** (`cd backend && pytest tests/unit -q --tb=short --continue-on-collection-errors`): **1625 passed, 60 skipped, 4 errors** — identical pass/skip counts to the Track A3 tail; the 4 errors are the unchanged pre-existing environment failures (`gymnasium` in `test_valentini_rl.py` collection; 3 `httpx` `TestDebugMemoryEndpoint` errors in `test_optimizations.py`). Verified untouched: `git diff 7614610~1..HEAD -- backend/tests/unit/domain/test_valentini_rl.py backend/tests/unit/test_optimizations.py` is empty.

## Concerns

1. **Pre-existing skip in ported scanner test:** `test_scanner_passes_exchange_string` has a wrong assertion in the source (`NIFTY` auto-detects as `NFO` exchange, not the `exchange="MCX"` argument) — this is exactly why the whole `TestOptionScannerService` class was pre-existing-skipped in the backend suite. Kept skipped in the port with the reason preserved.
2. **No dedicated backend tests existed** for `ib_breakout_scalp` or `one_min_bar_engine` (zero grep hits). Coverage comes from new unit + parity tests written in the established port style.
3. **No backend test for the sync-boundary helper existed** — `tests/quant/contracts/test_sync_boundary.py` is a new unit test. The original `backend/app/core/async_boundary.py` is untouched (it has other consumers), per the brief.
4. **futures_provider default path is now backend-coupled** — the sanctioned tweak hardcodes `backend/config` in the default. Documented at the code site and pinned by a test; Phase 3 consolidation should decide whether `instruments.json` moves to the repo-root `config/`.
5. **`one_min_bar.py` imports `IST` but never uses it** — this is a pre-existing unused import carried over byte-identically (per "keep logic byte-identical"); the import was rewritten to `quant.contracts.timezones` as required.
