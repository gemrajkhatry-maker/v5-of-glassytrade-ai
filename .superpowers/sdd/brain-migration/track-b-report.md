# Track B Report — Decision & gates cluster → `quant/decision/`

**Branch:** `migration/track-B` (worktree `/Users/apple/Documents/wt-gt-track-B`)
**Date:** 2026-08-06
**Status:** ✅ COMPLETE — all modules moved, shims in place, both suites green.

## Summary

Moved the remaining backend decision/gates cluster into `quant/decision/gates/` with
byte-identical logic (imports rewritten only), re-export shims at every legacy path,
ported backend tests, and `assert_parity` differential tests. The three already-moved
modules (sizer, signal_coordinator, trade_thesis) were skipped as instructed — parity
tests were still added for them.

## Commit hashes (new, oldest → newest)

| Hash | Message |
|---|---|
| `28316f9` | refactor(quant): move gate_pipeline from backend brain |
| `2392727` | refactor(quant): move confirmation_bundle from backend brain |
| `c971e12` | refactor(quant): move grading from backend brain |
| `76d0d9c` | refactor(quant): move three_align from backend brain |
| `49846ec` | refactor(quant): move signal_builder from backend brain |
| `559cdc2` | refactor(quant): move gate_runner from backend brain |
| `67a82e7` | refactor(quant): add entry_gates shim to quant.decision.gates |
| `10457aa` | refactor(quant): move scalp_gate_pipeline from backend brain |
| `c1f3d5d` | refactor(quant): move short_signal_gates from backend brain |
| `5b48db1` | test(quant): port signal_coordinator tests and add parity for sizer/signal_coordinator/trade_thesis |
| `029ca71` | test(quant): port gate_13 session filter, golden_week1, and entry-gate audit-fix cases |

No `.superpowers/`, `docs/`, or `docs/**/*.md` files were committed (verified via
`git diff --name-only f29d646..HEAD`).

## Module mapping (all `git mv` + shim at legacy path)

| Legacy path | quant path | shim |
|---|---|---|
| `fabio_ai/services/gate_pipeline.py` | `quant/decision/gates/legacy_gate_pipeline.py` | `from quant.decision.gates.legacy_gate_pipeline import *` |
| `fabio_ai/services/entry_gates/confirmation_bundle.py` | `quant/decision/gates/confirmation_bundle.py` | `import *` |
| `fabio_ai/services/entry_gates/grading.py` | `quant/decision/gates/grading.py` | `import *` |
| `fabio_ai/services/entry_gates/three_align.py` | `quant/decision/gates/three_align.py` | `import *` |
| `fabio_ai/services/entry_gates/signal_builder.py` | `quant/decision/gates/signal_builder.py` | `import *` |
| `fabio_ai/services/entry_gates/gate_runner.py` | `quant/decision/gates/gate_runner.py` | `import *` |
| `domain/services/scalp_gate_pipeline.py` | `quant/decision/gates/scalp.py` | `import *` |
| `domain/services/short_signal_gates.py` | `quant/decision/gates/short.py` | `import *` |

## entry_gates `__init__.py` shim verification

Replaced with the sanctioned 5-line shim (`from quant.decision.gates.{confirmation_bundle,grading,three_align,signal_builder,gate_runner} import *`).
Verified all **16** previously-exported public symbols resolve through the shim and
each resolves to a `quant.decision.gates.*` module (checked programmatically):
`min_candles_gate, full_body_close_gate, nearest_round_number, cluster_aggressive_prints,
extract_bubble_levels_from_footprint, three_align_check, check_confirmation_bundle,
check_momentum_fade, compute_atr, build_entry_signal, sl_from_aggressive_print,
compute_grade_score, check_vwap_bias, check_imbalance_alignment, run_gate_pipeline,
calculate_position_size`.

## gate_runner loss_tracker TODO (Track D)

`quant/decision/gates/gate_runner.py:186` keeps the lazy legacy import with the
sanctioned TODO:
```python
# TODO(migration): switch to quant.execution.loss_tracker once Track D lands
from app.domain.fabio_ai.services.loss_tracker import LossTracker
```
Dynamic-risk path (`session_realized_pnl=...`) exercised by ported
`test_gate_runner_dynamic_risk.py`.

