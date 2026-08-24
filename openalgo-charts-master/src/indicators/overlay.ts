/**
 * Built-in overlays — the seven price-pane studies whose behaviour
 * is specified against the published reference definitions rather than this library's own.
 * Part of the lazy `openalgo-charts/indicators` tier.
 *
 * Parity note, and the reason `ema` is absent from the imports: the reference `ema`
 * seeds from the SMA of the first `length` values and is `na` before that, while
 * the base bundle's `ema` seeds from `values[0]` and emits from bar 0 to match
 * `openalgo.ta`. The two disagree over the whole warmup, so anything that has to
 * land on the same pixels as a reference platform plot uses `smaSeededEma` from `./calc`.
 *
 * `atr` and the `sourceValues` helper come from the base bundle
 * (`openalgo-charts`), not deep paths — see the note in `src/indicators/index.ts`.
 */
import { atr, sourceValues } from 'openalgo-charts';
import type { IndicatorDescriptor, IndicatorSource } from 'openalgo-charts';
import { sma, wma, highest, lowest, nulls, smaSeededEma, alma } from './calc';

const num = (s: Readonly<Record<string, unknown>>, k: string, d: number): number => {
  const v = s[k];
  return typeof v === 'number' && Number.isFinite(v) ? v : d;
};
/** the reference `input.int` is whole by construction; a settings blob carries whatever a UI wrote. */
const int = (s: Readonly<Record<string, unknown>>, k: string, d: number, min = 1): number =>
  Math.max(min, Math.round(num(s, k, d)));
const src = (s: Readonly<Record<string, unknown>>, k = 'source'): IndicatorSource =>
  (s[k] as IndicatorSource) ?? 'close';

const highs = (bars: readonly { high: number }[]): number[] => bars.map((b) => b.high);
const lows = (bars: readonly { low: number }[]): number[] => bars.map((b) => b.low);

/**
 * `smaSeededEma` over a series that itself opens with a warmup gap. the reference `ema`
 * re-seeds from `sma(src, length)` for as long as its own previous value is
 * `na`, and that SMA stays `na` until the window holds `length` real values — so
 * an EMA of an EMA first prints at `2 * length - 2`, not at `length - 1`.
 * `smaSeededEma` seeds unconditionally from index 0, where a leading NaN would poison
 * the recursion forever, so it is only ever shown the live tail.
 */
function emaOfGapped(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  let start = 0;
  while (start < n && !Number.isFinite(values[start])) start += 1;
  if (start >= n) return out;
  const tail = smaSeededEma(values.slice(start), period);
  for (let i = 0; i < tail.length; i++) out[start + i] = tail[i];
  return out;
}

/**
 * A rolling extreme that refuses any window containing a warmup gap. `highest` /
 * `lowest` in `./calc` step over non-finite values, which is what you want for
 * raw highs and lows but not when the input is itself an indicator: the reference builds
 * `highest` out of `max`, and `max(na, x)` is `na`, so a window
 * straddling the inner series' warmup is `na` across its whole span. Chande
 * Kroll stacks one extreme on top of another and is the only place it shows.
 */
function extremeStrict(values: readonly number[], period: number, wantHigh: boolean): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  for (let i = period - 1; i < n; i++) {
    let best = wantHigh ? -Infinity : Infinity;
    let live = true;
    for (let k = 0; k < period; k++) {
      const v = values[i - k];
      if (!Number.isFinite(v)) { live = false; break; }
      if (wantHigh ? v > best : v < best) best = v;
    }
    if (live) out[i] = best;
  }
  return out;
}

/** the reference `plot(..., offset = n)`: positive draws the value `n` bars later. */
function shift(values: readonly number[], k: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  for (let i = 0; i < n; i++) {
    const j = i - k;
    if (j >= 0 && j < n) out[i] = values[j];
  }
  return out;
}

/**
 * the reference fills these channels with `color.rgb(33, 150, 243, 95)` — 95 % transparent,
 * so the band is a hint rather than a wash. Kept as-is so the overlay reads the
 * same here as on the reference platform.
 */
const CHANNEL_FILL_OPACITY = 0.05;

/**
 * The source is hard-coded to `close` in the reference (`source = close`,
 * not an `input`), so there is no source setting to expose.
 */
