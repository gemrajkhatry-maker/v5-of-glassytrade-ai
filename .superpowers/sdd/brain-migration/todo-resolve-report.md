# TODO(migration) Resolution Report

**Branch:** stable_4
**Base HEAD:** 17601ff (all migration tracks merged)

## Status

**DONE.** All legacy `app.*` imports in `quant/` resolved to `quant/` targets.

## Commit

- **Hash:** `bd04f4b`
- **Message:** `refactor(quant): resolve cross-track migration TODOs after parallel merge`
- **Scope:** 7 files, +9/-14
- `.superpowers/`, `docs/superpowers/plans/`, `docs/*.md` were NOT committed.

## Changes

| File | Change |
|------|--------|
| `quant/amt/analyzer.py:30` | `from quant.amt.models.observation import AMTObservation` |
| `quant/probability/agent_pipeline.py:61-62` | `from quant.decision.gates.three_align import three_align_check`; `from quant.decision.gates.gate_runner import run_gate_pipeline` |
| `quant/contracts/trading_context.py:24-25` | `from quant.amt.session.context import SessionInfo`; `from quant.probability.agent_pipeline import AgentDecision` |
| `quant/contracts/ports/exchange_strategy.py:21` | `from quant.amt.session.symbol_registry import SymbolRegistry` |
| `quant/inference/rl/valentini_env.py:23` | `from quant.amt.analyzer import (AMTAnalyzer, AMTConfig, compute_aggression_sigma)` — names preserved; `compute_aggression_sigma` is re-exported by `quant/amt/analyzer.py:78` |
| `quant/decision/gates/gate_runner.py:186` | `from quant.execution.loss_tracker import LossTracker` |
| `quant/inference/prompt_builder.py:21` | Restored `if TYPE_CHECKING: from quant.amt.session.context import SessionInfo` (referenced at line 458 in `build_overseer_prompt` annotation); removed stale comment block |

All `# TODO(migration)` comments removed from the changed lines.

## Verification

### Final grep

```
$ grep -rn "import app\.\|from app\." quant/ --include="*.py"
(no output — exit 1)
```

### Test results

```
tests/quant:        1448 passed, 30 skipped, 0 errors
backend/tests/unit: 1324 passed, 60 skipped, 4 errors
```

The 4 errors are the known pre-existing environment failures (missing `gymnasium` for `test_valentini_rl.py`, missing `httpx` for 3 `TestDebugMemoryEndpoint` tests in `test_optimizations.py`). Both modules are absent from the `amt_313` env; confirmed independent of these changes. No new failures introduced.

## Concerns

- `quant/contracts/ports/exchange_strategy.py:20` still carries the stale comment `# Lazy — only used in annotations. Resolves when symbol_registry moves (Phase 3).` It is not a `# TODO(migration)` comment and was left untouched per the "only import changes" rule; it could be cleaned up later.
- `compute_aggression_sigma` is imported via re-export from `quant/amt/analyzer.py` (which itself imports it from `quant/amt/orderflow/aggressive_prints.py`). Works, but a future pass could point directly at the canonical module.
