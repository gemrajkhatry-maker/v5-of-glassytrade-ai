# WS-WIRE — Route all signal sizing/exits through the realism guards

**Worktree:** `/Users/apple/Documents/wt-ws-wire` (branch `migration/ws-wire`). Work ONLY there.

**Context:** WS-REALISM added `MIN_STOP_DISTANCE_PCT = 0.1` and `MAX_POSITION_QUANTITY = 1000` (constructor-overridable) to `quant/decision/signal_builder.py` (guards in the Triple-A `SignalBuilder.build()` path). But TWO paths bypass them (flagged in ws-realism-report):
1. `quant/runtime.py:124` — `quantity = self._risk.position_size(signal.entry, signal.sl)` computes the quantity directly from `SessionRisk`, ignoring the builder's clamp.
2. `quant/decision/decision_service.py:44-49` — the VA-fade fallback builds a `Signal(...)` directly (bypassing `SignalBuilder.build()`), so a razor-thin stop can still pass.

**Task:**
1. In `quant/decision/signal_builder.py`, expose the existing guard logic as REUSABLE functions (or keep the constructor params and add module-level helpers): e.g. `is_min_stop_met(entry, sl, min_stop_distance_pct=None) -> bool` and `clamp_quantity(qty, max_quantity=None) -> int`. Keep the defaults equal to the existing `MIN_STOP_DISTANCE_PCT`/`MAX_POSITION_QUANTITY`. Do not change the existing builder behavior/tests.
2. `quant/runtime.py`: replace `quantity = self._risk.position_size(signal.entry, signal.sl)` with `quantity = clamp_quantity(self._risk.position_size(signal.entry, signal.sl))` (import from `quant.decision.signal_builder`). Same override defaults.
3. `quant/decision/decision_service.py` VA-fade path: before returning the fade `Signal`, apply `is_min_stop_met(fade.entry, fade.sl)`; if the stop is too thin, skip the fade (fall through to NO_EDGE). Do NOT change the Triple-A path (it already goes through `SignalBuilder.build()`).
4. Add tests:
   - `tests/quant/runtime/test_runtime_*.py` (or the existing runtime test): a razor-thin-stop signal that would produce a huge quantity now yields quantity clamped to `MAX_POSITION_QUANTITY`.
   - `tests/quant/decision/test_va_fade_*.py`: a fade with a sub-0.1% stop is rejected (decision = NO_EDGE / not VA_FADE); a healthy fade still passes.
   - `tests/quant/decision/test_signal_builder_*.py`: the two new helpers behave per spec (defaults match the constants).

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short` (worktree root). Report exact counts. All pre-existing tests must stay green.

**Commits:** `refactor(quant): expose min-stop/clamp helpers on signal builder`, `fix(quant): route runtime sizing through clamp (MAX_POSITION_QUANTITY)`, `fix(quant): apply min-stop guard to VA-fade fallback`, `test(quant): wiring guard tests`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-wire-report.md`. Reply: status, commits, test counts, concerns.
