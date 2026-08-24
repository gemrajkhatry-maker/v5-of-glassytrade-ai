/**
 * Pure calculation helpers shared by the Tier-1 indicator descriptors
 * (`openalgo-charts/indicators`). Every function returns an array the same
 * length as its input, with `NaN` in warmup slots — the line renderer breaks
 * across non-finite points and autoscale skips them, so a warmup gap draws as
 * nothing rather than as a spike to zero.
 *
 * `ema`, `rsi`, `atr`, `trueRange`, and `supertrend` are NOT re-implemented
 * here — they ship in the base bundle and the tier imports them from it.
 */

/** Simple moving average. First value lands at index `period - 1`. */
export function sma(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  // The running sum must never absorb a non-finite value: `sum += NaN` poisons
  // it permanently, and subtracting the NaN back out when it leaves the window
  // does not restore it (NaN - NaN is NaN). Any input with a warmup gap -- an
  // indicator chained onto another -- would then be NaN for the whole series.
  // So sum only the finite values and count the rest.
  let sum = 0;
  let bad = 0;
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (Number.isFinite(v)) sum += v;
    else bad += 1;
    if (i >= period) {
      const gone = values[i - period];
      if (Number.isFinite(gone)) sum -= gone;
      else bad -= 1;
    }
    if (i >= period - 1) out[i] = bad === 0 ? sum / period : NaN;
  }
  return out;
}

/** Linearly weighted moving average (most recent bar carries weight `period`). */
export function wma(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  const denom = (period * (period + 1)) / 2;
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    for (let k = 0; k < period; k++) acc += values[i - k] * (period - k);
    out[i] = acc / denom;
  }
  return out;
}

/**
 * Wilder's smoothing (RMA): seed with the SMA of the first `period` values,
 * then `(prev * (period - 1) + v) / period`. The basis of RSI, ATR, and ADX.
 */
export function rma(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  let prev = sum / period;
  out[period - 1] = prev;
  for (let i = period; i < n; i++) {
    prev = (prev * (period - 1) + values[i]) / period;
    out[i] = prev;
  }
  return out;
}

/** Rolling population standard deviation over `period`. */
export function stdev(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  const means = sma(values, period);
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    const m = means[i];
    for (let k = 0; k < period; k++) {
      const d = values[i - k] - m;
      acc += d * d;
    }
    out[i] = Math.sqrt(acc / period);
  }
  return out;
}

/** Rolling maximum over `period` bars. */
export function highest(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  for (let i = period - 1; i < n; i++) {
    let m = -Infinity;
    for (let k = 0; k < period; k++) if (values[i - k] > m) m = values[i - k];
    out[i] = m;
  }
  return out;
}

/** Rolling minimum over `period` bars. */
export function lowest(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  for (let i = period - 1; i < n; i++) {
    let m = Infinity;
    for (let k = 0; k < period; k++) if (values[i - k] < m) m = values[i - k];
    out[i] = m;
  }
  return out;
}

/** NaN → null, so a warmup slot serialises as an explicit gap. */
export function nulls(values: readonly number[]): (number | null)[] {
  const out = new Array<number | null>(values.length);
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    out[i] = Number.isFinite(v) ? v : null;
  }
  return out;
}

// ── the reference-compatible helpers ───────────────────────────────────────────────
// These built-in indicators are ports of well-known published formulas, and
// two of those differ from what this file already exports. They are added here
// rather than by changing the originals, which are published API with their own
// documented behaviour (`ema` matches `openalgo.ta`, not the reference).

/**
 * the reference `ema`: seeded with the **SMA of the first `period` values**, NaN
 * before that. The base bundle's `ema` seeds from `values[0]` and emits from
 * index 0 instead, so the two disagree for roughly the first `period` bars and
 * converge after. Anything reproducing a reference platform plot needs this one.
 */
