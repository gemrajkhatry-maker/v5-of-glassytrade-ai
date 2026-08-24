/**
 * Tier-2 contract — indicators whose data is **not** derived from the chart's
 * OHLCV: open interest, cumulative volume delta, PCR, an external analytics
 * feed. Where a Tier-1 descriptor is a pure `calc(bars, settings)`, a Tier-2
 * descriptor owns a fetch / subscribe / merge lifecycle and its own series.
 *
 * `createTier2Indicator` wraps that lifecycle into an ordinary
 * `IndicatorDescriptor`, so the chart runtime, the settings model, panes,
 * levels, and removal all work identically — there is no second runtime.
 *
 * The alignment rule is deliberate and worth knowing: external points carry
 * their own timestamps, which rarely match bar times. Each bar takes the most
 * recent external point **at or before** that bar's time (last-known-value,
 * never interpolated and never forward-looking), and bars before the first
 * point are `null`.
 */
import type {
  Bar,
  IndicatorDescriptor,
  IndicatorPlot,
  IndicatorInput,
  IndicatorLevel,
  IndicatorSettings,
  IndicatorValues,
} from 'openalgo-charts';

/** One external observation: a timestamp plus a value per plot key. */
export interface Tier2Point {
  /** UTC seconds. */
  time: number;
  values: Readonly<Record<string, number | null>>;
}

export interface Tier2Context {
  settings: Readonly<IndicatorSettings>;
  /** The chart's current source bars — use for the requested time window. */
  bars: readonly Bar[];
  /** UTC seconds of the first and last source bar (0 when there are none). */
  from: number;
  to: number;
}

export interface Tier2Descriptor {
  id: string;
  name: string;
  category?: string;
  placement: 'onchart' | 'pane';
  inputs: readonly IndicatorInput[];
  plots: readonly IndicatorPlot[];
  /** Load the series for the current window. */
  fetch(ctx: Tier2Context): Promise<readonly Tier2Point[]>;
  /**
   * Optional live subscription. Call `push` with each incoming point; return an
   * unsubscribe function.
   */
  subscribe?(ctx: Tier2Context, push: (point: Tier2Point) => void): () => void;
  /**
   * Settings keys that invalidate the fetched data when they change (symbol,
   * exchange, resolution). Changing anything else only re-runs alignment.
   */
  refetchOn?: readonly string[];
  levels?(settings: Readonly<IndicatorSettings>): readonly IndicatorLevel[];
  range?(settings: Readonly<IndicatorSettings>): { min: number; max: number } | null;
}

interface Tier2State {
  key: string;
  points: Tier2Point[];
  loading: boolean;
  unsubscribe: (() => void) | null;
  /** Set once the instance is torn down, so a late fetch is ignored. */
  dead: boolean;
}

const STATE = '__tier2';

const stateOf = (store: Record<string, unknown>): Tier2State | undefined =>
  store[STATE] as Tier2State | undefined;

/** Cache key from the settings that invalidate data. */
function cacheKey(d: Tier2Descriptor, settings: Readonly<IndicatorSettings>): string {
  const keys = d.refetchOn ?? [];
  return keys.map((k) => `${k}=${String(settings[k])}`).join('&');
}

/** Upsert a point by time, keeping the series time-sorted. */
function upsert(points: Tier2Point[], point: Tier2Point): void {
  const last = points[points.length - 1];
  if (last === undefined || point.time > last.time) { points.push(point); return; }
  if (point.time === last.time) { points[points.length - 1] = point; return; }
  let lo = 0;
  let hi = points.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid].time < point.time) lo = mid + 1;
    else hi = mid;
  }
  if (points[lo]?.time === point.time) points[lo] = point;
  else points.splice(lo, 0, point);
}

/**
 * Project time-stamped external points onto the bar timeline: each bar reads
 * the latest point at or before it. Both arrays are time-sorted, so this is a
 * single linear merge, not a per-bar search.
 */
function align(
  bars: readonly Bar[],
  points: readonly Tier2Point[],
  plots: readonly IndicatorPlot[],
): IndicatorValues {
  const out: Record<string, (number | null)[]> = {};
  for (const plot of plots) out[plot.key] = new Array<number | null>(bars.length).fill(null);
  if (points.length === 0) return out;
  let p = -1;
  for (let i = 0; i < bars.length; i++) {
    while (p + 1 < points.length && points[p + 1].time <= bars[i].time) p += 1;
    if (p < 0) continue;
    const values = points[p].values;
    for (const plot of plots) {
      const v = values[plot.key];
      out[plot.key][i] = typeof v === 'number' && Number.isFinite(v) ? v : null;
    }
  }
  return out;
}

/**
 * Wrap a Tier-2 descriptor as a normal `IndicatorDescriptor`.
 *
 * ```ts
 * export const OPEN_INTEREST = createTier2Indicator({
 *   id: 'open-interest', name: 'Open Interest', placement: 'pane',
 *   inputs: [{ key: 'symbol', type: 'text', label: 'Symbol', default: '' }],
 *   plots: [{ key: 'oi', type: 'line', title: 'OI' }],
 *   refetchOn: ['symbol'],
 *   fetch: async ({ settings, from, to }) => loadOi(settings.symbol, from, to),
 * });
 * registerIndicator(OPEN_INTEREST);
 * ```
 */
export function createTier2Indicator(d: Tier2Descriptor): IndicatorDescriptor {
  return {
    id: d.id,
    name: d.name,
    category: d.category,
    placement: d.placement,
    inputs: d.inputs,
    plots: d.plots,
    levels: d.levels,
    range: d.range,

    calc: (bars, _settings, store) => {
      const state = stateOf(store);
      return align(bars, state?.points ?? [], d.plots);
    },

    attach: (ctx) => {
      // The store survives a settings change (attach is re-run), so reuse any
      // existing state: the cache key then decides whether a refetch is needed.
      const state: Tier2State =
        stateOf(ctx.store) ?? { key: '', points: [], loading: false, unsubscribe: null, dead: false };
      state.dead = false;
      ctx.store[STATE] = state;

      const context = (): Tier2Context => {
        const bars = ctx.bars();
        return {
          settings: ctx.settings(),
          bars,
          from: bars.length > 0 ? bars[0].time : 0,
          to: bars.length > 0 ? bars[bars.length - 1].time : 0,
        };
      };

      const onPoint = (point: Tier2Point): void => {
        if (state.dead) return;
        upsert(state.points, point);
        ctx.requestRecompute();
      };

      const load = (): void => {
        const c = context();
        const key = cacheKey(d, c.settings);
        // Same data-affecting settings and data already in hand: nothing to do.
        if (state.loading || (key === state.key && state.points.length > 0)) {
          if (state.unsubscribe === null && d.subscribe !== undefined) {
            state.unsubscribe = d.subscribe(c, onPoint);
          }
          return;
        }
        state.loading = true;
        state.key = key;
        void d.fetch(c).then(
          (points) => {
            state.loading = false;
            if (state.dead || state.key !== key) return; // settings moved on
            state.points = points.slice().sort((a, b) => a.time - b.time);
            ctx.requestRecompute();
          },
          () => {
            state.loading = false;
            // A failed fetch leaves the previous points on screen rather than
            // blanking the pane; the next settings change retries.
            state.key = '';
          },
        );

        state.unsubscribe?.();
        state.unsubscribe = d.subscribe?.(c, onPoint) ?? null;
      };

      load();

      return () => {
        state.dead = true;
        state.unsubscribe?.();
        state.unsubscribe = null;
      };
    },
  };
}
