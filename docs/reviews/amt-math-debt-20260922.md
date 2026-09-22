# AMT Math Debt — §1.7 carry-forward (post money-path)

Date: 2026-09-22 · After Waves 0–8 of `amt_fidelity_repair`.
Updated: Specs 1–4 closed (verify-then-fix). All §1.7 AMT-math rows resolved.

## Spec 4 closed

| Item | Locus | Notes |
|------|-------|-------|
| Cold CVD/IB/session-VWAP after seed | amt_engine seed | Fixed: complete idempotent seed replay; 2–4 bar seeds no longer omit the final bar |
| Session-rollover retention | amt_engine | Verified correct; rollover and EOD both persist levels, close, and non-option NPOC |
| 1m-decision-on-stale-5m-DTO | multi TF | Fixed: DTOs carry macro-bar time and shared tick-handler guard fails closed after one macro interval |

## Already addressed or obsolete vs audit

- `recent_window` NameError + VA clamp restored (Wave 0)
- LVN cluster uses `keep_highest=True` with inverted strength (strongest trough kept)
- Drive tracker requires departure before re-approach (`drive.py`)
- **Spec 2 — Forming-footprint overwrite:** same-length forming updates replace only the final candle; completed cache entries survive.
- **Spec 2 — Epoch-vs-ISO footprint key:** analyzer and tick accumulator normalize state keys with `epoch_to_iso`; equivalent instants collide.
- **Spec 2 — Gaussian footprint non-conservation:** per-side rounding residuals reconcile onto POC/heaviest levels; ask, bid, volume, and delta totals are conserved.
- **Spec 2 — Duplicate-timestamp CVD:** equal normalized timestamps return current state without appending delta/history; backwards time still resets the session.
- **Spec 2 — CVD `state()` honesty:** slope persistence advances only in `update()`; repeated reads are mutation-free.
- **Spec 1 — VA desert under-coverage:** gap guard is true-desert (`pair <= 0`) only; soft-shell REPRO reaches ≥70% (`test_soft_shell_reaches_value_area_pct`)
- **Spec 1 — Flat-price incremental profile:** zero-range rebuild uses 1 bucket, volume conserved (`test_identical_ltp_conserves_volume_in_one_bucket`)
- **Spec 1 — Clamped σ as statistical σ:** `SessionVWAP.recent_stats` publishes raw √variance; no 0.1%/3% floor/cap (`test_vwap_stats.py`)
- **Spec 3 — Balance-ratio OR-trigger:** removed as a state transition; low balance ratio now contributes only confidence/trigger context.
- **Spec 3 — B-shape forced BALANCED:** obsolete; the analyzer no longer overrides market state from profile shape and retains B as descriptive shape output.
- **Spec 3 — Sticky/both-sides acceptance:** acceptance is published only for the current close's boundary side; inside-VA closes clear both flags while timer decay and wick/sweep signals remain intact.
- **Spec 4 — Session rollover retention:** already correct. Date rollover persists POC/VAH/VAL/close, updates non-option NPOC, reloads prior levels, resets analyzer/candles, and EOD persistence covers no-next-day-bar shutdown.
