# Phase 1 Track B — Decision & gates cluster → `quant/decision/`

**Worktree:** `/Users/apple/Documents/wt-gt-track-B` (branch `migration/track-B`). Do ALL work inside this worktree. Commit there. Do NOT touch `/Users/apple/Documents/v5-of-glassytrade-ai`.

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track B.

**ALREADY DONE on the base branch (do NOT re-move; they are in your worktree):**
- `position_sizer.py` → `quant/decision/sizer.py` (commit a1ed714)
- `signal_coordinator.py` → `quant/decision/signal_coordinator.py` (commit bd2ef3c)
- `trade_thesis.py` → `quant/decision/trade_thesis.py` (commit f29d646)
Only the REMAINING modules below need moving. `run_gate_pipeline`/`calculate_position_size` and the entry-gate modules are still in the backend.

**Goal:** Port the backend entry-gate/decision cluster into `quant/decision/`, extending the existing greenfield decision package. Same move-with-shim + parity recipe. One commit per module; every commit leaves quant + backend suites green.

**IMPORTANT naming collision:** the existing greenfield `quant/decision/signal_builder.py` (5-gate SignalBuilder) is DIFFERENT from the backend `entry_gates/signal_builder.py` (`build_entry_signal`). Keep them separate. The moved entry-gate modules go under `quant/decision/gates/` (create `quant/decision/gates/__init__.py`, empty). Do NOT merge the two signal builders.

**Modules to move:**

1. `backend/app/domain/fabio_ai/services/gate_pipeline.py` → `quant/decision/gates/legacy_gate_pipeline.py`
   - Exports: `GateType`, `GateReason`, `GateContext`, `GateResult`, `GatePipeline`. Imports `eia_calendar.EIACalendar` → `quant.amt.session.eia.EIACalendar` (moved in Track A4).
2. `backend/app/domain/fabio_ai/services/entry_gates/confirmation_bundle.py` → `quant/decision/gates/confirmation_bundle.py`
   - Exports: `check_confirmation_bundle`, `check_momentum_fade`, `compute_atr`. Imports `candle_metrics.body` → `quant.contracts.candle_metrics.body`.
3. `backend/app/domain/fabio_ai/services/entry_gates/grading.py` → `quant/decision/gates/grading.py`
   - Exports: `check_vwap_bias`, `check_imbalance_alignment`, `compute_grade_score`. Pure.
4. `backend/app/domain/fabio_ai/services/entry_gates/three_align.py` → `quant/decision/gates/three_align.py`
   - Exports: `min_candles_gate`, `full_body_close_gate`, `nearest_round_number`, `cluster_aggressive_prints`, `extract_bubble_levels_from_footprint`, `three_align_check`.
   - Imports: `candle_metrics.body` → `quant.contracts.candle_metrics.body`; `confirmation_bundle.check_confirmation_bundle` → `quant.decision.gates.confirmation_bundle.check_confirmation_bundle`; `fabio_ai.ports.three_align.ThreeAlignInput` → `quant.amt.profile.three_align_input.ThreeAlignInput` (moved Track A1).
5. `backend/app/domain/fabio_ai/services/entry_gates/signal_builder.py` → `quant/decision/gates/signal_builder.py`
   - Exports: `sl_from_aggressive_print`, `build_entry_signal`.
   - Imports: `tick_utils` → `quant.contracts.tick_utils`; `confirmation_bundle.compute_atr` → `quant.decision.gates.confirmation_bundle.compute_atr`; `grading.compute_grade_score` → `quant.decision.gates.grading.compute_grade_score`; `trade_thesis.build_trade_thesis` → `quant.decision.trade_thesis.build_trade_thesis`.
6. `backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py` → `quant/decision/gates/gate_runner.py`
   - Exports: `run_gate_pipeline`, `calculate_position_size`.
   - Its imports are LAZY (inside function bodies): `gate_pipeline` → `quant.decision.gates.legacy_gate_pipeline`; `eia_calendar` → `quant.amt.session.eia`; `position_sizer` → `quant.decision.sizer`; **`loss_tracker` is Track D (NOT moved yet) — keep the lazy import `from app.domain.fabio_ai.services.loss_tracker import LossTracker` with `# TODO(migration): switch to quant.execution.loss_tracker once Track D lands`.**
7. `backend/app/domain/fabio_ai/services/position_sizer.py` → `quant/decision/sizer.py`
   - Exports: `PositionSize`, `PositionSizer`. Pure.
8. `backend/app/domain/fabio_ai/services/signal_coordinator.py` → `quant/decision/signal_coordinator.py`
   - Exports: `EntryEvaluation`, `SignalCoordinator`. Pure.
9. `backend/app/domain/fabio_ai/services/trade_thesis.py` → `quant/decision/trade_thesis.py`
   - Exports: `TradeThesis`, `infer_location`, `infer_aggression_trigger`, `setup_family_for`, `build_trade_thesis`, `validate_trade_thesis`. Pure.
