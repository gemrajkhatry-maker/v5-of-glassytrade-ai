# Spec 1 — AMT Profile / VA Math Design

Date: 2026-09-22  
Parent: AMT Math Debt Program (verify-then-fix)  
Done-bar: audit REPRO + merge-gate tests only

## Problem

Three profile/VA honesty bugs remain after money-path waves:

1. **VA desert under-coverage** — `compute_value_area` gap guard uses `pair < 1% of POC`, which freezes expansion on quiet-but-nonzero shells (~45% coverage) while still correctly blocking true zero-volume leaps to stale tails.
2. **Flat-price incremental** — `IncrementalVolumeProfile._full_rebuild` on `price_range == 0` spreads volume across all buckets at 50/50 buy/sell, inventing fake width.
3. **Clamped σ as statistical σ** — `SessionVWAP.recent_stats` floor/caps std (0.1%–3% of VWAP) then publishes it as `vwap_std` for bands / anti-climax.

## Contract

| Axis | Rule |
|------|------|
| VA | Expand via CME two-row method until `VALUE_AREA_PCT` **or** a true volume desert (pair volume ≤ 0). Soft nonzero shells must expand. Zero-gap + far stale tail must not leap (existing CRUDEOIL test). |
| Flat incremental | Identical OHLC → one bucket, full volume conserved, buy_ratio from taker_buy/delta (not forced 50/50 across N buckets). |
| σ | `vwap_std` is the raw volume-weighted std. No proportional floor/cap inside `recent_stats`. Deviation-multiple clamp at ±4σ in `bands()` stays (display sanity only). |

## Non-goals

Footprint, CVD, classifier, seed/multi-TF (Specs 2–4). Money-path gates/sizing unchanged.

## Design

### A — Desert guard

In `compute_value_area`, replace `min_pair_vol = poc_vol * 0.01` with a true-desert check: `up_pair <= 0` / `down_pair <= 0` (float-safe: `<= 0.0`).

### B — Flat rebuild

When `price_range == 0`: `_buckets = 1`, single cell gets `total_vol` and honest buy/sell from candle taker ratios (aggregate), `_step = max(tick_size, 1e-6)`.

### C — σ honesty

`recent_stats` returns unclamped `sqrt(variance)`. Callers needing display floors do so explicitly (none required for Spec 1).

## Tests

- Soft-shell REPRO: POC + contiguous vol=4 shell + outer mass → coverage ≥ 0.70.
- Keep `test_sparse_far_tail_does_not_inflate_vah` green.
- Flat incremental: N identical LTPs → one nonzero bucket, Σ volume = N×vol.
- `recent_stats` tiny true std not inflated to `max(1.0, 0.1%×vwap)`.