export function smaSeededEma(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  let prev = sum / period;
  out[period - 1] = prev;
  const k = 2 / (period + 1);
  for (let i = period; i < n; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** the reference `change(src, n)`: `src - src[n]`. NaN for the first `n` bars. */
export function change(values: readonly number[], n = 1): number[] {
  const len = values.length;
  const out = new Array<number>(len).fill(NaN);
  for (let i = n; i < len; i++) out[i] = values[i] - values[i - n];
  return out;
}

/** the reference `roc`: `100 * (src - src[n]) / src[n]`. NaN for the first `n` bars. */
export function roc(values: readonly number[], n: number): number[] {
  const len = values.length;
  const out = new Array<number>(len).fill(NaN);
  if (n <= 0) return out;
  for (let i = n; i < len; i++) {
    const base = values[i - n];
    out[i] = base === 0 ? NaN : (100 * (values[i] - base)) / base;
  }
  return out;
}

/**
 * the reference `dev`: mean **absolute** deviation from the SMA over `period` — not
 * a standard deviation. CCI's 0.015 constant is calibrated against this.
 */
export function dev(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  const means = sma(values, period);
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    for (let k = 0; k < period; k++) acc += Math.abs(values[i - k] - means[i]);
    out[i] = acc / period;
  }
  return out;
}

/**
 * the reference `percentrank`: the percentage of the **previous** `period` values
 * that are less than or equal to the current one. The current bar is the
 * subject of the comparison, not part of the window, so the first answer lands
 * at index `period`.
 */
export function percentRank(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  for (let i = period; i < n; i++) {
    let count = 0;
    for (let k = 1; k <= period; k++) if (values[i - k] <= values[i]) count += 1;
    out[i] = (count * 100) / period;
  }
  return out;
}

/** the reference `alma`: Gaussian-weighted MA, `offset` 0..1 and `sigma` > 0. */
export function alma(
  values: readonly number[],
  period: number,
  offset: number,
  sigma: number,
): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || sigma <= 0 || n < period) return out;
  const m = offset * (period - 1);
  const s = period / sigma;
  // The kernel depends only on the window position, so it is built once.
  const weights = new Array<number>(period);
  let norm = 0;
  for (let i = 0; i < period; i++) {
    const w = Math.exp(-((i - m) * (i - m)) / (2 * s * s));
    weights[i] = w;
    norm += w;
  }
  if (norm === 0) return out;
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    for (let k = 0; k < period; k++) acc += values[i - (period - 1 - k)] * weights[k];
    out[i] = acc / norm;
  }
  return out;
}

/** the reference `vwma`: `sma(src * volume, len) / sma(volume, len)`. */
export function vwma(
  values: readonly number[],
  volumes: readonly number[],
  period: number,
): number[] {
  const n = values.length;
  const pv = new Array<number>(n);
  for (let i = 0; i < n; i++) pv[i] = values[i] * (volumes[i] ?? 0);
  const num = sma(pv, period);
  const den = sma(volumes, period);
  const out = new Array<number>(n).fill(NaN);
  for (let i = 0; i < n; i++) out[i] = den[i] === 0 ? NaN : num[i] / den[i];
  return out;
}

/**
 * the reference `highestbars` / `lowestbars`: the **offset** to the extreme bar
 * in the window, `0` for the current bar and `-(period - 1)` for the oldest.
 * Aroon is built entirely out of these, and the sign convention is why.
 */
export function highestBars(values: readonly number[], period: number): number[] {
  return extremeBars(values, period, true);
}

export function lowestBars(values: readonly number[], period: number): number[] {
  return extremeBars(values, period, false);
}

function extremeBars(values: readonly number[], period: number, wantHigh: boolean): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  for (let i = period - 1; i < n; i++) {
    let best = values[i];
    let at = 0;
    for (let k = 1; k < period; k++) {
      const v = values[i - k];
      // Ties resolve to the most recent bar, matching the reference: the strict
      // comparison leaves `at` on the newer index when values are equal.
      if (wantHigh ? v > best : v < best) { best = v; at = k; }
    }
    // Normalised so a current-bar extreme is +0, not the -0 that negating a
    // zero offset produces. Arithmetic is unaffected, but -0 leaks into
    // Object.is comparisons and JSON round-trips.
    out[i] = at === 0 ? 0 : -at;
  }
  return out;
}

/** the reference `sum`: rolling sum over `period` bars. NaN during warmup. */
export function rollingSum(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  let acc = 0;
  for (let i = 0; i < n; i++) {
    acc += values[i];
    if (i >= period) acc -= values[i - period];
    if (i >= period - 1) out[i] = acc;
  }
  return out;
}

/** the reference `cum`: running total from the first bar. Non-finite terms count as 0. */
export function cumulative(values: readonly number[]): number[] {
  const n = values.length;
  const out = new Array<number>(n);
  let acc = 0;
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (Number.isFinite(v)) acc += v;
    out[i] = acc;
  }
  return out;
}

/**
 * the reference `linreg`: the least-squares regression line fitted over the last
 * `period` values, evaluated `offset` bars back from its right-hand end.
 *
 * x runs 0 (oldest bar in the window) to period-1 (current bar), so the value
 * at the current bar is `intercept + slope * (period - 1)`. A positive `offset`
 * steps back down that line, which is how LSMA's offset input shifts the plot
 * without recomputing the fit.
 */
export function linreg(values: readonly number[], period: number, offset = 0): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 1 || n < period) return out;
  // x is the same window every bar, so its sums are loop-invariant.
  const sumX = ((period - 1) * period) / 2;
  const sumXSqr = ((period - 1) * period * (2 * period - 1)) / 6;
  const denom = period * sumXSqr - sumX * sumX;
  if (denom === 0) return out;
  for (let i = period - 1; i < n; i++) {
    let sumY = 0;
    let sumXY = 0;
    for (let k = 0; k < period; k++) {
      const y = values[i - (period - 1 - k)]; // k = 0 is the oldest bar
      sumY += y;
      sumXY += y * k;
    }
    const slope = (period * sumXY - sumX * sumY) / denom;
    const intercept = (sumY - slope * sumX) / period;
    out[i] = intercept + slope * (period - 1 - offset);
  }
  return out;
}

