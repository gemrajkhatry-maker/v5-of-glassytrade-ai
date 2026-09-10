# Decision Pipeline Fixes — Design Spec

> Date: 2026-09-10 | Source: `docs/decision_pipeline_deep_review.md` (4 bugs + 8 structural findings, all code-verified)
> Scope answer: Everything (all 12 items) | STRUCT-5 approach: enforce canonical gates

## Goal

Fix all verified decision-pipeline defects in `quant/decision/`, `quant/strategies/timesfm_strategy.py`,
and `quant/execution/` wiring, in three independently shippable waves. End state: one entry
authority (`DecisionService` + canonical `GatePipeline`), one real exit path (`ExitEngine` →
`TimesFMRiskAuthority`), advisory/model paths clearly labeled, no dead gates, no synthetic data
masquerading as model output.

## Wave 1 — P1 correctness (ship first, stop-safe)

1. **BUG-2** (`quant/decision/context_builder.py:385`): assign `MarketState.DEAD` enum instead of
   plain `"DEAD"` string, so `DecisionService`'s `ctx.market_state == MarketState.DEAD` check fires
   and VA-fade cannot trigger in dead markets.
2. **BUG-1** (`quant/decision/timesfm_agents.py:125,143`): substring match on absorption side
   (`"BUY" in absorption` / `"SELL" in absorption`) so both bare and `_ABSORBED` DTO forms fire
   scanner Setups A/B.
3. **STRUCT-3**: lower `DecisionService` conviction threshold `0.9 → 0.65` so the
   `DATA_QUALITY_BLOCKED` gate is reachable with the pinned 0.7 deterministic conviction;
   update stale "0.55 threshold" comments in `context_builder.py:22-25` and `runtime.py:109-112`.
4. **STRUCT-8** (`quant/strategies/timesfm_strategy.py:333`): inference failure returns `None`
   (existing `MODEL_UNAVAILABLE` path, no `_latest_forecasts` write) instead of a synthetic flat
   forecast that poisons the `ExitEngine` cache.
5. **STRUCT-2**: add exit-source field to close logging (`PositionAgent` advisory vs
   `ExitEngine`/`TimesFMRiskAuthority` real) + operator runbook note documenting the gap.

Acceptance: dead DTO → NO_EDGE; full-form absorption DTO fires scanner setups; inferred-quality
DTO blocks entry while exact/distributed passes; forced inference exception leaves forecast cache
empty; every close event carries an exit source.

## Wave 2 — P2 architecture (single authority)

6. **STRUCT-5**: `TimesFMTradingStrategy.should_enter()` becomes candidate-generator +
   canonical-gate enforcement: after `ScanningAgent` produces a candidate, run it through
   `GatePipeline`/`DecisionService.evaluate()`. Approval requires both. No gate-semantics changes.
7. **STRUCT-4**: scanner `gateResults` output carries the canonical `GateResult`s from step 6
   instead of shadow booleans; UI lights always agree with the real decision.

Acceptance: E2E entry blocked by opposing stacked imbalance while scanner internals stay green;
dashboard gate payload equals `DecisionService` gate results for the same context.

## Wave 3 — P3/P4 cleanup

8. **BUG-3**: `equity=100000.0` → `equity=ctx.equity` (`timesfm_agents.py:315`).
9. **STRUCT-6**: `is_option_contract()` guard in scanner; SHORT on options → FLAT in advisory.
10. **STRUCT-7**: wire `record_forecast_outcome` into close path + read
    `get_session_budget_multiplier` in sizing; delete both if wiring proves invasive (bias: wire).
11. **STRUCT-1**: delete `TradeIntent`/`FixedRiskSizer` dead scaffolding (default); keep only if
    Wave 2 reveals a use.
12. **BUG-4**: remove phantom `allow_entry` (`timesfm_agents.py:102`).
13. **Forecast-cache freshness**: stamp forecast age on the `ExitEngine` path; stale (>1 bar)
    forecasts warn and fall back to deterministic exits.

## Testing strategy

- Existing suites (`tests/quant/decision/`, gate tests) green after every wave.
- New unit tests: BUG-1 (both DTO forms), BUG-2 (dead DTO → NO_EDGE), STRUCT-3 (quality
  gating matrix), STRUCT-8 (exception → empty cache + `MODEL_UNAVAILABLE`).
- Wave 2: E2E-vs-canonical divergence test; gate-payload equality test.
- Pre-merge: full suite + one paper-session replay asserting exit-source on every close.

## Non-goals

- No gate-threshold retuning (CVD ±0.5/±1.0/±2.5 map stays as-is).
- No RL-checkpoint or LLM-model wiring (confirmed unused; out of scope).
- No probability-model inference wiring (schema exists; separate project).
