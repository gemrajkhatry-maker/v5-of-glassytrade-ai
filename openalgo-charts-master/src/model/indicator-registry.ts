/**
 * Indicator registry (ARCHITECTURE.md §6A, §8). The sibling of the chart-type
 * registry: that one answers *"how do I paint an array of bars"*, this one
 * answers *"what do I compute, what does it plot, and what can a user tune"*.
 *
 * A descriptor is data, not code-in-the-core — the chart never switches on an
 * indicator id. Each `plot` names a registered **chart type**, so indicators
 * ride the existing Family-A renderers and add no drawing code at all.
 *
 * The built-in descriptors live in the lazy `openalgo-charts/indicators` tier;
 * only the registry and the runtime ship in the base bundle, so an app that
 * plots its own maths pays nothing for the catalog.
 */
import type { Bar } from './bar';
import type { SeriesType } from './chart-type-registry';
import type { SeriesStyle } from '../render/series-style';
import type { PriceScaleId } from './series';
import type { SeriesMarker } from '../primitives/markers';
import type { TableCell, ChartTableOptions } from '../primitives/table';

/** Which price a calculation reads from each bar. */
export type IndicatorSource = 'open' | 'high' | 'low' | 'close' | 'hl2' | 'hlc3' | 'ohlc4' | 'volume';

/** One tunable input. `type` is what a settings UI renders; the core only reads `key`/`default`. */
export type IndicatorInput =
  | { key: string; type: 'number'; label: string; default: number; min?: number; max?: number; step?: number; group?: string }
  | { key: string; type: 'boolean'; label: string; default: boolean; group?: string }
  | { key: string; type: 'color'; label: string; default: string; group?: string }
  | { key: string; type: 'text'; label: string; default: string; group?: string }
  | { key: string; type: 'select'; label: string; default: string; options: readonly { label: string; value: string }[]; group?: string }
  | { key: string; type: 'source'; label: string; default: IndicatorSource; group?: string };

/** Line-style options, for a settings UI's Style tab. */
export const INDICATOR_LINE_STYLES: readonly { label: string; value: string }[] = [
  { label: 'Solid', value: 'solid' },
  { label: 'Dashed', value: 'dashed' },
  { label: 'Dotted', value: 'dotted' },
];

/** Settings keys the runtime derives for a plot's appearance. */
export function plotStyleKeys(plot: IndicatorPlot): {
  color: string; width: string; lineStyle: string; opacity: string; type: string;
} {
  return {
    // A descriptor that already declares a colour input owns that key — a
    // generated one would shadow it, and setting the declared key would
    // silently stop working.
    color: plot.colorKey ?? `${plot.key}:color`,
    width: `${plot.key}:width`,
    lineStyle: `${plot.key}:lineStyle`,
    opacity: `${plot.key}:opacity`,
    type: `${plot.key}:type`,
  };
}

/**
 * Per-plot appearance inputs, generated from the descriptor rather than
 * hand-written on each one — every indicator gets colour, opacity, thickness,
 * and line style for free, and a settings UI can render them as a "Style" tab
 * beside the descriptor's own `inputs`.
 *
 * Defaults come from the plot's declared style (and its legacy `colorKey`), so
 * an indicator that already ships colours keeps them.
 */
export function indicatorStyleInputs(descriptor: IndicatorDescriptor): IndicatorInput[] {
  const out: IndicatorInput[] = [];
  for (const plot of descriptor.plots) {
    const k = plotStyleKeys(plot);
    const declared = descriptor.inputs.find((i) => i.key === plot.colorKey);
    const color = typeof declared?.default === 'string'
      ? declared.default
      : (plot.style?.color ?? '#4f8cff');
    out.push({ key: k.color, type: 'color', label: plot.title, default: color, group: plot.title });
    out.push({
      key: k.opacity, type: 'number', label: 'Opacity', default: 100,
      min: 0, max: 100, step: 1, group: plot.title,
    });
    out.push({
      key: k.width, type: 'number', label: 'Thickness', default: plot.style?.lineWidth ?? 1.5,
      min: 0.5, max: 8, step: 0.5, group: plot.title,
    });
    out.push({
      key: k.lineStyle, type: 'select', label: 'Line style',
      default: plot.style?.lineStyle ?? 'solid',
      options: INDICATOR_LINE_STYLES, group: plot.title,
    });
    out.push({
      key: k.type, type: 'select', label: 'Plot style',
      default: plot.type,
      options: INDICATOR_PLOT_STYLES, group: plot.title,
    });
  }
  return out;
}

/**
 * Chart types a plot can be re-rendered as. A moving average is a line by
 * default, but the same column of numbers reads better as a histogram or an
 * area depending on what you are looking for — and a descriptor cannot know
 * which. Restricted to the types that make sense for a single value column.
 */
