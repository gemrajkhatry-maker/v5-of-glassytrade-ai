/**
 * Tier-1 volume indicators, computed from the chart's own OHLCV.
 * Part of the lazy `openalgo-charts/indicators` tier.
 */
import type { IndicatorDescriptor } from 'openalgo-charts';
import { nulls, sma, wma, rma, vwma, smaSeededEma, stdev } from './calc';

const num = (s: Readonly<Record<string, unknown>>, k: string, d: number): number => {
  const v = s[k];
  return typeof v === 'number' && Number.isFinite(v) ? v : d;
};
/** A window length is whole by construction; a settings blob carries whatever a UI wrote. */
const int = (s: Readonly<Record<string, unknown>>, k: string, d: number, min = 1): number =>
  Math.max(min, Math.round(num(s, k, d)));
const str = (s: Readonly<Record<string, unknown>>, k: string, d: string): string => {
  const v = s[k];
  return typeof v === 'string' && v !== '' ? v : d;
};

/** The selectable smoothing kernels of the "Smoothing" block. */
const SMOOTHING_MA_TYPES: readonly { label: string; value: string }[] = [
  { label: 'None', value: 'None' },
  { label: 'SMA', value: 'SMA' },
  { label: 'SMA + Bollinger Bands', value: 'SMA + Bollinger Bands' },
  { label: 'EMA', value: 'EMA' },
  { label: 'SMMA (RMA)', value: 'SMMA (RMA)' },
  { label: 'WMA', value: 'WMA' },
  { label: 'VWMA', value: 'VWMA' },
];

/** Set by `maType` when the two Bollinger band plots become visible. */
const BOLLINGER_MA = 'SMA + Bollinger Bands';

/**
 * The smoothing block's kernel switch. No warmup-gap handling here, unlike the
 * same block on a windowed study: a running total prints from bar 0, so the
 * smoother's window can start there too.
 */
function smoothingMa(
  kind: string,
  values: readonly number[],
  volumes: readonly number[],
  length: number,
): number[] {
  switch (kind) {
    case 'EMA': return smaSeededEma(values, length);
    case 'SMMA (RMA)': return rma(values, length);
    case 'WMA': return wma(values, length);
    case 'VWMA': return vwma(values, volumes, length);
    // 'SMA', the Bollinger variant, and (because a settings blob can carry
    // anything) everything else.
    default: return sma(values, length);
  }
}

export const VOLUME: IndicatorDescriptor = {
  id: 'volume',
  name: 'Volume',
  category: 'Volume',
  placement: 'pane',
  inputs: [{ key: 'color', type: 'color', label: 'Color', default: '#3a4666' }],
  plots: [{ key: 'volume', type: 'histogram', title: 'Volume', colorKey: 'color', style: { base: 0 } }],
  calc: (bars) => ({ volume: nulls(bars.map((b) => b.volume ?? 0)) }),
};

export const OBV: IndicatorDescriptor = {
  id: 'obv',
  name: 'On-Balance Volume',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'color', type: 'color', label: 'Color', default: '#26c6da' },
    {
      key: 'maType', type: 'select', label: 'Type', default: 'None',
      options: SMOOTHING_MA_TYPES, group: 'Smoothing',
    },
    { key: 'maLength', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1, group: 'Smoothing' },
    { key: 'bbMult', type: 'number', label: 'BB StdDev', default: 2, min: 0.001, max: 50, step: 0.5, group: 'Smoothing' },
    { key: 'maColor', type: 'color', label: 'OBV-based MA', default: '#ffeb3b', group: 'Smoothing' },
    { key: 'bbUpperColor', type: 'color', label: 'Upper Bollinger Band', default: '#4caf50', group: 'Smoothing' },
    { key: 'bbLowerColor', type: 'color', label: 'Lower Bollinger Band', default: '#4caf50', group: 'Smoothing' },
  ],
  plots: [
    { key: 'obv', type: 'line', title: 'OBV', colorKey: 'color', style: { lineWidth: 1.5 } },
    { key: 'ma', type: 'line', title: 'OBV-based MA', colorKey: 'maColor', style: { lineWidth: 1.5 } },
    { key: 'bbUpper', type: 'line', title: 'Upper Bollinger Band', colorKey: 'bbUpperColor', style: { lineWidth: 1 } },
    { key: 'bbLower', type: 'line', title: 'Lower Bollinger Band', colorKey: 'bbLowerColor', style: { lineWidth: 1 } },
  ],
  fills: [{
    between: ['bbUpper', 'bbLower'],
    colorUpKey: 'bbUpperColor',
    colorDownKey: 'bbUpperColor',
    opacity: 0.1,
  }],
  calc: (bars, s) => {
    const n = bars.length;
    const out = new Array<number>(n).fill(NaN);
    let acc = 0;
    for (let i = 0; i < n; i++) {
      if (i > 0) {
        const v = bars[i].volume ?? 0;
        if (bars[i].close > bars[i - 1].close) acc += v;
        else if (bars[i].close < bars[i - 1].close) acc -= v;
      }
      out[i] = acc;
    }

    const maType = str(s, 'maType', 'None');
    const maLength = int(s, 'maLength', 14);
    const mult = num(s, 'bbMult', 2);
    const ma = maType === 'None'
      ? new Array<number>(n).fill(NaN)
      : smoothingMa(maType, out, bars.map((b) => b.volume ?? 0), maLength);
    // The band offset exists only for the Bollinger kernel, and an absent
    // offset makes both band columns absent too, which is how the reference
    // keeps the two plots and their fill hidden for every other type.
    const band = maType === BOLLINGER_MA
      ? stdev(out, maLength).map((v) => v * mult)
      : new Array<number>(n).fill(NaN);

    return {
      obv: nulls(out),
      ma: nulls(ma),
      bbUpper: nulls(ma.map((v, i) => v + band[i])),
      bbLower: nulls(ma.map((v, i) => v - band[i])),
    };
  },
};

export const ADL: IndicatorDescriptor = {
  id: 'adl',
  name: 'Accumulation/Distribution',
  category: 'Volume',
  placement: 'pane',
  inputs: [{ key: 'color', type: 'color', label: 'Color', default: '#4f8cff' }],
  plots: [{ key: 'adl', type: 'line', title: 'A/D Line', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars) => {
    const out = new Array<number>(bars.length).fill(NaN);
    let acc = 0;
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i];
      const span = b.high - b.low;
      // A doji bar (high === low) has an undefined money-flow multiplier;
      // the standard treatment is to contribute nothing.
      if (span > 0) acc += (((b.close - b.low) - (b.high - b.close)) / span) * (b.volume ?? 0);
      out[i] = acc;
    }
    return { adl: nulls(out) };
  },
};
