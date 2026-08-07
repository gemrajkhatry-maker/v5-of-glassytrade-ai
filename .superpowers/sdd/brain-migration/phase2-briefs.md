# Phase 2 — Track Briefs (one per parallel worktree)

Work in YOUR worktree only (`cd /Users/apple/Documents/wt-gt-<TRACK>`). Read the recipe first: `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/phase2-recipe.md`. Follow its rules exactly.

## P2.1 — Application services
**Worktree:** `/Users/apple/Documents/wt-gt-P21`. Swap brain imports in these files (under `backend/app/application/services/`):
`amt_service.py`, `analysis_service.py`, `entry_coordinator.py`, `exit_coordinator.py`, `session_event_router.py`, `session_phase_manager.py`, `session_risk_coordinator.py`, `session_state_manager.py`, `phase_manager.py`, `trading_session.py`, `state_snapshot_builder.py`, `startup_contracts.py`, `engine_lifecycle.py`, `experiment_context.py`, `quant_bridge.py`, `quant_signal_mapper.py` (check), `ai_command_service.py`, `trading_query_service.py`.
Note: `session_event_router.py` is large — its `_try_execute_quant_decision` already imports `quant.decision.signal_builder.Signal`; leave that, only swap the `app.domain.*` imports.

## P2.2 — Handlers
**Worktree:** `/Users/apple/Documents/wt-gt-P22`. Swap brain imports in `backend/app/application/handlers/`:
`amt_handler.py`, `llm_entry_handler.py`, `llm_overseer_handler.py`, `trade_lifecycle_handler.py`, `pre_candle_advisor.py`, `post_trade_analyst.py`, `rl_handler.py`, `entry_gate_coordinator.py`.

## P2.3 — Engine & orchestrators
**Worktree:** `/Users/apple/Documents/wt-gt-P23`. Swap brain imports in:
`backend/app/application/engine.py`, `candle_aggregator.py`, `watchdog_manager.py`, `session_orchestrator.py`, `session_runtime_contracts.py`, `trading_query_service.py` (if not in P2.1), `utils.py`.

## P2.4 — API layer
**Worktree:** `/Users/apple/Documents/wt-gt-P24`. Swap brain imports in `backend/app/api/`:
`routers/health.py`, `routers/ai.py`, `routers/analysis.py`, `routers/rl.py`, `routers/metrics.py`, `routers/trading.py`, `routers/market.py`, `routers/observability.py`, `websocket/gameloop.py`, `dependencies.py`.

## P2.5 — Infrastructure adapters
**Worktree:** `/Users/apple/Documents/wt-gt-P25`. Swap brain imports in `backend/app/infrastructure/`:
`adapters/delta_profile_adapter.py`, `adapters/npoc_adapter.py`, `adapters/lgbm_probability_adapter.py`, `adapters/mlx_inference_adapter.py`, `adapters/gguf_inference_adapter.py`, `adapters/paper_broker.py`, `adapters/dhan_adapter.py`, `serialization/schemas.py`, `metrics.py`, `strategies/mcx_strategy.py`, `strategies/nse_strategy.py`.

## P2.6 — DI + config
**Worktree:** `/Users/apple/Documents/wt-gt-P26`. Swap brain imports in:
`backend/app/application/di/composition_root.py`, `backend/app/application/di/container.py`, `backend/app/config_models/settings_adapter.py`, `backend/app/config.py`, `backend/app/main.py`.

## P2.7 — Split-brain unification (quant.core vs quant.amt)
**Worktree:** `/Users/apple/Documents/wt-gt-P27`. This is the analysis-consolidation decision task. Do NOT change production code in this track — produce a WRITTEN analysis + a test-only comparison, and record the decision in `docs/AMT_UNIFICATION.md` (write it in the worktree; do not commit it to stable_4 yet — report the decision):
1. Write `tests/quant/unification/test_auction_vs_amt.py`: feed the same fixed 60-bar synthetic session through BOTH `quant/coordinator.AuctionCoordinator` (quant.core) and `quant/amt/analyzer.AMTAnalyzer`; compare the overlapping outputs (poc, vah, val, vwap value, cvd, delta, ib high/low). Use a fresh instance per side (both are stateful).
2. Report the numeric deltas for each overlapping field (absolute and %).
3. Decide and document: keep `quant.core` as the real-time `auction`-WS producer (already byte-compatible with the frontend contract) AND `quant.amt` as the full-featured decision engine, OR unify. Recommend the default (keep both, document divergence budget) unless the deltas are huge (then recommend investigating).
4. Do NOT delete or edit `quant/core` or `quant/amt` files. This track's deliverable is the comparison test + `docs/AMT_UNIFICATION.md` decision record. Commit only the test file.

**All tracks:** commit per file-group or per track. Do NOT commit `.superpowers/`, `docs/superpowers/plans/`, `docs/*.md` (except P2.7 writes AMT_UNIFICATION.md in the worktree but does not commit it). Reply with: status, commit hashes, test counts, and any `# TODO(p2)` fallbacks.