export const INDICATOR_PLOT_STYLES: readonly { label: string; value: string }[] = [
  { label: 'Line', value: 'line' },
  { label: 'Line with markers', value: 'line-markers' },
  { label: 'Step line', value: 'step' },
  { label: 'Area', value: 'area' },
  { label: 'Histogram', value: 'histogram' },
  { label: 'Columns', value: 'column' },
];

/** Canonical option list for a `type: 'source'` input, for settings UIs. */
export const INDICATOR_SOURCES: readonly { label: string; value: IndicatorSource }[] = [
  { label: 'Close', value: 'close' },
  { label: 'Open', value: 'open' },
  { label: 'High', value: 'high' },
  { label: 'Low', value: 'low' },
  { label: 'HL2', value: 'hl2' },
  { label: 'HLC3', value: 'hlc3' },
  { label: 'OHLC4', value: 'ohlc4' },
];

export type IndicatorSettings = Record<string, unknown>;

/** One plotted line/band/histogram. `type` is any registered chart type. */
/** A shaded band between two of an indicator's plots. */
export interface IndicatorFillSpec {
  /** The two plot keys to fill between. */
  between: readonly [string, string];
  /** Colour where the first plot is above the second. */
  colorUp?: string;
  /** Colour where the second is above the first. */
  colorDown?: string;
  /** Settings keys holding those colours, so the band is restyleable. */
  colorUpKey?: string;
  colorDownKey?: string;
  /** 0..1. Defaults to 0.12. */
  opacity?: number;
}

export interface IndicatorPlot {
  /** Key into the `calc` result. */
  key: string;
  /** Registered chart type used to draw it ('line', 'histogram', 'area', ...). */
  type: SeriesType;
  /** Legend title. */
  title: string;
  /** Style overrides merged onto the chart type's defaults. */
  style?: SeriesStyle;
  /** Price axis for this plot. Defaults to 'right'. */
  priceScaleId?: PriceScaleId;
  /**
   * Settings key holding this plot's color, so a settings change restyles the
   * series without a full rebuild.
   */
  colorKey?: string;
  /**
   * Per-bar colour, for plots whose meaning changes bar to bar — a MACD
   * histogram is four colours by sign and direction, a conditional study two.
   * Return `undefined` to fall back to the plot's own colour.
   *
   * Renderer support is required: histogram and column honour it today.
   */
  colorBy?(ctx: {
    value: number;
    index: number;
    values: IndicatorValues;
    settings: IndicatorSettings;
  }): string | undefined;
}

/** A horizontal reference level (RSI 70/30, Stochastic 80/20, a zero line). */
export interface IndicatorLevel {
  price: number;
  color?: string;
  title?: string;
  dashed?: boolean;
}

/** `calc` output: one array per plot key, aligned 1:1 with the input bars. */
export type IndicatorValues = Record<string, readonly (number | null)[]>;

/** Per-instance scratch owned by the descriptor (Tier-2 data lands here). */
export type IndicatorStore = Record<string, unknown>;

/** What an indicator's `attach` lifecycle can reach. */
export interface IndicatorAttachContext {
  /** Current settings (live — read at call time, not captured). */
  settings(): Readonly<IndicatorSettings>;
  /** The chart's current source bars. */
  bars(): readonly Bar[];
  /** Re-run `calc` and repaint — call when external data arrives. */
  requestRecompute(): void;
  /** Scratch this instance owns; the same object `calc` receives. */
  store: IndicatorStore;
}