## Zero-backend-import rule

`grep -rn "import app\.\|from app\." quant/amt quant/decision` returns exactly 2 hits,
both sanctioned:
- `quant/amt/profile/factory.py:17` — `amt_analyzer` `# TODO(migration): switch to quant.amt.analyzer once Track A5 lands`
- `quant/decision/gates/gate_runner.py:186` — `loss_tracker` Track D TODO

## Parity tests (all use `tests.quant.parity.assert_parity`)

| Test file | Covers |
|---|---|
| `test_legacy_gate_pipeline_parity.py` | `GatePipeline.evaluate` — all-pass, warmup, EIA/session, R:R, risk-halt contexts |
| `test_confirmation_bundle_parity.py` | `compute_atr`, `check_confirmation_bundle` |
| `test_grading_parity.py` | `check_vwap_bias`, `check_imbalance_alignment`, `compute_grade_score` |
| `test_three_align_parity.py` | `three_align_check` (incl. golden mock), `cluster_aggressive_prints`, `min_candles_gate`, `full_body_close_gate`, `nearest_round_number` |
| `test_gates_entry_signal_builder_parity.py` | `sl_from_aggressive_print`, `build_entry_signal` (golden mock + trend) |
| `test_gate_runner_parity.py` | `run_gate_pipeline` — warmup-block, full-pass, risk-halt triples |
| `test_scalp_parity.py` | `evaluate_scalp_gates` — pass / default / blocked |
| `test_short_parity.py` | `evaluate_short_gates` + each `check_s*` gate |
| `test_sizer_parity.py` | `PositionSizer.calculate`, `apply_velocity_scaling` |
| `test_signal_coordinator_parity.py` | `SignalCoordinator.evaluate_entry` (4 scenarios) |
| `test_trade_thesis_parity.py` | `build_trade_thesis`, `validate_trade_thesis` (object/dict/None/incomplete) |

### AMTResult fields populated for `run_gate_pipeline` parity

Read the body first; it uses `amt_result.value_area_high/value_area_low/lvns/poc/setup`
and `getattr` fields `session_vwap`, `vwap_upper_1`, `absorption_side`. Built a minimal
`AMTResult` with `market_state/poc/value_area_high/value_area_low/setup` (defaults cover
the rest). No skips — all parity tests run.

## Ported tests

Backend tests `git mv`'d to `tests/quant/decision/` (`gates/` where module-scoped):
gate_pipeline (+slim/+soft_gates), gate_13_session_filter, dynamic_risk_sizing →
`test_gate_runner_dynamic_risk.py`, integration entry-signal chain →
`test_gate_runner_entry_signal_chain.py`, signal_coordinator, golden_week1, scalp, short.
Entry-gate test cases from `test_entry_gate.py`/`test_cushion_sl.py`/`test_amt_analyzer.py`/
`test_aggressive_prints.py` were ported into the per-module `test_{confirmation_bundle,grading,three_align,grading}.py`
files and the renamed `test_gates_entry_signal_builder*.py` (avoids collision with greenfield
`test_signal_builder.py`). Backend copies of those test files remain green through the shims.

## Test tails (final, after last commit)

- **`tests/quant`:** `1029 passed, 5 skipped, 1 warning` (baseline was 825/5)
- **`backend tests/unit`:** `1543 passed, 60 skipped, 4 errors` — the 4 errors are the
  pre-existing gymnasium (test_valentini_rl) + 3 httpx (test_optimizations) and are
  unchanged from baseline (1625 passed / 60 skipped / 4 errors; delta = 82 tests moved).

## Concerns

- The 4 backend errors are environmental (gymnasium / httpx deps), untouched by this track.
- `quant/decision/gates/signal_builder.py` (backend entry-gate version) coexists with the
  greenfield `quant/decision/signal_builder.py` (5-gate SignalBuilder) — kept separate per brief.
- `run_gate_pipeline` parity used synthetic `AMTResult`s; no field was skipped, but two
  `getattr`-guarded fields (`absorption_side`, `vwap_upper_1`) default to unpopulated in the
  synthetic fixture, so that branch of `_detect_vwap_breakout`/absorption is only covered
  indirectly by the ported unit tests.
- No remaining `# TODO(migration)` imports beyond the two sanctioned ones listed above.
