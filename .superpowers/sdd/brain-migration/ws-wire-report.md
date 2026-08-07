# WS-WIRE — Execution Report

**Status: COMPLETE** — all three bypass paths wired through the realism guards; regression tests added; all pre-existing tests green.

## Summary

Context: WS-REALISM had already landed in the worktree (commits `1d21e53`, `8103284`), so the guards and module-level helpers `is_stop_too_thin` / `clamp_quantity` already existed in `quant/decision/signal_builder.py`. WS-WIRE closed the two remaining bypasses.

1. **Exposed helpers** — `quant/decision/signal_builder.py:21-29`: added `is_min_stop_met(entry, sl, min_stop_distance_pct=MIN_STOP_DISTANCE_PCT) -> bool` as the positive form of `is_stop_too_thin` (pure negation, no duplicated logic). `clamp_quantity(quantity, max_quantity=MAX_POSITION_QUANTITY)` was already exposed at module level. Both defaults equal the existing `MIN_STOP_DISTANCE_PCT = 0.1` / `MAX_POSITION_QUANTITY = 1000` constants. Triple-A `SignalBuilder.build()` path and its behavior/tests untouched.

2. **Runtime sizing** — `quant/runtime.py:125`: `quantity = self._risk.position_size(signal.entry, signal.sl)` → `quantity = clamp_quantity(self._risk.position_size(signal.entry, signal.sl))` (imported `clamp_quantity` from `quant.decision.signal_builder`). Uses the shared `MAX_POSITION_QUANTITY` default, so the engine can no longer submit a razor-thin-stop-sized position.

3. **VA-fade fallback** — `quant/decision/decision_service.py:45-47`: the VA-fade path now applies `is_min_stop_met(fade.entry, fade.sl)` before constructing the fade `Signal`; a sub-0.1% stop returns `NO_EDGE` (falls through, same semantics as the bottom-of-function branch). Triple-A path unchanged (already routed through `SignalBuilder.build()`).

## Commits (branch `migration/ws-wire`, worktree `wt-ws-wire`)

```
047ee15 test(quant): wiring guard tests
8832d33 fix(quant): apply min-stop guard to VA-fade fallback
666380a fix(quant): route runtime sizing through clamp (MAX_POSITION_QUANTITY)
eef32b3 refactor(quant): expose min-stop/clamp helpers on signal builder
```

Six files changed (`quant/decision/signal_builder.py`, `quant/runtime.py`, `quant/decision/decision_service.py`, `tests/quant/decision/test_signal_builder_guards.py`, `tests/quant/decision/test_decision_service.py`, `tests/quant/runtime/test_runtime.py`). `.superpowers/`, `docs/superpowers/plans/`, `docs/*.md` untouched.

## Verification

- `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short` → **1387 passed, 30 skipped** (baseline was 1379 passed; +8 new tests). 1 pre-existing RuntimeWarning in `tests/quant/contracts/test_sync_boundary.py`.
- `git status --short` → clean.

New tests (8):
- `test_signal_builder_guards.py` (4): `is_min_stop_met` defaults match `MIN_STOP_DISTANCE_PCT`; `is_min_stop_met` is the negation of `is_stop_too_thin`; override honored; `clamp_quantity` defaults match `MAX_POSITION_QUANTITY` (incl. `max_quantity=0` disable).
- `test_decision_service.py` (2): sub-0.1% VA-fade stop (entry 99.6, SL 99.61) → rejected as `NO_EDGE`; healthy ~0.1% stop → `VA_FADE` passes.
- `test_runtime.py` (2): razor-thin-stop signal that `SessionRisk` would size to 50,000 units now opens with `MAX_POSITION_QUANTITY` (1000); healthy 3% stop leaves the computed 333 units unclamped.

## Concerns

- **Runtime test uses a canned decision service**: to deterministically drive a razor-thin-stop signal through `QuantEngine._decide`, the runtime test swaps in a `_FixedDecisionService` returning a fixed approved `QuantDecision`. It pins the wiring (`clamp_quantity` applied to `position_size`) but does not end-to-end exercise the real gate pipeline; the end-to-end thin-stop rejection is covered at the `DecisionService` level instead.
- **Boundary is float-sensitive**: `is_stop_too_thin(100.0, 99.9)` is `True` because `100.0 * (0.1 / 100.0)` evaluates to `0.10000000000000001` (existing behavior, unmodified). Tests assert against the actual (not the decimal-exact) boundary. A future cleanup could switch to `<=`/`>=` or decimal math, but that is out of scope here.
- **`clamp_quantity` returns `float`**, not `int` as the brief's example signature suggested; kept as `float` to preserve existing builder behavior and tests.
