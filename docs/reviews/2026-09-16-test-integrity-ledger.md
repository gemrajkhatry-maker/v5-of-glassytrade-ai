# Test Integrity Ledger — `architecture/design-level-refactoring`

**Ledger commit:** `5015ebb1` · **Date:** 2026-09-16 · **Owner workstream:** WS-C
**Canonical baseline:** 36 failed / 781 passed / 2 skipped on the S3-era 819-test subset (`25ea293f`); full `tests/quant` suite is 2192 tests and was **never baselined before this ledger** — see §Dark zone.

## Verdict summary (at `5015ebb1`)

| Class | Count | Notes |
|---|---|---|
| **REAL-REGRESSION** | 1 | incomplete commit `be9609ae` — **FIXED** at `5015ebb1` (`_get_lots`) |
| **STALE-GOLDEN** | 44 | four root-cause groups below; **zero live regressions remain** |
| ENV/ORDER-DEPENDENT | 0 in canon | `test_half_trend_scale_parity` ×3 flakes only in partial-run orderings (§Notes) |
| FLAKY | 0 | failure sets identical across independent runs |

**Headline:** 22 of the original 36 failures + a 13-failure dark zone trace to **one commit** — `be9609ae` (2026-09-11). It (a) added the Gate-3 1-min candle-acceptance guard without updating pre-guard test fixtures, and (b) added 5 `_get_lots` call sites without defining the method — a genuine crash in the live partial-exit/BE-arm path, fixed by `5015ebb1`.

## Full-suite confirmation runs

| Run | Commit | Scope | Result |
|---|---|---|---|
| S3 baseline | `25ea293f` | 819-test subset (+tests/system) | 36F/781P/2S |
| ws-c run1 | `ad0b70c2` | tests/quant (full, 2192) | 56F/2125P/11S — includes `_get_lots` crashes |
| **ws-c run2 (canonical)** | **`5015ebb1`** | **tests/quant (full)** | **44F/2147P/11S** |
| Reconciliation | — | — | 35 baseline stale (−1 fixed exits, −1 lives in tests/system, out of run scope) + 10 dark-zone stale = 44 ✓ |

## Group 1 — Gate-3 candle-acceptance guard vs pre-guard fixtures (21 · STALE-GOLDEN)

Tests' synthetic bars predate the guard `be9609ae` added (`Mid-candle probe rejected: body {x}% of range < 60%`, `Wick probe rejected: close not near the high`, `1-min candle closed {up|down} — no {bullish|bearish} body`). Production is per-spec.

**Owner:** WS-B (its Gate-3 rewrite touches this exact surface — fold fixture repair into that PR).
**Action:** `FIX-FIXTURES` — give bars a ≥60% body in signal direction / close near extreme. Do NOT delete assertions encoding trend-veto or drop-reason semantics (`test_gate1_phase_permissions` midday trio, E5 especially).

Tests: `test_decision_service.py` ×3, `test_gate1_phase_permissions.py` ×3 (midday veto trio), `test_phase3_pipeline.py` ×1, `test_setup_approval_flow.py` ×4, `test_squeeze_pullback.py` ×4, `test_strategy_behavior.py` ×4, `tests/system/test_fabio_behavior_trace.py` ×1, plus `test_signal_drop_reasons.py::test_service_block_reason_includes_builder_drop` (E5 precondition shift: guard rejects at Gate 3 before the `aa7b06fa` SignalBuilder path is reachable with that fixture).

## Group 2 — Sizing-model change vs old tier math (15 · STALE-GOLDEN)

`61aa8156` deliberately reworked sizing (50% deployment, 5% budget); `9f817605` unified constants. Tests pin the old model. Owner: **nobody** — recommend "WS-D: re-pin risk/lot tests to `9f817605` constants" with quant review of each new number (several encode safety semantics: kill-switch reason, deployment ceiling, 0.5% house cap).

Tests: `test_risk.py` ×7 (`test_max_loss_halts` — prod **does** halt, via the new 2% session kill-switch; `test_position_size_risk_based` 1000 vs 250; `test_cushion_tier_progression`; `test_house_money_bonus_capped`; `test_day_of_week_multiplier_monday_defensive` 500 vs 125; notional-ceiling ×2), `test_lot_aware_risk.py` ×7, `runtime/test_runtime.py::test_runtime_leaves_healthy_stop_quantity_unclamped` (250 vs 125, same tier math).