export const ALMA: IndicatorDescriptor = {
  id: 'alma',
  name: 'Arnaud Legoux Moving Average',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'offset', type: 'number', label: 'Offset', default: 0.85, min: 0, max: 1, step: 0.01 },
    { key: 'sigma', type: 'number', label: 'Sigma', default: 6, min: 0.1, max: 100, step: 0.1 },
    { key: 'color', type: 'color', label: 'ALMA', default: '#2962ff' },
  ],
  plots: [{
    key: 'alma', type: 'line', title: 'ALMA', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => ({
    alma: nulls(alma(
      sourceValues(bars, 'close'),
      int(s, 'length', 9),
      num(s, 'offset', 0.85),
      num(s, 'sigma', 6),
    )),
  }),
};

/**
 * `2 * ema - ema(ema)`. The second pass runs over a series that is already NaN
 * for its own warmup, which is what pushes the first plotted bar out to
 * `2 * length - 2` — see `emaOfGapped`.
 */
export const DEMA: IndicatorDescriptor = {
  id: 'dema',
  name: 'Double EMA',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'DEMA', default: '#43a047' },
  ],
  plots: [{
    key: 'dema', type: 'line', title: 'DEMA', colorKey: 'color',
    style: { color: '#43a047', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const length = int(s, 'length', 9);
    const e1 = smaSeededEma(values, length);
    const e2 = emaOfGapped(e1, length);
    return { dema: nulls(e1.map((v, i) => 2 * v - e2[i])) };
  },
};

export const HMA: IndicatorDescriptor = {
  id: 'hma',
  name: 'Hull Moving Average',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 2, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'HMA', default: '#2962ff' },
  ],
  plots: [{
    key: 'hma', type: 'line', title: 'HMA', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const length = int(s, 'length', 9, 2);
    // the reference `length / 2` divides two ints and truncates — `wma` takes an int
    // period, so 9 smooths over 4 bars, never 4.5. Both periods are floored and
    // clamped so a degenerate setting cannot ask for a zero-bar window.
    const half = Math.max(1, Math.floor(length / 2));
    const root = Math.max(1, Math.floor(Math.sqrt(length)));
    const fast = wma(values, half);
    const slow = wma(values, length);
    // `wma` carries NaN through its accumulator, so the raw series' warmup
    // propagates into the smoothing pass without any masking here.
    const raw = fast.map((v, i) => 2 * v - slow[i]);
    return { hma: nulls(wma(raw, root)) };
  },
};

