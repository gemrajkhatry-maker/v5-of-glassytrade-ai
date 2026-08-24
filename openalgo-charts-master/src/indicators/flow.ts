/**
 * Built-in volume studies, ported to descriptor form.
 * Part of the lazy `openalgo-charts/indicators` tier.
 *
 * Each `calc` reproduces the published reference definition numerically, warmup gaps
 * included, so a plot here lines up bar for bar with the same study on
 * the reference platform. Where the published reference definitions differ from this library's own
 * helpers the reference-compatible variant in `./calc` is used: `smaSeededEma`, never the
 * base bundle's `ema`, because the two seed from different windows and would
 * disagree for the first `length` bars of every plot that touches them.
 */
import type { Bar, IndicatorDescriptor } from 'openalgo-charts';
import { change, cumulative, nulls, smaSeededEma, rollingSum, sma } from './calc';

const num = (s: Readonly<Record<string, unknown>>, k: string, d: number): number => {
  const v = s[k];
  return typeof v === 'number' && Number.isFinite(v) ? v : d;
};

/** the reference `nz(volume)`: a bar the feed gave no volume for traded nothing. */
const vol = (b: Bar): number =>
  typeof b.volume === 'number' && Number.isFinite(b.volume) ? b.volume : 0;

/**
 * The Accumulation/Distribution money-flow term, shared by Chaikin Money Flow
 * and the Chaikin Oscillator.
 *
 * The guard is the reference own and it is load-bearing: a bar with no range has an
 * undefined close location, and the reference platform contributes exactly 0 for it rather
 * than na. Letting the division stand would put a NaN into a running sum and
 * blank every bar after it.
 */
function moneyFlow(bars: readonly Bar[]): number[] {
  const out = new Array<number>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const degenerate = (b.close === b.high && b.close === b.low) || b.high === b.low;
    out[i] = degenerate ? 0 : ((2 * b.close - b.low - b.high) / (b.high - b.low)) * vol(b);
  }
  return out;
}

/**
 * the reference `ema` over a series that opens with a warmup gap.
 *
 * `change` is na on bar 0, so the input to an EMA built on it starts one bar
 * late. the reference seeds from the first *full window of real values*, which pushes
 * the whole plot one bar right; feeding the NaN straight to `smaSeededEma` would
 * instead poison the seed and blank the series forever.
 */
function emaFromFirstFinite(values: readonly number[], period: number): number[] {
  const out = new Array<number>(values.length).fill(NaN);
  const start = values.findIndex((v) => Number.isFinite(v));
  if (start < 0) return out;
  const tail = smaSeededEma(values.slice(start), period);
  for (let i = 0; i < tail.length; i++) out[start + i] = tail[i];
  return out;
}

/**
 * Chaikin Money Flow — the money-flow term summed over the window and
 * normalised by the volume traded in that same window, so the reading is a
 * bounded -1..+1 share of participation rather than a raw quantity.
 */
export const CHAIKIN_MONEY_FLOW: IndicatorDescriptor = {
  id: 'chaikin-money-flow',
  name: 'Chaikin Money Flow',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Color', default: '#43a047' },
  ],
  plots: [{ key: 'cmf', type: 'line', title: 'CMF', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const length = num(s, 'length', 20);
    const flow = rollingSum(moneyFlow(bars), length);
    const traded = rollingSum(bars.map(vol), length);
    const out = new Array<number>(bars.length).fill(NaN);
    for (let i = 0; i < bars.length; i++) {
      // A window that traded nothing has no flow to express as a share of it;
      // the reference division by zero yields na, so this stays a gap.
      if (traded[i] > 0) out[i] = flow[i] / traded[i];
    }
    return { cmf: nulls(out) };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/**
 * Chaikin Oscillator — a MACD of the A/D line.
 *
 * The two EMAs run over the *running total* of the money-flow term (the reference
 * `accdist`), not the per-bar term, so what the oscillator measures is
 * acceleration in accumulation rather than the flow itself.
 */
export const CHAIKIN_OSCILLATOR: IndicatorDescriptor = {
  id: 'chaikin-oscillator',
  name: 'Chaikin Oscillator',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'short', type: 'number', label: 'Fast Length', default: 3, min: 1, max: 500, step: 1 },
    { key: 'long', type: 'number', label: 'Slow Length', default: 10, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Color', default: '#ec407a' },
  ],
  plots: [{ key: 'osc', type: 'line', title: 'Chaikin Oscillator', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const accdist = cumulative(moneyFlow(bars));
    const fast = emaFromFirstFinite(accdist, num(s, 'short', 3));
    const slow = emaFromFirstFinite(accdist, num(s, 'long', 10));
    const out = new Array<number>(bars.length);
    for (let i = 0; i < bars.length; i++) out[i] = fast[i] - slow[i];
    return { osc: nulls(out) };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/**
 * Ease of Movement — how far the midpoint travelled per unit of volume, scaled
 * by the bar's range and by a divisor that only exists to bring the number into
 * a readable magnitude.
 */
export const EASE_OF_MOVEMENT: IndicatorDescriptor = {
  id: 'ease-of-movement',
  name: 'Ease of Movement',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'divisor', type: 'number', label: 'Divisor', default: 10000, min: 1, max: 1000000, step: 1 },
    { key: 'color', type: 'color', label: 'Color', default: '#43a047' },
  ],
  plots: [{ key: 'eom', type: 'line', title: 'EOM', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const divisor = num(s, 'divisor', 10000);
    const move = change(bars.map((b) => (b.high + b.low) / 2));
    const term = new Array<number>(bars.length);
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i];
      const v = vol(b);
      // No volume means no measure of how easily price moved. the reference divides by
      // zero and gets na; NaN here says the same thing, and `sma` refuses to
      // average a window holding one, which is exactly the reference platform's gap.
      term[i] = v === 0 ? NaN : (divisor * move[i] * (b.high - b.low)) / v;
    }
    return { eom: nulls(sma(term, num(s, 'length', 14))) };
  },
};

/**
 * Elder Force Index — the bar's price change weighted by the volume behind it,
 * smoothed. Direction and conviction in one number: a large move on thin
 * volume scores less than a small move the whole market took part in.
 */
export const ELDER_FORCE_INDEX: IndicatorDescriptor = {
  id: 'elder-force-index',
  name: 'Elder Force Index',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 13, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Color', default: '#f44336' },
  ],
  plots: [{ key: 'efi', type: 'line', title: 'Elder Force Index', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const moved = change(bars.map((b) => b.close));
    const force = new Array<number>(bars.length);
    for (let i = 0; i < bars.length; i++) force[i] = moved[i] * vol(bars[i]);
    return { efi: nulls(emaFromFirstFinite(force, num(s, 'length', 13))) };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/** Every the reference platform volume built-in in this module, in picker order. */
export const FLOW_INDICATORS: readonly IndicatorDescriptor[] = [
  CHAIKIN_MONEY_FLOW,
  CHAIKIN_OSCILLATOR,
  EASE_OF_MOVEMENT,
  ELDER_FORCE_INDEX,
];
