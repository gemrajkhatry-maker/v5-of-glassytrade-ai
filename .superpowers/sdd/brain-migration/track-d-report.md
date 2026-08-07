# Track D Report — Execution & risk cluster → `quant/execution/`

**Date:** 2026-08-06
**Worktree:** `/Users/apple/Documents/wt-gt-track-D` (branch `migration/track-D`)
**Status:** COMPLETE — all 14 modules moved, shims left at legacy paths, tests ported, parity suite green.

## Commits (newest → oldest)

| Commit | Module |
|---|---|
| `679d435` | exit_engine → `quant/execution/exit_engine.py` |
| `b2e9d9b` | trade_costs → `quant/execution/trade_costs.py` |
| `4c7e823` | risk_tier_engine → `quant/execution/risk_tier.py` |
| `7bd5b63` | risk_sizing_engine → `quant/execution/risk_sizing.py` |
| `9b590a2` | circuit_breakers → `quant/execution/circuit_breakers.py` |
| `e3b58bf` | signal_validator → `quant/execution/signal_validator.py` |
| `5b23424` | risk_manager → `quant/execution/risk_manager.py` |
| `9fb429d` | kill_switch → `quant/execution/kill_switch.py` |
| `3601da1` | session_risk_manager → `quant/execution/session_risk_manager.py` |
| `1d27ce5` | loss_tracker → `quant/execution/loss_tracker.py` |
| `b2a51ae` | partition_exit_manager → `quant/execution/partition.py` |
| `96357a7` | pyramid_manager → `quant/execution/pyramid.py` |
| `e032ee8` | scale_manager → `quant/execution/scale.py` |
| `2e74a1a` | trail_engine → `quant/execution/trail.py` |

All messages: `refactor(quant): move <module> from backend brain`. `exit_signal.py` / `exit_rules.py` were already in `quant/execution/` (Task 0.2) and used as imports — not re-moved. `git mv` used throughout (no content drift).

## Test summary

- `tests/quant`: **1085 passed, 5 skipped** (up from 825 baseline; +302 in `tests/quant/execution/`).
- `backend/tests/unit`: **1406 passed, 60 skipped, 4 errors** — the 4 errors are the **pre-existing env errors** (1 collection error `test_valentini_rl.py` missing `gymnasium`; 3 errors in `test_optimizations.py` missing `httpx`), unchanged from baseline.
- Ported tests now live in `tests/quant/execution/`:
  `test_trail.py`, `test_scale.py`, `test_pyramid.py`, `test_pyramid_integration.py`, `test_partition.py`, `test_loss_tracker.py` (new — no legacy dedicated test existed), `test_session_risk_manager.py`, `test_kill_switch.py` (new), `test_risk_manager.py`, `test_risk_manager_enhanced.py`, `test_signal_validator.py`, `test_signal_validator_extended.py`, `test_circuit_breakers.py`, `test_risk_sizing.py`, `test_risk_tier.py` (RiskTierEngine portion extracted from `test_observability.py`; tracker tests stayed in backend), `test_trade_costs.py` (new), `test_trade_manager.py`, `test_exit_engine_pyramid.py`.
- Parity tests: **21 passed** in `tests/quant/execution/test_parity.py` via `assert_parity` covering: TrailEngine (ATR/VWAP/imbalance/CVD-BE/adjust-SL), ExitEngine.check_position (stop-loss + hold/MAE), LossTracker (`is_daily_limit_reached`, `compute_dynamic_risk`), RiskManager (`validate`, `record_trade_result`), CircuitBreakers.evaluate, RiskSizingEngine.calculate, TradeCosts.compute_trade_costs, SignalValidator.validate_all, plus scale, pyramid, partition, session_risk_manager, kill_switch, risk_tier.

## Parity notes / Position-field observations

- `Position`/`Signal`/`Portfolio` all built from `quant.contracts.*`. `quant.contracts.entities.Position` already carries all lifecycle fields needed (`peak_profit`, `mae/mfe`, `tick_count`, `scale_step/scale_confirm_price/scale_breakout_price`, `partial_taken`, `atr_trail_active`, `breakeven_set`, `cushion_state`, `advance_cushion_state`, …) — no field gaps.
- `quant.contracts.entities` imports `quant.execution.exit_rules`; `exit_rules` imports `quant.contracts.enums/constants` + `quant.execution.exit_signal` — no circular import introduced by the moves (verified by clean import of all modules + full suite).
- `Portfolio.create_default()` (equity/balance as `Decimal`) is compatible with `RiskManager.validate`/`record_trade_result` (uses `float(portfolio.equity)`, `has_open_position_for_source`, `p.is_open/size/entry_price/symbol`).
- `test_risk_manager_enhanced.py` patch target updated from `app.domain.trading.services.risk_manager.datetime` → `quant.execution.risk_manager.datetime` (test-visible behavior; the shim would keep the old path working for non-patched imports).
- LossTracker: `app.core.async_boundary` → `quant.contracts.sync_boundary` (sanctioned rewrite); `ports.storage` → `quant.contracts.ports.storage`; IST via `quant.contracts.timezones`.

## Zero-backend-import rule

`grep -rn "import app\.|from app\." quant/` → only pre-existing: `quant/amt/profile/factory.py:17` (Track-A5 `amt_analyzer` TODO, allowed) and `quant/contracts/*` TYPE_CHECKING TODO(migration) imports. **Nothing new; `quant/execution/*` has zero `app.*` imports.**

## Concerns

1. **Stale `session_risk_coordinator` reference** — the brief lists `session_risk_coordinator.py` as a consumer, but no such source file exists in this worktree (only a stale `.pyc`). The real consumers (`trading_session.py`, `entry_coordinator.py`, `session_event_router.py`, `exit_coordinator.py`, handlers) all import via shims and were exercised by `backend/tests/unit` (1406 passed).
2. **`test_dynamic_risk_sizing.py` left in backend** — it imports `gate_runner.calculate_position_size` (Track B module) and transitively LossTracker; left as-is per Track-B ownership. The loss_tracker coverage in `tests/quant` is via the new `test_loss_tracker.py` + parity.
3. **No dedicated legacy tests existed** for `loss_tracker`, `kill_switch`, `trade_costs` — replaced with new direct tests + parity instead of a port.
4. **`test_observability.py` split** — RiskTierEngine tests extracted to `tests/quant/execution/test_risk_tier.py`; GateRejectionTracker/LatencyTracker tests remain in backend (untouched modules).
5. **Phase 2.7 reconciliation** — greenfield `quant/execution/{exits,risk,oms,order}.py` untouched and coexisting with moved production brain; deferred as specified.