10. `backend/app/domain/services/scalp_gate_pipeline.py` → `quant/decision/gates/scalp.py`
    - Exports: `ScalpGate`, `ScalpGateResult`, `ScalpContext`, `check_g1_session_timing`…`check_g6_no_double_exposure`, `evaluate_scalp_gates`. Pure.
11. `backend/app/domain/services/short_signal_gates.py` → `quant/decision/gates/short.py`
    - Exports: `ShortGateResult`, `check_s1_direction_allowed`…`check_s5_contract_type`, `evaluate_short_gates`. Pure.

**entry_gates `__init__.py` shim (special):** `backend/app/domain/fabio_ai/services/entry_gates/__init__.py` currently re-exports 16 public symbols. Replace its body with a shim that re-exports the same surface from `quant.decision.gates`:
```python
from quant.decision.gates.confirmation_bundle import *  # noqa: F401,F403
from quant.decision.gates.grading import *  # noqa: F401,F403
from quant.decision.gates.three_align import *  # noqa: F401,F403
from quant.decision.gates.signal_builder import *  # noqa: F401,F403
from quant.decision.gates.gate_runner import *  # noqa: F401,F403
```
Verify every previously-exported name still resolves via the shim (grep the old `__all__` and assert each imports). Leave the same "moved to quant — delete in Phase 3" docstring.

**Other shims** at each legacy path: `from quant.decision.gates.<name> import *  # noqa: F401,F403` (or `from quant.decision.<name> import *` for sizer/signal_coordinator/trade_thesis). The `fabio_ai/services/gate_pipeline.py` shim → `from quant.decision.gates.legacy_gate_pipeline import *`.

**Import-rewrite map:**
- `app.domain.trading.models.*` → `quant.contracts.*`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.services.candle_metrics` / `tick_utils` → `quant.contracts.<same>`
- `app.domain.fabio_ai.services.eia_calendar` → `quant.amt.session.eia`
- `app.domain.fabio_ai.ports.three_align` → `quant.amt.profile.three_align_input`
- `app.domain.fabio_ai.services.entry_gates.<x>` → `quant.decision.gates.<x>`
- `app.domain.fabio_ai.services.gate_pipeline` → `quant.decision.gates.legacy_gate_pipeline`
- `app.domain.fabio_ai.services.{position_sizer,signal_coordinator,trade_thesis}` → `quant.decision.<same>`
- `app.domain.services.{scalp_gate_pipeline,short_signal_gates}` → `quant.decision.gates.{scalp,short}`

**Tests to port** (find under `backend/tests/`; port ALL hits): gate_pipeline, gate_runner, three_align, confirmation_bundle, entry gate signal_builder, grading, position_sizer, signal_coordinator, trade_thesis, scalp_gate_pipeline, short_signal_gates → `tests/quant/decision/` (or `tests/quant/decision/gates/`). Rename the ported entry-gate signal_builder tests to avoid collision with the greenfield signal_builder tests (`test_gates_entry_signal_builder*.py`).

**Parity tests** via `assert_parity` (legacy shim vs moved) on fixed inputs:
- `gate_pipeline.GatePipeline.evaluate`: a populated `GateContext` (fields per the dataclass) for a few scenarios (all-pass, session-fail, RR-fail). NOTE: `GateContext`/`GateResult` are the same class objects via the shim — parity of `evaluate` output is still meaningful for field values.
- `run_gate_pipeline`: a synthetic `(data, amt_result, tick)` triple — build a minimal `AMTResult` via `quant.contracts.value_objects.AMTResult` with the fields `run_gate_pipeline` reads (check which `getattr` fields it uses first; populate them).
- `compute_atr`, `three_align_check` (synthetic OHLC), `sl_from_aggressive_print`, `build_entry_signal` (synthetic tick+AMTResult), `compute_grade_score`.
- `evaluate_scalp_gates`, `evaluate_short_gates`: synthetic contexts.
- `PositionSizer.calculate`, `SignalCoordinator.evaluate_entry`, `build_trade_thesis`/`validate_trade_thesis`.
For functions that need a rich `AMTResult`, construct it with only the accessed fields (read the function body first); assert parity of the returned tuple/dict.

**Verification (after EACH module):**
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
Report pass/skip/error counts; the 4 pre-existing errors (gymnasium + 3 httpx) must be unchanged.

**Zero-backend-import rule:** `grep -rn "import app\.\|from app\." quant/amt quant/decision --include=*.py` → allowed hits: `quant/amt/profile/factory.py` (amt_analyzer TODO, Track A5) AND `quant/decision/gates/gate_runner.py` (loss_tracker TODO, Track D). Nothing else.

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-b-report.md`: commit hashes, the entry_gates `__init__` shim verification, the gate_runner loss_tracker TODO, parity-skips (esp. which AMTResult fields you had to populate), test tails, remaining `# TODO(migration)` imports. Return: status, commits, one-line test summary, concerns.
