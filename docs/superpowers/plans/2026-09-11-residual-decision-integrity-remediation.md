# Residual Decision-Integrity Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Finish the residual decision-integrity work left after the 2026-09-10 remediation: make D-5 pyramids genuinely reachable when market data supports them, make D-16 trailing-stop state single-authority across partial fills and replay, and close the remaining observability, sizing, dead-path and hygiene residuals without weakening the release gate.

**Current baseline:** branch `feat/timesfm-paper-e2e-validation`, commit `fb1e4556`.
The prior program closed the blocking gate: `pre_release_decision_check.py --skip-suites` = 16 passed / 0 failed. Broad per-directory verification = 1394 passed / 0 failed / 4 skipped.

## Design decisions

### D5: LVN producer must be fixed at the data boundary, not by loosening the entry gate

Current evidence: `detect_displacement_leg()` builds a leg profile from recent directional candles, then `create_profile(..., buckets=DELTA_PROFILE_BUCKETS)` and `find_lvns()`. In practice, `leg_lvns` is empty ~95% of sampled windows because 1m candle volume concentrates into 1-3 buckets while LVN detection requires a profile with at least three meaningful buckets and local troughs. The current `check_pyramid` gate also requires the selected LVN to be within `2 * tick`, which is too strict for a sparse proxy profile.

Decision:

1. Preserve the strict "price must retest a real LVN" safety invariant. Do NOT make pyramids fire merely because a leg profile exists.
2. Produce a stable, multi-resolution leg profile from finer-grained input when available. Prefer tick/footprint volume buckets; fall back to candle-derived buckets only when tick data is unavailable. The producer must expose provenance and bucket count.
3. Make LVN detection return a typed result with `available`, `provenance`, `bucket_count`, and `levels`. Empty LVNs remain a truthful `NO_LVN` state, not a fabricated level.
4. Replace the fixed `2 * tick` proximity with a named, instrument-aware retest tolerance derived from the profile bucket width and exchange tick size, bounded by a maximum fraction of the leg range. The tolerance must be measured and tested, not guessed.
5. Extract `_nearest_leg_lvn` and `_resolve_leg_lvn` into one pure helper used by both `DecisionContextBuilder` and `PositionManager`.
6. Add journal replay metrics before and after: non-empty LVN rate, bucket count distribution, candidate retest rate, approved pyramid rate, and false-positive guard cases. The release gate must fail if the producer emits levels without provenance or if a level cannot be traced to a profile bucket.

### D16: one protective-stop state owner

Current evidence: `ExitEngine._trail`, `TimesFMRiskAuthority._trail_stops`, the order signal's submitted `sl`, and folded `StopMoved`/`PositionReduced` state all represent overlapping stop state. Task 7 fixed plain `StopMoved` folding and Task 7's follow-up fixed partial-fill reversion, but the two runtime stores remain.

Decision:

1. Introduce a single `ProtectiveStopState` value object keyed by position id, containing `submitted_sl`, `breakeven_floor`, `trail_stop`, `authority`, and `updated_at_bar`.
2. `ExitEngine` owns the state and is the only writer. `TimesFMRiskAuthority` becomes a pure calculator returning a candidate and reason; it no longer maintains `_trail_stops` or `_is_risk_free` state.
3. Deterministic trailing returns a candidate; `ProtectiveStopState.tighten()` applies one monotonic rule. No second write-site clamp and no second private dictionary.
4. `StopMoved` gains `position_id` and `stop_kind` (`BREAKEVEN`, `TRAIL`, `PYRAMID_BASE`) so the event fold can update exactly the position it describes. A base stop move must never tighten pyramid legs by guesswork.
5. `PositionReduced` preserves the folded protective stop for the surviving id, including LONG/SHORT monotonic semantics. Add lifecycle tests for ratchet → TP1 partial → display and replay.
6. The portfolio/WS payload reads only the folded `ProtectiveStopState`; it must never re-derive the displayed stop from `signal.sl` after a ratchet.
7. Add a migration/replay compatibility rule: old `StopMoved` events without `position_id` are accepted as base-position events during replay and are marked legacy in diagnostics.

### Remaining residuals

- **D-16 tie-break:** unify bar/tick protective-stop resolution through the same pure helper.
- **Forecast provider:** add a real `TimesFM_NATIVE=false` contract test, or formally deprecate the remote path after checking deployment config.
- **Sizing observability:** expose model-sizing failure count and reason in `/v1/metrics`, WS risk state, and session journals; add log-once throttling per symbol/session.
- **D-5 observability:** expose LVN provenance, bucket count and unavailable reason in AMT DTO and gate payload.
- **Dead paths:** remove or explicitly quarantine unused coupled option-underlying translation and `sizeFraction`/unused dynamic-sizing fields only after confirming frontend/API consumers.
- **Hygiene:** keep `runtime_audit/e2e` tracked because a tracked test imports `boot_helper`; keep generated graphify/throwaway trees untracked; add a fresh-clone check for all tracked test imports.
- **Tests:** pin all SessionRisk calendar inputs; add a test collection policy that prevents `day_of_week` wall-clock dependence.

