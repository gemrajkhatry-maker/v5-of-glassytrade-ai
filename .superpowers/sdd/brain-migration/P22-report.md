# Phase 2 Track P2.2 — Handlers brain-import migration

## Status: COMPLETE

## Commit
- `1166aac` — `refactor(backend): handlers import brain from quant.*` (branch `migration/P22`, worktree `/Users/apple/Documents/wt-gt-P22`)

## Files changed (8)
| File | Swap summary |
|---|---|
| `backend/app/application/handlers/amt_handler.py` | `amt_analyzer`→`quant.amt.analyzer`; `footprint_analyzer`→`quant.amt.orderflow.footprint`; `trading.models.value_objects`→`quant.contracts.value_objects` (TYPE_CHECKING); `shared.timezones`→`quant.contracts.timezones` |
| `backend/app/application/handlers/llm_entry_handler.py` | `trading.models.enums`→`quant.contracts.enums`; `entities`→`quant.contracts.entities`; `regime_detector`→`quant.amt.market.regime`; `exit_engine`→`quant.execution.exit_engine` (top + lazy); `session_context`→`quant.amt.session.context`; `entry_gates.signal_builder`→`quant.decision.gates.signal_builder`; `entry_gates.three_align`→`quant.decision.gates.three_align`; `position_sizer`→`quant.decision.sizer`; `value_objects`→`quant.contracts.value_objects` (TYPE_CHECKING); `generative_ai_service`→`quant.inference.generative_ai` (TYPE_CHECKING); `ports.storage`→`quant.contracts.ports.storage` (TYPE_CHECKING); `entry_gates.confirmation_bundle`→`quant.decision.gates.confirmation_bundle` (lazy) |
| `backend/app/application/handlers/llm_overseer_handler.py` | `exit_engine`→`quant.execution.exit_engine`; `prompt_builder`→`quant.inference.prompt_builder`; `value_objects`→`quant.contracts.value_objects` (TYPE_CHECKING); `generative_ai_service`→`quant.inference.generative_ai` (TYPE_CHECKING); `ports.storage`→`quant.contracts.ports.storage`; `ports.probability_inference`→`quant.contracts.ports.probability_inference`; `probability.features`→`quant.probability.features` (lazy) |
| `backend/app/application/handlers/trade_lifecycle_handler.py` | `exit_engine`→`quant.execution.exit_engine`; `partition_exit_manager`→`quant.execution.partition`; `enums`→`quant.contracts.enums`; `aggregates`→`quant.contracts.aggregates` (TYPE_CHECKING); `entities`→`quant.contracts.entities` (TYPE_CHECKING); `value_objects`→`quant.contracts.value_objects` (TYPE_CHECKING) |
| `backend/app/application/handlers/pre_candle_advisor.py` | `prompt_builder`→`quant.inference.prompt_builder`; `value_objects`→`quant.contracts.value_objects` (TYPE_CHECKING); `generative_ai_service`→`quant.inference.generative_ai` (TYPE_CHECKING) |
| `backend/app/application/handlers/post_trade_analyst.py` | `generative_ai_service`→`quant.inference.generative_ai` (TYPE_CHECKING); `ports.storage`→`quant.contracts.ports.storage` (TYPE_CHECKING) |
| `backend/app/application/handlers/rl_handler.py` | `fabio_ai.rl.trainer`→`quant.inference.rl.trainer` (try/except guarded) |
| `backend/app/application/handlers/entry_gate_coordinator.py` | `entry_gates.{three_align,confirmation_bundle,gate_runner}`→`quant.decision.gates.{...}`; `constants`→`quant.contracts.constants`; `value_objects`→`quant.contracts.value_objects` (TYPE_CHECKING) |

No logic changes — import-path swaps only (41 insertions / 41 deletions across 8 files).

## Test counts
- Backend (`backend/tests/unit`, `--continue-on-collection-errors`): **1324 passed, 60 skipped, 4 errors**
  - The 4 errors are the pre-existing env failures: `tests/unit/domain/test_valentini_rl.py` (gymnasium/stable_baselines3 missing) + 3 `httpx` setup errors in `tests/unit/test_optimizations.py`. No new failures.
- Quant (`tests/quant`): **1448 passed, 30 skipped, 0 errors** (1 unrelated RuntimeWarning in `test_sync_boundary.py`).

## `# TODO(p2)` fallbacks
- **None.** All target symbols exist in the canonical `quant.*` modules and were verified importable.
- **No circular-import fallbacks:** `grep` of `quant/` for `from app.` / `import app.` returns nothing — quant never imports backend modules, so swapping handler imports to quant directly introduces no cycle (shims already loaded the same quant modules).

## Concerns
- `rl_handler.py` keeps its `try/except ImportError` guard; the RL dependency (`stable_baselines3`) is still not installed, so `_RL_AVAILABLE` remains `False` — same as pre-migration behavior, unaffected by the path swap.
- Shims in `backend/app/domain/...` left untouched for Phase 3 deletion as instructed.
- `IncrementalVolumeProfile` and `ExitReason`/`ExitSignal` are re-exported through their quant module namespaces (`quant.amt.analyzer`, `quant.execution.exit_engine`) — verified importable directly.