export interface IndicatorDescriptor {
  /** Registry key, e.g. `'macd'`. */
  id: string;
  /** Display name, e.g. `'MACD'`. */
  name: string;
  /** Grouping for a picker UI ('Trend', 'Momentum', 'Volume', 'Volatility'). */
  category?: string;
  /** `'onchart'` overlays the price pane; `'pane'` gets its own pane. */
  placement: 'onchart' | 'pane';
  inputs: readonly IndicatorInput[];
  plots: readonly IndicatorPlot[];
  /**
   * Shaded bands between pairs of plots — the Ichimoku cloud, a Bollinger
   * channel. A pair of lines is not the same picture as a filled region: the
   * fill is what makes "price is above the cloud" readable at a glance, and
   * which side leads is itself the signal, hence the two colours.
   */
  fills?: readonly IndicatorFillSpec[];
  /**
   * Full recompute over every bar. Must return arrays the same length as
   * `bars` (use `null` for warmup gaps — the line renderer breaks across them
   * and autoscale skips them).
   *
   * Tier-1 indicators are pure functions of `(bars, settings)` and ignore
   * `store`. Tier-2 indicators — the ones with their own data — read the
   * external series their `attach` lifecycle put in `store`.
   */
  calc(
    bars: readonly Bar[],
    settings: Readonly<IndicatorSettings>,
    store: IndicatorStore,
  ): IndicatorValues;
  /**
   * Optional per-instance lifecycle, for indicators whose data is not derived
   * from the chart's bars (open interest, CVD, an external feed). Called once
   * when the instance is created; return a teardown function.
   *
   * Fetch into `ctx.store`, then call `ctx.requestRecompute()` — `calc` runs
   * again and reads what you stored.
   */
  attach?(ctx: IndicatorAttachContext): (() => void) | void;
  /**
   * Optional incremental path, called instead of `calc` when only the tail
   * changed (a live tick). Return values for indices `[fromIndex, bars.length)`
   * — the runtime splices them onto the previous result — or `null` to fall
   * back to a full `calc`.
   *
   * Without it every tick costs a full recompute. That is a few hundred
   * microseconds for one indicator over 50k bars, but it is O(n) per tick per
   * indicator, so implement this for anything meant to run in a busy live pane.
   */
  calcTail?(
    bars: readonly Bar[],
    settings: Readonly<IndicatorSettings>,
    fromIndex: number,
    previous: IndicatorValues,
    store: IndicatorStore,
  ): IndicatorValues | null;
  /**
   * Optional bar-anchored signal markers — a named "Buy"/"Sell" plate, an arrow
   * at a crossover. Runs after every `calc`, so it reads the values it just
   * produced rather than recomputing anything.
   *
   * A plot cannot express this: a plot is a column of prices drawn as a line or
   * histogram, whereas a signal is a discrete event with a label. Returning `[]`
   * (when a `showLabels`-style input is off, say) clears the layer.
   */
  markers?(ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): readonly SeriesMarker[];
  /**
   * Optional summary grid pinned to a corner of the pane.
   *
   * Some studies are not a value per bar at all: a seasonality heatmap is a
   * matrix of monthly returns, a scoreboard is a handful of statistics. Those
   * have no place in `calc`, whose contract is one column per plot aligned to
   * the bars, so they come back through here instead. Runs after every `calc`.
   *
   * Return `null` (or a zero-row grid) to draw nothing, which is how a
   * `showTable`-style input should switch it off.
   */
  table?(ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): { rows: readonly (readonly TableCell[])[]; options?: Partial<ChartTableOptions> } | null;
  /** Optional horizontal reference levels drawn in the indicator's pane. */
  levels?(settings: Readonly<IndicatorSettings>): readonly IndicatorLevel[];
  /**
   * Optional fixed price range for the indicator's own pane (RSI 0..100).
   * Applied only when the indicator creates its pane — two indicators sharing a
   * pane would otherwise fight over it.
   */
  range?(settings: Readonly<IndicatorSettings>): { min: number; max: number } | null;
}

const registry = new Map<string, IndicatorDescriptor>();

/** Register an indicator descriptor. Later registrations of the same id win. */
export function registerIndicator(descriptor: IndicatorDescriptor): void {
  registry.set(descriptor.id, descriptor);
}

export function getIndicator(id: string): IndicatorDescriptor {
  const d = registry.get(id);
  if (d === undefined) {
    throw new Error(
      `openalgo-charts: unknown indicator "${id}" — did you import 'openalgo-charts/indicators'?`,
    );
  }
  return d;
}

export function hasIndicator(id: string): boolean {
  return registry.has(id);
}

export function registeredIndicators(): IndicatorDescriptor[] {
  return Array.from(registry.values());
}

/** The descriptor's declared defaults as a settings object. */
export function indicatorDefaults(descriptor: IndicatorDescriptor): IndicatorSettings {
  const out: IndicatorSettings = {};
  for (const input of descriptor.inputs) out[input.key] = input.default;
  return out;
}

/** Read one bar's value for a price source. */
export function sourceValue(bar: Bar, source: IndicatorSource): number {
  switch (source) {
    case 'open': return bar.open;
    case 'high': return bar.high;
    case 'low': return bar.low;
    case 'hl2': return (bar.high + bar.low) / 2;
    case 'hlc3': return (bar.high + bar.low + bar.close) / 3;
    case 'ohlc4': return (bar.open + bar.high + bar.low + bar.close) / 4;
    case 'volume': return bar.volume ?? 0;
    default: return bar.close;
  }
}

/** Read a whole bar array for a price source. */
export function sourceValues(bars: readonly Bar[], source: IndicatorSource): number[] {
  const out = new Array<number>(bars.length);
  for (let i = 0; i < bars.length; i++) out[i] = sourceValue(bars[i], source);
  return out;
}