## Global constraints

- No live entry, exit, or sizing behavior may be loosened without a replay metric and a negative guard test.
- No task may introduce a second authority for entry, exit, sizing, market state, or provenance.
- Every changed event/schema requires replay compatibility tests and a frontend/WS contract check.
- Do not touch the user's pre-existing `brokers/broker/dhan/infrastructure/symbol_mapper.py` modification.
- Run changed-domain suites after each task; run the release gate after each wave.
- Use isolated worktrees for independent lanes. Merge only after each lane has its own tests and a combined verification passes.

---

## Wave R1 — D5 producer and provenance

### Task R1.1: Extract one LVN resolution helper

**Files:**
- Create: `quant/amt/profile/leg_lvn.py`
- Modify: `quant/decision/context_builder.py`, `quant/position_manager.py`
- Test: `tests/quant/amt/profile/test_leg_lvn.py`

- [ ] Write tests for plural DTO, legacy singular fallback, empty input, non-numeric input, nearest selection, and provenance.
- [ ] Run tests red against the duplicated implementations.
- [ ] Implement pure `resolve_leg_lvn(amt_dto, close_px) -> LegLVNResolution`.
- [ ] Replace both call sites and delete duplicated selection logic.
- [ ] Run `tests/quant/amt/profile/ tests/quant/decision/test_context_builder_behavior.py tests/quant/execution/test_pyramid_integration.py`.
- [ ] Commit `refactor: centralize leg-LVN resolution`.

### Task R1.2: Add profile provenance and bucket diagnostics

**Files:**
- Modify: `quant/amt/profile/displacement.py`, `quant/contracts/value_objects.py`, `quant/amt/dto.py`, `quant/amt_engine.py`
- Test: `tests/quant/amt/profile/test_displacement.py`, `tests/quant/test_amt_engine.py`

- [ ] Add typed metadata: `leg_profile_source`, `leg_bucket_count`, `leg_lvn_available`, `leg_lvn_unavailable_reason`.
- [ ] Preserve old DTO keys while adding camelCase diagnostics.
- [ ] Assert no LVN level is emitted without an originating profile bucket.
- [ ] Run AMT tests and a small journal fixture measurement.
- [ ] Commit `feat: expose leg-LVN provenance and availability diagnostics`.

### Task R1.3: Improve leg-profile resolution without loosening safety

**Files:**
- Modify: `quant/amt/profile/displacement.py`, `quant/amt/profile/volume_profile.py`, `quant/amt_engine.py`
- Test: `tests/quant/amt/profile/test_displacement.py`, `tests/quant/certification/` fixture test

- [ ] Add a finer-resolution profile input path using footprint/tick buckets when available.
- [ ] Keep candle fallback explicitly marked `CANDLE_DISTRIBUTED` or `CANDLE_GAUSSIAN`.
- [ ] Compare non-empty LVN rate on a fixed replay corpus before/after.
- [ ] Reject output when the profile has insufficient buckets instead of synthesizing a level.
- [ ] Commit `feat: improve leg-LVN producer resolution`.

### Task R1.4: Make retest tolerance named, instrument-aware, and measurable

**Files:**
- Modify: `quant/position_manager.py`, `quant/contracts/constants.py`, `quant/contracts/instrument_registry.py`
- Test: `tests/quant/execution/test_pyramid_integration.py`, `tests/quant/decision/test_pyramid_retest_tolerance.py`

- [ ] Define `leg_lvn_retest_tolerance(price, tick_size, profile_bucket_width, leg_range)`.
- [ ] Test NSE, MCX, options and futures scales, including too-wide rejection.
- [ ] Replace the literal `2.0 * tick` only with the named helper.
- [ ] Run replay acceptance metrics: candidate retest count, accepted pyramid count, and negative cases.
- [ ] Commit `fix: use bounded instrument-aware LVN retest tolerance`.

### Task R1.5: D5 acceptance gate

- [ ] Add a machine-readable producer gate requiring provenance and bucket diagnostics.
- [ ] Add a replay report comparing LVN availability before/after.
- [ ] Require no pyramid approval when provenance is unavailable.
- [ ] Run `scripts/pre_release_decision_check.py --skip-suites` and AMT/pyramid suites.
- [ ] Commit `test: gate pyramid entries on traceable LVN evidence`.

---

## Wave R2 — D16 single stop authority

### Task R2.1: Add `ProtectiveStopState`

**Files:**
- Create: `quant/execution/protective_stop.py`
- Test: `tests/quant/execution/test_protective_stop.py`

- [ ] Test LONG/SHORT monotonic tighten, BE floor, trail candidate, invalid values, and tie-break.
- [ ] Implement immutable state + pure `tighten()` transition.
- [ ] Commit `feat: add single protective-stop state value object`.

### Task R2.2: Make `TimesFMRiskAuthority` stateless

**Files:**
- Modify: `quant/decision/timesfm_risk.py`, `quant/execution/exits.py`
- Test: `tests/quant/decision/test_timesfm_risk.py`, `tests/quant/execution/test_exits_trailing.py`

