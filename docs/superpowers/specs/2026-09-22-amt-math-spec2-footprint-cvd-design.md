# Spec 2 — AMT Footprint / CVD Math Design

Date: 2026-09-22  
Parent: AMT Math Debt Program (verify-then-fix)  
Done-bar: focused order-flow tests + quant merge gate

## Problem

Four order-flow invariants are not enforced:

1. `FootprintAnalyzer.generate` rebuilds on same-length forming-bar updates and uses raw time keys, while `TickFootprintAccumulator` also compares raw keys. Equivalent epoch/ISO timestamps can therefore duplicate a candle or finalize it prematurely.
2. Gaussian per-level rounding does not conserve buy and sell allocations.
3. `CVDTracker.update` counts repeated delivery of the same candle more than once.
4. `CVDTracker.state()` mutates slope-persistence history, so reads alter later decisions.

## Expected Behavior Contract

| Axis | Contract |
|------|----------|
| Inputs | Real `OHLC` candles or live ticks. Timestamps may be epoch numbers/strings or ISO-8601. |
| Footprint keys | Every externally visible footprint dict key is `epoch_to_iso(time)`. Equivalent epoch and ISO instants collide. Opaque non-time labels remain unchanged. |
| Forming candle | A same-length analyzer update replaces only the final normalized key. Tick updates for the same normalized period continue accumulating in place. Completed candles remain intact. |
| Conservation | Generated Gaussian levels satisfy `Σask == round((volume + delta) / 2)` and `Σbid == round((volume - delta) / 2)`. Residual units are assigned to the POC/heaviest level. |
| CVD transition | A timestamp newer than the last appends one delta. An equal normalized timestamp is idempotent. A timestamp older than the last resets the session, then appends once. |
| CVD reads | `state()` returns a snapshot without changing CVD, histories, or slope-persistence state. Only `update()` advances persistence. |
| Failure mode | Empty data resets analyzer cache. Invalid/opaque timestamps compare as their unchanged text; no synthetic key is invented. |

## Runtime Cycle

Assume completed candle `09:15`, forming candle `09:20`, and the next feed delivery repeats `09:20` once as epoch and once as ISO.

1. Analyzer normalizes both keys to IST ISO and stores two candles.
2. Same-length refresh replaces only `09:20`; `09:15` survives.
3. The epoch/ISO repeat resolves to the same dict key, so no third candle exists.
4. Gaussian allocation rounds each level, computes side-specific residuals, and applies them to the heaviest level. Published ask/bid totals equal the rounded candle-side totals.
5. CVD receives `09:20` once and appends delta/history/slope persistence.
6. The equivalent timestamp compares equal and returns current state without mutation.
7. A later call to `state()` is observational only.
8. If the next normalized timestamp goes backwards, reset occurs before consuming that candle, preserving session rollover behavior.

Any implementation that compares raw timestamps, replaces the whole cache on a forming update, or lets `state()` append persistence history silently violates this cycle.

## Design

### Footprint timestamp ownership

Normalize at the two footprint state boundaries: `FootprintAnalyzer.generate` and `TickFootprintAccumulator.on_tick`. Generated `FootprintCandle.time` is normalized with its dict key. This is the smallest shared fix and avoids requiring every caller to pre-normalize.

### Incremental ownership

`FootprintAnalyzer` keeps completed cache entries and regenerates only the last candle when input length is unchanged or grows by one. Assignment by normalized key naturally replaces a shared time key. Shrink/reset/non-local growth performs a full rebuild.

### Gaussian conservation

Keep existing Gaussian weights and integer levels. After initial rounding, select the heaviest generated level and add each side's integer residual there. The target is the rounded non-negative buy/sell total because level volumes are discrete.

### CVD idempotency and persistence

Normalize the incoming timestamp before comparison. Equality returns `state()` immediately; backwards time resets; forward time appends once. `_compute_slope` receives an explicit persistence flag: `update()` advances sign history once, while `state()` only evaluates the current snapshot.

## Non-goals

No money-path, auction, TimesFM, options, Gate 1–4, seed, classifier, or execution-risk changes.

## Tests

- Same-length forming update preserves completed candles and replaces the final value.
- Growth with an equivalent epoch/ISO final key does not create a duplicate.
- Tick accumulator treats equivalent epoch/ISO candle times as one period.
- Gaussian buy/sell and total delta are conserved for a rounding-sensitive candle.
- Equal normalized CVD timestamps are idempotent.
- Backwards timestamp still resets.
- Repeated `state()` calls do not change slope persistence; `update()` advances it once.
# Spec 2 — Footprint / CVD Math Design

Date: 2026-09-22  
Parent: AMT Math Debt Program  
Done-bar: audit REPRO + merge-gate tests only

## Problem

1. **Forming-footprint overwrite** — `FootprintAnalyzer.generate` only incrementally updates when `len` grows by exactly 1; same-length forming refreshes full-rebuild. Worse: raw `candle.time` keys mean a forming refresh under a normalized twin key can orphan or duplicate completed candles.
2. **Epoch-vs-ISO keys** — footprint dict keys mix epoch ints and ISO strings for the same bar instant.
3. **Gaussian non-conservation** — per-level `round()` drifts Σ(ask)+Σ(bid) from candle volume/delta.
4. **Duplicate-timestamp CVD** — `CVDTracker.update` re-adds delta when the same bar time is fed twice (analyzer double-call / forming refresh).

## Contract

| Axis | Rule |
|------|------|
| Keys | All footprint cache/completed keys via `epoch_to_iso` |
| Forming | Same-length last-bar refresh updates only that key; completed candles retained |
| Gaussian | After allocation, residual ask/bid adjusted onto POC level so totals match |
| CVD | Identical normalized time → no double-count; time regress → session reset |

## Non-goals

Classifier, seed/multi-TF, money-path gates.