/** the reference `swma`: the fixed 4-bar symmetrically weighted average, 1/2/2/1 over 6. */
export function swma(values: readonly number[]): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  for (let i = 3; i < n; i++) {
    out[i] = (values[i - 3] + 2 * values[i - 2] + 2 * values[i - 1] + values[i]) / 6;
  }
  return out;
}

/**
 * the reference `stoch(source, high, low, length)`. Note the three series are
 * independent: Stochastic RSI passes the RSI in for all three, which is why
 * this cannot just take bars.
 */
export function stoch(
  source: readonly number[],
  high: readonly number[],
  low: readonly number[],
  period: number,
): number[] {
  const n = source.length;
  const out = new Array<number>(n).fill(NaN);
  const hi = highest(high, period);
  const lo = lowest(low, period);
  for (let i = 0; i < n; i++) {
    const span = hi[i] - lo[i];
    out[i] = span === 0 ? NaN : (100 * (source[i] - lo[i])) / span;
  }
  return out;
}

/**
 * the reference `percentile_nearest_rank`. The nearest-rank method returns an
 * actual member of the window rather than interpolating between two, so a
 * 50th percentile over an even-length window is the upper of the two middles,
 * not their mean. That difference is visible on Median's default length of 3.
 */
export function percentileNearestRank(
  values: readonly number[],
  period: number,
  percentage: number,
): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  for (let i = period - 1; i < n; i++) {
    const win = values.slice(i - period + 1, i + 1);
    if (win.some((v) => !Number.isFinite(v))) continue;
    win.sort((a, b) => a - b);
    const rank = Math.max(1, Math.ceil((percentage / 100) * period));
    out[i] = win[rank - 1];
  }
  return out;
}

/** the reference `correlation`: Pearson correlation of two series over `period`. */
export function correlation(
  a: readonly number[],
  b: readonly number[],
  period: number,
): number[] {
  const n = a.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 1 || n < period) return out;
  for (let i = period - 1; i < n; i++) {
    let sa = 0, sb = 0, saa = 0, sbb = 0, sab = 0;
    for (let k = 0; k < period; k++) {
      const x = a[i - k];
      const y = b[i - k];
      sa += x; sb += y; saa += x * x; sbb += y * y; sab += x * y;
    }
    const cov = period * sab - sa * sb;
    const den = Math.sqrt(period * saa - sa * sa) * Math.sqrt(period * sbb - sb * sb);
    out[i] = den === 0 ? NaN : cov / den;
  }
  return out;
}

/** the reference `cci`: `(src - sma) / (0.015 * dev)`, where `dev` is the mean absolute deviation. */
export function cci(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  const mean = sma(values, period);
  const md = dev(values, period);
  for (let i = 0; i < n; i++) out[i] = md[i] === 0 ? NaN : (values[i] - mean[i]) / (0.015 * md[i]);
  return out;
}

/**
 * the reference `pivothigh` / `pivotlow`. A pivot is confirmed `right` bars
 * after it happens, so the answer lands on the confirming bar and refers to the
 * value `right` bars back. Comparisons are strict on both sides, so a tie is
 * not a pivot.
 */
export function pivotHigh(values: readonly number[], left: number, right: number): number[] {
  return pivot(values, left, right, true);
}

export function pivotLow(values: readonly number[], left: number, right: number): number[] {
  return pivot(values, left, right, false);
}

function pivot(values: readonly number[], left: number, right: number, wantHigh: boolean): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  for (let i = left + right; i < n; i++) {
    const at = i - right;
    const v = values[at];
    if (!Number.isFinite(v)) continue;
    let ok = true;
    for (let k = 1; k <= left && ok; k++) {
      const o = values[at - k];
      if (!Number.isFinite(o) || (wantHigh ? o >= v : o <= v)) ok = false;
    }
    for (let k = 1; k <= right && ok; k++) {
      const o = values[at + k];
      if (!Number.isFinite(o) || (wantHigh ? o >= v : o <= v)) ok = false;
    }
    if (ok) out[i] = v;
  }
  return out;
}

/** the reference `barssince`: bars elapsed since `cond` was last true, NaN before the first. */
export function barsSince(cond: readonly boolean[]): number[] {
  const n = cond.length;
  const out = new Array<number>(n).fill(NaN);
  let last = -1;
  for (let i = 0; i < n; i++) {
    if (cond[i]) last = i;
    if (last >= 0) out[i] = i - last;
  }
  return out;
}

/**
 * the reference `valuewhen(cond, source, occurrence)`: the value of `source` the
 * n-th most recent time `cond` was true, counting the current bar. Occurrence 0
 * is the latest.
 */
export function valueWhen(
  cond: readonly boolean[],
  source: readonly number[],
  occurrence: number,
): number[] {
  const n = cond.length;
  const out = new Array<number>(n).fill(NaN);
  const hits: number[] = [];
  for (let i = 0; i < n; i++) {
    if (cond[i]) hits.push(i);
    const at = hits.length - 1 - occurrence;
    if (at >= 0) out[i] = source[hits[at]];
  }
  return out;
}