- [ ] Remove `_trail_stops` and `_is_risk_free` mutable stores.
- [ ] Return candidate stop/action from the authority using the supplied active state.
- [ ] Make `ExitEngine` apply all tightening through `ProtectiveStopState`.
- [ ] Run risk/exit suites and confirm no change to stop reasons.
- [ ] Commit `refactor: make TimesFM risk calculation stateless`.

### Task R2.3: Add position identity to stop events

**Files:**
- Modify: `quant/events.py`, `quant/position_manager.py`, `quant/transitions.py`, `quant/event_store.py`
- Test: `tests/quant/test_state_machine.py`, `tests/quant/test_replay_journal.py`, `tests/quant/execution/test_exit_source.py`

- [ ] Add `position_id` and `stop_kind` with backward-compatible defaults.
- [ ] Emit base/pyramid identity explicitly at every stop-move site.
- [ ] Fold only the identified position; old events default to base and emit a legacy diagnostic.
- [ ] Test base-only, pyramid-only, replay ordering, and duplicate events.
- [ ] Commit `fix: make StopMoved position-specific and replay-compatible`.

### Task R2.4: Preserve stop state through partial fills

**Files:**
- Modify: `quant/transitions.py`, `quant/execution/oms.py`, `quant/position_manager.py`
- Test: `tests/quant/test_partial_fold_reconcile.py`, `tests/quant/execution/test_position_management_flow.py`

- [ ] Test LONG/SHORT ratchet → TP1 → displayed stop and pyramid partials.
- [ ] Ensure `PositionReduced` merges the folded stop monotonically.
- [ ] Ensure OMS/order serialization carries the effective stop when required.
- [ ] Commit `fix: preserve protective stop state through partial fills`.

### Task R2.5: Unify bar/tick resolver and display contract

- [ ] Route bar and tick breach decisions through one pure resolver.
- [ ] Pin protective-vs-TP precedence and gap convention.
- [ ] Assert WS snapshot shows the effective folded stop after ratchet, partial, replay, and restart.
- [ ] Run execution/runtime/replay/WS suites.
- [ ] Commit `refactor: unify bar and tick protective-stop resolution`.

---

## Wave R3 — Remaining residuals and hardening

### Task R3.1: Model-sizing observability lifecycle

- [ ] Add log-once/session throttling for repeated model-sizing failures.
- [ ] Include failure reason/counter in journal, `/v1/metrics`, WS risk state, and readiness.
- [ ] Test real failure, MagicMock failure, reset-on-session, and recovery.
- [ ] Commit `fix: expose and throttle model-sizing failures`.

### Task R3.2: Remote TimesFM path decision

- [ ] Add `use_native_engine=False` contract coverage for `TimesFMClient`, buffer, and advisor.
- [ ] Verify `TIMESFM_NATIVE=false` startup path with a stub service.
- [ ] If the remote path is intentionally retired, write an ADR and remove it safely instead.
- [ ] Commit either `test: cover remote TimesFM advisor path` or `chore: retire remote TimesFM path`.

### Task R3.3: Remove/route dead UI and coupled-path fields

- [ ] Trace `dynamicSizing`, `sizeFraction`, `dynamicTrailStop`, coupled option-underlying fields through WS/frontend consumers.
- [ ] Delete fields with zero consumers or add explicit `advisoryOnly`/`source` metadata where they are intentionally displayed.
- [ ] Do not remove a field without frontend/API contract tests.
- [ ] Commit `refactor: remove dead decision payload fields`.

### Task R3.4: Fresh-clone and provenance gate

- [ ] Add a test that every tracked test import path exists in a fresh materialized clone.
- [ ] Keep `runtime_audit/e2e` tracked because `tests/e2e/test_cross_process_injection.py` imports it.
- [ ] Decide the never-tracked frontend `runtime_audit/fixtures/ws_payloads.json` dependency explicitly.
- [ ] Commit `test: enforce fresh-clone test dependency closure`.

### Task R3.5: Final residual acceptance

- [ ] Run per-directory suites separately to avoid OpenMP contention.
- [ ] Run `make parity` and the full release gate.
- [ ] Generate a residual metrics report: LVN availability, pyramid approvals, stop-state transitions, model-sizing failures, remote advisor path, dead payload fields.
- [ ] Update `docs/PRE_RELEASE_READINESS_CHECKLIST.md` and `docs/reviews/2026-09-10-pre-release-code-audit.md`.
- [ ] Commit `docs: close residual decision-integrity remediation`.

## Safety and acceptance criteria

- D5 is not complete when the key is merely read. It is complete when the producer emits traceable LVNs at a measured, useful rate without increasing untraceable pyramid approvals.
- D16 is not complete when plain `StopMoved` folds. It is complete when one protective-stop state survives bar exits, tick exits, partial fills, pyramids, event replay, restart projection, and WS display.
- Every residual task must include a negative test, a positive test, and a representative replay or lifecycle test.
- Keep all existing unrelated working-tree changes untouched.
