# Phase 1 Track D — Execution & risk cluster → `quant/execution/`

**Worktree:** `/Users/apple/Documents/wt-gt-track-D` (branch `migration/track-D`). Do ALL work inside this worktree. Commit there. Do NOT touch `/Users/apple/Documents/v5-of-glassytrade-ai`.

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track D. Recipe: `git mv` → rewrite imports → shim → port tests → parity → suites → commit `refactor(quant): move <module> from backend brain`.

**Modules to move (leaf-first; note exit_signal + exit_rules are ALREADY moved to `quant/execution/` by Task 0.2 — they exist in this worktree, do not re-move them):**

1. `backend/app/domain/fabio_ai/services/trail_engine.py` → `quant/execution/trail.py` (imports `tick_utils` → `quant.contracts.tick_utils`; `exit_signal` → `quant.execution.exit_signal`)
2. `backend/app/domain/fabio_ai/services/scale_manager.py` → `quant/execution/scale.py`
3. `backend/app/domain/fabio_ai/services/pyramid_manager.py` → `quant/execution/pyramid.py`
4. `backend/app/domain/fabio_ai/services/partition_exit_manager.py` → `quant/execution/partition.py`
5. `backend/app/domain/fabio_ai/services/loss_tracker.py` → `quant/execution/loss_tracker.py` (imports `app.core.async_boundary.ensure_sync_adapter_result` → `quant.contracts.sync_boundary.ensure_sync_adapter_result`; `ports.storage` → `quant.contracts.ports.storage`)
6. `backend/app/domain/fabio_ai/services/session_risk_manager.py` → `quant/execution/session_risk_manager.py`
7. `backend/app/domain/trading/services/kill_switch.py` → `quant/execution/kill_switch.py`
8. `backend/app/domain/trading/services/risk_manager.py` → `quant/execution/risk_manager.py` (imports `kill_switch` → `quant.execution.kill_switch`; `entities.Signal`/`aggregates.Portfolio` → `quant.contracts.*`)
9. `backend/app/domain/trading/services/signal_validator.py` → `quant/execution/signal_validator.py`
10. `backend/app/domain/services/circuit_breakers.py` → `quant/execution/circuit_breakers.py`
11. `backend/app/domain/services/risk_sizing_engine.py` → `quant/execution/risk_sizing.py`
12. `backend/app/domain/services/risk_tier_engine.py` → `quant/execution/risk_tier.py`
13. `backend/app/domain/services/trade_costs.py` → `quant/execution/trade_costs.py`
14. `backend/app/domain/fabio_ai/services/exit_engine.py` → `quant/execution/exit_engine.py` (LAST — imports exit_rules, exit_signal, trail, scale, loss_tracker, pyramid — all now `quant.execution.*`). Exports `ExitEngine` (also aliased `TradeManager`), `TradeManagerConfig`, `ExitDecision`.

**IMPORTANT naming collision:** the existing greenfield `quant/execution/exits.py` and `quant/execution/risk.py` are a DIFFERENT lightweight engine used by `QuantEngine` (deterministic runtime). Do NOT merge or delete them; keep both. The moved `ExitEngine`/`RiskManager` are the production brain. A Phase 2.7 task reconciles them later.

**Import-rewrite map:**
- `app.domain.trading.models.*` → `quant.contracts.*`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.ports.<x>` → `quant.contracts.ports.<x>`
- `app.core.async_boundary` → `quant.contracts.sync_boundary`
- `app.domain.fabio_ai.services.exit_signal` → `quant.execution.exit_signal`
- `app.domain.fabio_ai.services.exit_rules` → `quant.execution.exit_rules`
- `app.domain.fabio_ai.services.trail_engine` → `quant.execution.trail`
- `app.domain.fabio_ai.services.scale_manager` → `quant.execution.scale`
- `app.domain.fabio_ai.services.pyramid_manager` → `quant.execution.pyramid`
- `app.domain.fabio_ai.services.partition_exit_manager` → `quant.execution.partition`
- `app.domain.fabio_ai.services.loss_tracker` → `quant.execution.loss_tracker`
- `app.domain.fabio_ai.services.session_risk_manager` → `quant.execution.session_risk_manager`
- `app.domain.trading.services.<x>` → `quant.execution.<x>`
- `app.domain.services.{circuit_breakers,risk_sizing_engine,risk_tier_engine,trade_costs}` → `quant.execution.<same>`
- `app.domain.fabio_ai.services.exit_engine` → `quant.execution.exit_engine`

**Shims** at each legacy path: `from quant.execution.<name> import *  # noqa: F401,F403`. Consumers that must keep working via shims: `trade_lifecycle_handler.py` (ExitEngine, ExitReason, PartitionExitManager), `llm_entry_handler.py`/`llm_overseer_handler.py` (ExitEngine), `session_risk_coordinator.py` (RiskManager, KillSwitch, SessionRiskManager, RiskTierEngine, CircuitBreakers), `entry_coordinator.py` (RiskSizingEngine), `state_snapshot_builder.py` (ExitEngine lazy), `amt_analyzer.py` (loss_tracker? check), `gate_runner.py` (loss_tracker — Track B; keep legacy import in Track B with TODO, your shim makes it work).

**Tests to port** (from `backend/tests/`; port ALL hits): exit_engine, exit_rules (already ported in 0.2 — skip), exit_signal (skip), trail_engine, scale_manager, pyramid_manager, partition_exit_manager, loss_tracker, session_risk_manager, risk_manager, kill_switch, signal_validator, circuit_breakers, risk_sizing_engine, risk_tier_engine, trade_costs → `tests/quant/execution/`.

**Parity tests** via `assert_parity` (legacy shim vs moved) on fixed inputs:
- `TrailEngine` / `ExitEngine.check_position`: a fixed `Position` (from `quant.contracts.entities`) + price/time/cvd.
- `LossTracker`: fixed loss/win sequences → `is_daily_limit_reached`, `compute_dynamic_risk`.
- `RiskManager.validate`: a fixed `Signal` + `Portfolio`; `record_trade_result`.
- `CircuitBreakers.evaluate`: fixed consecutive-loss/pnl tuples.
- `RiskSizingEngine.calculate`: fixed sizing inputs.
- `TradeCosts.compute_trade_costs`: fixed notional/slippage.
- `SignalValidator.validate_all`: fixed signal+tick.

**Verification (after EACH module):**
```bash
cd /Users/apple/Documents/wt-gt-track-D
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
(The worktree has its own `backend/`. 4 pre-existing env errors unchanged.)

**Zero-backend-import rule:** `grep -rn "import app\.\|from app\." quant/ --include=*.py` → allowed: Track-A5 `amt_analyzer` TODO in `quant/amt/profile/factory.py` (already on stable_4). Nothing new. (Track B's gate_runner→loss_tracker legacy import lives in the OTHER worktree; after merge, Track B resolves it.)

**Report:** write to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-d-report.md` (commit hashes, test tails, parity skips, any Position-field issues). Reply: status, commits, one-line test summary, concerns.