export const ENVELOPE: IndicatorDescriptor = {
  id: 'envelope',
  name: 'Envelope',
  category: 'Volatility',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'percent', type: 'number', label: 'Percent', default: 10, min: 0, max: 100, step: 0.1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'exponential', type: 'boolean', label: 'Exponential', default: false },
    { key: 'basisColor', type: 'color', label: 'Basis', default: '#ff6d00' },
    { key: 'bandColor', type: 'color', label: 'Bands', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'upper', type: 'line', title: 'Env Upper', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
    { key: 'basis', type: 'line', title: 'Env Basis', colorKey: 'basisColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
    { key: 'lower', type: 'line', title: 'Env Lower', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
  ],
  fills: [{
    between: ['upper', 'lower'],
    colorUpKey: 'fillColor',
    colorDownKey: 'fillColor',
    opacity: CHANNEL_FILL_OPACITY,
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const length = int(s, 'length', 20);
    const k = num(s, 'percent', 10) / 100;
    const basis = s.exponential === true ? smaSeededEma(values, length) : sma(values, length);
    return {
      upper: nulls(basis.map((b) => b * (1 + k))),
      basis: nulls(basis),
      lower: nulls(basis.map((b) => b * (1 - k))),
    };
  },
};

export const DONCHIAN: IndicatorDescriptor = {
  id: 'donchian',
  name: 'Donchian Channels',
  category: 'Volatility',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'basisColor', type: 'color', label: 'Basis', default: '#ff6d00' },
    { key: 'bandColor', type: 'color', label: 'Bands', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'upper', type: 'line', title: 'DC Upper', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
    { key: 'basis', type: 'line', title: 'DC Basis', colorKey: 'basisColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
    { key: 'lower', type: 'line', title: 'DC Lower', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
  ],
  fills: [{
    between: ['upper', 'lower'],
    colorUpKey: 'fillColor',
    colorDownKey: 'fillColor',
    opacity: CHANNEL_FILL_OPACITY,
  }],
  calc: (bars, s) => {
    const length = int(s, 'length', 20);
    // Offset is a displacement, so it is the one setting that may be negative.
    const offset = Math.round(num(s, 'offset', 0));
    const upper = highest(highs(bars), length);
    const lower = lowest(lows(bars), length);
    const basis = upper.map((u, i) => (u + lower[i]) / 2);
    return {
      upper: nulls(shift(upper, offset)),
      basis: nulls(shift(basis, offset)),
      lower: nulls(shift(lower, offset)),
    };
  },
};

/**
 * Two stacked extremes: an ATR-padded high/low band, then the running extreme of
 * *that* over `q` bars, which is what keeps each stop monotone through a pullback.
 * The second pass is NaN-strict (`extremeStrict`), so nothing prints until the
 * whole `q`-bar window is past the ATR warmup — bar `p + q - 2`.
 */
export const CHANDE_KROLL_STOP: IndicatorDescriptor = {
  id: 'chande-kroll-stop',
  name: 'Chande Kroll Stop',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'p', type: 'number', label: 'ATR Length (p)', default: 10, min: 1, max: 500, step: 1 },
    { key: 'x', type: 'number', label: 'ATR Coefficient (x)', default: 1, min: 1, max: 100, step: 1 },
    { key: 'q', type: 'number', label: 'Stop Length (q)', default: 9, min: 1, max: 500, step: 1 },
    { key: 'longColor', type: 'color', label: 'Stop Long', default: '#2962ff' },
    { key: 'shortColor', type: 'color', label: 'Stop Short', default: '#ff6d00' },
  ],
  plots: [
    { key: 'stopLong', type: 'line', title: 'Stop Long', colorKey: 'longColor', style: { color: '#2962ff', lineWidth: 1.5 } },
    { key: 'stopShort', type: 'line', title: 'Stop Short', colorKey: 'shortColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const p = int(s, 'p', 10);
    const x = int(s, 'x', 1);
    const q = int(s, 'q', 9);
    const high = highs(bars);
    const low = lows(bars);
    const range = atr(high, low, bars.map((b) => b.close), p);
    const firstHighStop = highest(high, p).map((v, i) => v - x * range[i]);
    const firstLowStop = lowest(low, p).map((v, i) => v + x * range[i]);
    return {
      stopLong: nulls(extremeStrict(firstLowStop, q, false)),
      stopShort: nulls(extremeStrict(firstHighStop, q, true)),
    };
  },
};

/**
 * The reference imports an external helper library and calls `an external `chandelier()` helper`, whose
 * body is not in the reference file. This is the published definition of that stop:
 * the highest high of the window pulled down by `mult` ATRs, and its mirror.
 */
export const CHANDELIER_EXIT: IndicatorDescriptor = {
  id: 'chandelier-exit',
  name: 'Chandelier Exit',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 22, min: 1, max: 500, step: 1 },
    { key: 'atrLength', type: 'number', label: 'ATR length', default: 22, min: 1, max: 500, step: 1 },
    { key: 'atrMultiplier', type: 'number', label: 'ATR multiplier', default: 3, min: 0, max: 50, step: 0.01 },
    { key: 'longColor', type: 'color', label: 'Long exit', default: '#2962ff' },
    { key: 'shortColor', type: 'color', label: 'Short exit', default: '#ff6d00' },
  ],
  plots: [
    { key: 'longExit', type: 'line', title: 'Long Exit', colorKey: 'longColor', style: { color: '#2962ff', lineWidth: 1.5 } },
    { key: 'shortExit', type: 'line', title: 'Short Exit', colorKey: 'shortColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const length = int(s, 'length', 22);
    const mult = num(s, 'atrMultiplier', 3);
    const high = highs(bars);
    const low = lows(bars);
    const range = atr(high, low, bars.map((b) => b.close), int(s, 'atrLength', 22));
    return {
      longExit: nulls(highest(high, length).map((v, i) => v - mult * range[i])),
      shortExit: nulls(lowest(low, length).map((v, i) => v + mult * range[i])),
    };
  },
};

export const OVERLAY_INDICATORS: readonly IndicatorDescriptor[] = [
  ALMA, DEMA, HMA, ENVELOPE, DONCHIAN, CHANDE_KROLL_STOP, CHANDELIER_EXIT,
];