## Group 3 — Event-schema growth vs trace normalization (2 · STALE-GOLDEN)

`d0e82f70`/`0ba31e14` (2026-09-11) added `position_id` to stop events; `test_fast_determinism_parity.py::test_organic_decision_trace_is_identical_across_runs` and `test_hotpath_trace.py::test_trace_on_event_stream_equals_trace_off` (B7 passivity) normalize `correlation_id` but not `position_id`. Action: `FIX-FIXTURES` — add `position_id` to the normalizer (keep it asserted where the B7 test checks passivity structure).

## Group 4 — Stub fixtures vs hardened infra (2 · STALE-GOLDEN)

- `test_eod_square_off.py::test_force_close_position_closes_base_and_pyramids` + `::test_force_close_position_falls_back_to_entry_price_without_bar`: engine built via `QuantEngine.__new__` (no `__init__`); `2d74fe94` made `_emit` depend on `self.event_appender` (defined at `runtime.py:379` in real init). Action: stub `event_appender` in `_make_engine_stub` (or append to a list).

## Dark zone — first-ever full-suite measurement (10 · STALE-GOLDEN)

Discovered by run1: the S3 baseline covered only 819 of 2192 tests. These 10 were failing before WS-A and are **not** attributable to the merge (identical failures reproduced at `25ea293f`):

- `test_market_state_enum_guard.py::test_no_raw_market_state_literals_outside_allowlist` — scanner (`timesfm_advisor/agents/client/engine`, 5+ files) uses raw `"BALANCED"/"IMBALANCED"` literals; guard's allowlist predates the scanner's growth. Action: route through `amt/dto.py` or extend allowlist deliberately.
- `test_no_duplicate_types.py` ×2 — `Bar` re-defined in `quant/bars.py` **and** `quant/contracts/value_objects.py`; layered-pairs ratchet also stale. Action: pick the canonical home (contracts), alias elsewhere, update ratchet.
- `test_certification.py::test_s5_conviction_formula_is_explicit` — asserts `len(gate_results) >= 4` but the default-path service returns 0 gates; consistent with the E2E finding below. Needs WS-B's path decision first.
- `test_fast_determinism_parity.py::test_position_management_trace_is_identical_across_runs` — `position_id` normalization (Group 3).
- `test_stress_and_portfolio_risk.py::test_session_risk_sizes_from_portfolio_equity`, `test_portfolio_risk_guard.py::test_manage_exit_partial…` — sizing-family (Group 2).
- `runtime/` tick-cluster remainder collapsed to green after `5015ebb1` (12 of 13 were the `_get_lots` crash).

## REAL-REGRESSION (1 · RESOLVED)

| Test | Defect | Fix |
|---|---|---|
| `tests/quant/execution/test_exits.py::test_tp1_partial_exit_bar_journals_be_arm` | `quant/position_manager.py` `AttributeError: no attribute '_get_lots'` — `be9609ae` shipped 5 call sites, no helper; crash on every lot-aware partial exit / BE-arm / tier decision | `5015ebb1` defines `_get_lots` via the `IOMS.lot_size` port; `test_exits.py` 29/29 green |

## WS-B input — decision-path truth (verified, supersedes audit appendix)

`docs/reviews/2026-09-10-audit-appendices/audit-sizing-context.md:315` claimed the gate pipeline is bypassed on E2E. Verified **mode-dependent**:
- **Default mode:** `AmtScalpingStrategy(decision_service=…)` (`runtime.py:461`) → `DecisionService`/`GatePipeline` **LIVE** → WS-B's Gate-3 collapse governs default production.
- **`TIMESFM_END_TO_END`:** `TimesFMTradingStrategy` built without `decision_service` (`runtime.py:457`) and implements its own gates → bypass **true in this mode only**.

## Notes

- Order-dependent (outside canon): `test_half_trend_scale_parity` ×3 fail in one partial-suite ordering, pass in isolation re-run.
- WS-A interaction: the 19 pre-existing `tests/quant/decision/` failures are all Group-1 rows; WS-A's merge (`ad0b70c2`) changed none (byte-identical failure sets pre/post).
- Provenance: full-suite runs 1–2 (daemonized, `/tmp/wsc_run{1,2}.txt`), per-test `--tb=long` reruns, `git log -S` attribution, `25ea293f`-vs-`5015ebb1` A/B in ws-c worktree.
