# WS-REALISM — VA-fade min-stop/max-size guard + paper-run launcher

**Worktree:** `/Users/apple/Documents/wt-ws-realism` (branch `migration/ws-realism`). Work ONLY there.

**Context:** WS-SMOKE flagged a realism issue: the VA-fade signal builder produces a **razor-thin stop** (`sl = val-step`, `tp = poc`), e.g. entry 104.92 / sl 104.90 (~0.02% distance), which with the paper sizing produces ~50,000-unit positions — unrealistic and unsafe. This task adds production guards (no behavior change for healthy setups) plus an operator launcher for the §5.5 paper week.

**Part 1 — min-stop / max-size guard in `quant/decision/signal_builder.py` (the greenfield `SignalBuilder`):**
- Read the current signal builder (it builds `{entry, sl, tp, rr}`). Add TWO guards that reject/repair only the pathological cases:
  - `MIN_STOP_DISTANCE_PCT = 0.1` (percent of price) — if `abs(entry - sl)` is below this (i.e. a sub-0.1% stop), do NOT emit a Signal (return the "no edge" result / reject the build) unless the caller explicitly overrides. Rationale: a 0.02% stop is noise, not a structural stop (architecture proposal: SL at structural VAH/VAL/LVN).
  - `MAX_POSITION_QUANTITY = 1000` — clamp the computed quantity to this ceiling so paper/live size can never explode on razor-thin stops. The clamp must be applied in the sizing step, not silently in fills.
- Implement as pure functions with the two thresholds as named constants in the module; keep them overridable via constructor args with those defaults.
- Add tests: (a) a thin-stop setup is rejected; (b) a healthy setup (SL ≥0.1% away) still builds; (c) a huge quantity is clamped to `MAX_POSITION_QUANTITY`; (d) the defaults are exported constants.
- These guards change NO healthy-setup behavior — verify the existing `tests/quant/decision/` signal-builder tests still pass unmodified (if one asserted the thin-stop builds, update it deliberately with a comment).

**Part 2 — `backend/start_paper.sh` operator launcher:**
- A small script that runs the backend in paper mode with the quant path live: sets `QUANT_EXECUTION_MODE=paper`, `TRADING_MODE=paper` (verify the actual env var used for paper mode in `app/config*/settings_adapter.py` and `config/feature_flags.yaml`; use those), and execs the normal start (find how the backend is started — `backend/start.sh` — and chain to it).
- Add `echo` guidance: after a paper session, run `backend/scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl`.
- Make it executable (`chmod +x`).

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short` (worktree root). `bash -n backend/start_paper.sh`. Report exact counts.

**Commits:** `feat(quant): min-stop + max-size guards in signal builder`, `test(quant): signal-builder realism guards`, `feat(scripts): start_paper.sh paper-week launcher`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-realism-report.md`. Reply: status, commits, test counts, concerns.
