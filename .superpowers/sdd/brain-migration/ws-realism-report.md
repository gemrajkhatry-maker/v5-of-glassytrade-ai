# WS-REALISM — Execution Report

**Status: COMPLETE** — all three deliverables implemented, verified, committed.

## Summary

1. **Min-stop + max-size guards** in `quant/decision/signal_builder.py` (greenfield `SignalBuilder`):
   - Added module constants `MIN_STOP_DISTANCE_PCT = 0.1` and `MAX_POSITION_QUANTITY = 1000` (`quant/decision/signal_builder.py:6-7`), both constructor-overridable via `SignalBuilder(min_stop_distance_pct=..., max_position_quantity=...)`.
   - Pure helpers `is_stop_too_thin(entry, sl, pct)` and `clamp_quantity(quantity, max)` (`signal_builder.py:10-31`).
   - `build()` now rejects sub-0.1% stops (`return None` = "no edge") via `signal_builder.py:96-97`.
   - `SignalBuilder.size()` applies the fixed-fractional sizing formula with the quantity clamped at the sizing step (never silently in fills) — `signal_builder.py:119-136`.
   - No behavior change for healthy setups: all pre-existing `tests/quant/decision/` signal-builder tests pass unmodified.

2. **Tests** in `tests/quant/decision/test_signal_builder_guards.py` (8 tests):
   - (a) thin-stop setup (104.92/104.90, ~0.02%) rejected; pure-function thin-stop checks.
   - (b) healthy setup (3% stop) still builds; healthy quantity unclamped.
   - (c) huge quantity (50,000 → 1000) clamped; `clamp_quantity` verified; override (`max_position_quantity=500`) honored.
   - (d) defaults exported constants; constructor defaults match.

3. **`backend/start_paper.sh`** (executable, `chmod +x`):
   - Verified paper-mode env vars: `QUANT_EXECUTION_MODE` (highest priority, wins over `feature_flags.yaml` `quant_execution_mode: "off"`) per `backend/app/config_models/settings_adapter.py:257-273`; `GLASSYTRADE_ENV=paper` selects `environments/paper.yaml` (`broker_mode: paper`) per `config_models/loader.py:173`; `TRADING_MODE=paper` mirrors the live-mode detector in `app/shared/mode.py`.
   - Script exports `QUANT_EXECUTION_MODE=paper`, `TRADING_MODE=paper`, `GLASSYTRADE_ENV=paper`, prints guidance to run `backend/scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl` after the session, then `exec ./start.sh "$@"`.

## Commits (branch `migration/ws-realism`, worktree `wt-ws-realism`)

```
cca6f10 feat(scripts): start_paper.sh paper-week launcher
8103284 test(quant): signal-builder realism guards
1d21e53 feat(quant): min-stop + max-size guards in signal builder
```

Only these three files changed; `.superpowers/`, `docs/superpowers/plans/`, `docs/*.md` untouched.

## Verification

- `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short` → **1376 passed, 30 skipped** (baseline suite + 8 new guard tests).
- `bash -n backend/start_paper.sh` → passes (syntax OK).
- `git status --short` → clean.

## Concerns

- **Guard only on greenfield `SignalBuilder`**: the VA-fade tier-2 path in `decision_service.py` (`detect_va_fade`, `decision_service.py:44-49`) constructs `Signal` directly, bypassing `SignalBuilder.build()`. A razor-thin stop produced by `detect_va_fade` (e.g. `sl = val - step`) would still be emitted when gates fail. The brief scoped guards to the greenfield builder; if the paper week shows VA-fade thin stops, `decision_service.py` should route VA-fade through `is_stop_too_thin` too.
- **Clamp is applied via `SignalBuilder.size()`**: the runtime sizing path in `quant/runtime.py:124` still calls `SessionRisk.position_size()` directly. The clamp lives at the builder's sizing API; wiring `QuantEngine`/EntryCoordinator to `SignalBuilder.size()` (or `clamp_quantity`) is the natural follow-up so live/paper execution always hits the ceiling.
