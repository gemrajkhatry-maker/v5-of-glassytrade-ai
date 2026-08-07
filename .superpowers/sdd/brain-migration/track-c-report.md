# Phase 1 Track C — Probability cluster → `quant/probability/`

**Status:** COMPLETE

**Worktree:** `/Users/apple/Documents/wt-gt-track-C` (branch `migration/track-C`)

## Modules moved (all into `quant/probability/`)

| Legacy path | New path |
|---|---|
| `backend/app/domain/probability/features.py` | `quant/probability/features.py` |
| `backend/app/domain/probability/playbook.py` | `quant/probability/playbook.py` |
| `backend/app/domain/probability/regime_classifier.py` | `quant/probability/regime.py` |
| `backend/app/domain/probability/regime_hysteresis_store.py` | `quant/probability/regime_hysteresis.py` |
| `backend/app/domain/probability/direction_timing.py` | `quant/probability/direction_timing.py` |
| `backend/app/domain/probability/sizing.py` | `quant/probability/sizing.py` |
| `backend/app/domain/probability/labels.py` | `quant/probability/labels.py` |
| `backend/app/domain/probability/agent_pipeline.py` | `quant/probability/agent_pipeline.py` |
| `backend/app/domain/probability/__init__.py` | → re-export shim over `quant.probability` (+ fabio_ai prompt-builder aliases) |

All module content kept logic byte-identical. Imports rewritten per the track map:
`app.domain.trading.models.*` → `quant.contracts.*`, `app.domain.constants` → `quant.contracts.constants`, `app.domain.probability.*` → `quant.probability.*`, `app.domain.ports.probability_inference` → `quant.contracts.ports.probability_inference` (TYPE_CHECKING).

Re-export shims left at all 8 legacy module paths (incl. `__init__.py`). All 19 names re-exported by the legacy `__init__.py` verified to resolve (12 probability names + 7 prompt-builder aliases).

## Sanctioned legacy imports (zero-backend-import rule)

`git grep "from app\.\|import app\." -- quant/**/*.py` currently shows only:

1. **`quant/probability/agent_pipeline.py:62-63`** — `from app.domain.fabio_ai.services.entry_gates.three_align import three_align_check` and `from app.domain.fabio_ai.services.entry_gates.gate_runner import run_gate_pipeline` with `# TODO(migration): switch to quant.decision.gates.* once Track B merges`. **Track B dependency.**
2. **`quant/amt/profile/factory.py:17`** — `amt_analyzer` TODO (pre-existing from stable_4/Track A5, unchanged).
3. `quant/contracts/trading_context.py:24-25` and `quant/contracts/ports/exchange_strategy.py:21` — pre-existing `# TODO(migration)` TYPE_CHECKING imports from earlier tracks (not new).

No other `app.*` imports added.

## Commits

| Hash | Message |
|---|---|
| `8b6bfdb` | refactor(quant): move regime from backend brain |
| `3ebe256` | refactor(quant): move features from backend brain |
| `557242a` | refactor(quant): move sizing from backend brain |
| `9a3ca25` | refactor(quant): move labels from backend brain |
| `4473332` | refactor(quant): move direction_timing from backend brain |
| `1a71af5` | refactor(quant): move playbook from backend brain |
| `acf0d4b` | refactor(quant): move regime_hysteresis from backend brain |
| `1cfa93e` | refactor(quant): move agent_pipeline from backend brain |
| `0193ef2` | refactor(quant): add probability shims, package exports, and ported tests |

Each module commit verified green individually (tests/quant + backend tests/unit) before the next. `agent_pipeline` moved last per the brief.

## Tests ported → `tests/quant/probability/`

- `test_agent_pipeline_playbooks.py` (7 passed, 1 pre-existing skip)
- `test_timing_probability.py` (8 passed)
- `test_agent_decision_flat_output.py` (4 passed)
- `test_feature_alignment.py` (1 passed, 1 parquet-data skip)

## Parity tests (`tests/quant/probability/test_probability_parity.py`)

Legacy shim vs moved module on fixed inputs via `assert_parity`: `extract_features` (BALANCED + IMBALANCED), `select_playbook` (4 regimes), `classify_regime` (3 cases incl. <20 candles → DEAD), `pick_direction`, `assess_timing` (2 playbooks), `kelly_size` (4 probs), `adjust_sl_tp` (4 cases incl. dynamic MFE), `calculate_timing_probability` (ENTER_NOW/WAIT/SKIP), and `run_agent_pipeline`.

**Parity skip note for `run_agent_pipeline`:** the full ENTER_NOW path calls `three_align_check`/`run_gate_pipeline` (Track B modules — not in this worktree). The parity test drives the FLAT/DEAD early-return path only (deterministic, no gate module touched); the `latency_us` field is excluded from comparison (timing-dependent across two calls). The gate-touching path is intentionally not parity-tested until Track B merges.

## Test tails

```
tests/quant        : 855 passed, 7 skipped, 1 warning (3.1s)
backend tests/unit : 1625 passed, 60 skipped, 4 errors (5.2s)
```

The 4 backend errors are the pre-existing env errors (unchanged): `test_valentini_rl.py` (missing `gymnasium`) and 3 × `test_optimizations.py` httpx/starlette-testclient errors.

## Concerns

1. **Track B merge ordering:** `quant/probability/agent_pipeline.py` still imports `three_align_check`/`run_gate_pipeline` from `app.domain.fabio_ai.services.entry_gates` — those must switch to `quant.decision.gates.*` once Track B merges (TODO marker in place). The legacy entry_gates modules still exist in this worktree, so nothing is broken today.
2. `quant/probability/__init__.py` re-exports the split-module functions (regime/direction_timing/sizing/playbook); `agent_pipeline.py` defines its own richer variants of several of these names. This mirrors the legacy layout exactly (same duplication existed before the move) — no behavior change introduced.
3. Parity for `run_agent_pipeline` deliberately avoids the gate path (see skip note) — a true ENTER_NOW parity test should be added after Track B.
