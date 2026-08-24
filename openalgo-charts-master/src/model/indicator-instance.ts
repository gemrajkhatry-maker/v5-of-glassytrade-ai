/**
 * Indicator runtime (ARCHITECTURE.md §8). Turns an `IndicatorDescriptor` into
 * live chart objects: one series per plot, optional reference levels, an
 * optional fixed pane range — and recomputes them when the source data or the
 * settings change.
 *
 * It adds **no rendering code**. Every plot names a registered chart type, so
 * indicators draw through the same Family-A renderers as any other series.
 */
import type { Bar } from './bar';
import type { SeriesApi } from './series';
import type { PriceLine } from '../primitives/price-line';
import type { PaneLegend, LegendValue } from '../primitives/pane-legend';
import type { SeriesMarkers } from '../primitives/markers';
import type { ChartTable } from '../primitives/table';
import type { IndicatorFillSpec, IndicatorPlot } from './indicator-registry';
import { IndicatorFill as IndicatorFillPrimitive } from '../primitives/indicator-fill';

import { withAlpha } from '../render/pill';
import { DEFAULT_TIMEZONE } from '../feed/time';
import {
  indicatorDefaults,
  indicatorStyleInputs,
  plotStyleKeys,
  type IndicatorDescriptor,
  type IndicatorSettings,
  type IndicatorStore,
  type IndicatorValues,
} from './indicator-registry';

const num = (v: unknown, fallback: number): number =>
  (typeof v === 'number' && Number.isFinite(v) ? v : fallback);

/** Defaults for the generated per-plot appearance settings. */
function styleDefaults(descriptor: IndicatorDescriptor): IndicatorSettings {
  const out: IndicatorSettings = {};
  for (const input of indicatorStyleInputs(descriptor)) out[input.key] = input.default;
  return out;
}

/** Legend numbers: enough precision to be useful, never a 17-digit float. */
function formatValue(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toPrecision(3);
}

/** The slice of the chart the runtime needs. Keeps this module testable alone. */
export interface IndicatorHost {
  /** Add the pane-legend row (name + inline up/down/hide/maximize/close). */
  addIndicatorLegend(opts: {
    id: string; title: string; params: string; color?: string; row: number; paneIndex: number;
  }): PaneLegend;
  removeIndicatorLegend(legend: PaneLegend): void;
  /** How many legends already sit on this pane, so rows stack. */
  legendRowsOn(paneIndex: number): number;
  addIndicatorSeries(
    type: string,
    paneIndex: number,
    style: Record<string, unknown> | undefined,
    priceScaleId: string | undefined,
  ): SeriesApi;
  addIndicatorLevel(
    price: number,
    color: string,
    dashed: boolean,
    label: string,
    id: string,
    paneIndex: number,
  ): PriceLine;
  removeIndicatorLevel(line: PriceLine): void;
  /** Attach a band drawn behind the plots (an Ichimoku cloud). */
  addIndicatorFill(fill: IndicatorFillPrimitive, paneIndex: number): void;
  removeIndicatorFill(fill: IndicatorFillPrimitive): void;
  /**
   * Detach a signal-marker layer. There is no matching `add`: the layer comes
   * from `series.createMarkers()` on a plot's own series, so it already lands in
   * the right pane. Removing a series does not remove its primitives, hence this.
   */
  removeIndicatorMarkers(markers: SeriesMarkers): void;
  /** Attach a corner-pinned summary grid to a pane, and detach it again. */
  addIndicatorTable(paneIndex: number): ChartTable;
  removeIndicatorTable(table: ChartTable): void;
  /** Bars of the primary price series — the calculation input. */
  sourceBars(): readonly Bar[];
  /** Index of a fresh pane for an indicator that wants its own. */
  nextPaneIndex(): number;
  /**
   * The chart's configured IANA zone. Optional so a host predating the option
   * still satisfies this interface; absent means the shipped default.
   *
   * A descriptor is handed bars and settings and never the chart, so this is
   * how the calendar an anchor resets on (a VWAP session, a seasonality month)
   * reaches the calculation. See `IndicatorInstance._descriptorSettings`.
   */
  timezone?(): string;
  /** Pin a pane's price scale to a fixed range, or release it with `null`. */
  setPaneRange(paneIndex: number, range: { min: number; max: number } | null): void;
}

/** Public handle returned by `chart.addIndicator(...)`. */
export interface IndicatorApi {
  /** Unique instance id (several instances of one indicator can coexist). */
  readonly id: string;
  /** The descriptor id, e.g. `'macd'`. */
  readonly indicatorId: string;
  /** Display name. */
  readonly name: string;
  /** Pane the indicator drew into. */
  readonly paneIndex: number;
  /** Current settings (a copy). */
  settings(): IndicatorSettings;
  /** Merge a settings patch, recompute, and restyle. */
  setSettings(patch: Readonly<IndicatorSettings>): void;
  /** The series backing one plot key, for direct styling. */
  series(plotKey: string): SeriesApi | undefined;
  /** Latest computed values (a reference — do not mutate). */
  values(): IndicatorValues;
  /** Whether the plots are drawn (the legend's eye toggle). */
  visible(): boolean;
  /** Show or hide every plot without removing the instance. */
  setVisible(on: boolean): void;
  /** This indicator's legend row, or null if it has none. */
  legend(): PaneLegend | null;
  /** Refresh the legend readings for a bar index; omit for the latest bar. */
  updateLegendValues(index?: number): void;
  /** Remove every series, level, and legend row this indicator created. */
  remove(): void;
}

let nextInstance = 1;

export class IndicatorInstance implements IndicatorApi {
  public readonly id: string;
  public readonly indicatorId: string;
  public readonly name: string;
  /** Mutable: the chart re-indexes this when panes are moved or removed. */
  public paneIndex: number;

  private readonly _host: IndicatorHost;
  private readonly _d: IndicatorDescriptor;
  private readonly _ownPane: boolean;
  private _settings: IndicatorSettings;
  /** Memo for `_descriptorSettings`, keyed on the zone and the settings identity. */
  private _zoned: { zone: string; base: IndicatorSettings; merged: IndicatorSettings } | null = null;
  private readonly _series = new Map<string, SeriesApi>();
  /** The chart type each plot is currently drawn as (settings can override). */
  private readonly _plotTypes = new Map<string, string>();
  /** One band per declared fill, in descriptor order. */
  private readonly _fills: IndicatorFillPrimitive[] = [];
  private _levels: PriceLine[] = [];
  private _values: IndicatorValues = {};
  private _barCount = 0;
  private _removed = false;
  private readonly _store: IndicatorStore = {};
  private _detach: (() => void) | null = null;
  private _legend: PaneLegend | null = null;
  private _markers: SeriesMarkers | null = null;
  private _table: ChartTable | null = null;
  private _visible = true;

  public constructor(
    host: IndicatorHost,
    descriptor: IndicatorDescriptor,
    settings: Readonly<IndicatorSettings> = {},
    paneIndex?: number,
  ) {
    this._host = host;
    this._d = descriptor;
    this.indicatorId = descriptor.id;
    this.name = descriptor.name;
    this.id = `${descriptor.id}-${nextInstance++}`;
    // Declared inputs plus the generated per-plot appearance settings, so every
    // indicator supports colour / opacity / thickness / line style with no
    // per-descriptor boilerplate.
    this._settings = {
      ...indicatorDefaults(descriptor),
      ...styleDefaults(descriptor),
      ...settings,
    };

    if (paneIndex !== undefined) {
      this.paneIndex = paneIndex;
      this._ownPane = false;
    } else if (descriptor.placement === 'onchart') {
      this.paneIndex = 0;
      this._ownPane = false;
    } else {
      this.paneIndex = host.nextPaneIndex();
      this._ownPane = true;
    }

    for (const plot of descriptor.plots) {
      const type = this._plotType(plot);
      this._plotTypes.set(plot.key, type);
      this._series.set(
        plot.key,
        host.addIndicatorSeries(type, this.paneIndex, this._plotStyle(plot), plot.priceScaleId),
      );
    }

    for (const fill of descriptor.fills ?? []) {
      const band = new IndicatorFillPrimitive({
        colorUp: this._fillColor(fill, true),
        colorDown: this._fillColor(fill, false),
        opacity: fill.opacity ?? 0.12,
      });
      this._fills.push(band);
      host.addIndicatorFill(band, this.paneIndex);
    }

    this._legend = host.addIndicatorLegend({
      id: `indicator:${this.id}`,
      title: descriptor.name,
      params: this._paramSummary(),
      color: this._legendColor(),
      row: host.legendRowsOn(this.paneIndex),
      paneIndex: this.paneIndex,
    });

    this._applyLevels();
    this._applyRange();
    this.recompute();
    this._attach();
  }

  /**
   * The numeric/select inputs as a compact string (`14 close`), the way a
   * charting legend abbreviates an indicator's configuration. Colors are
   * excluded — the swatch already carries that. Booleans are excluded for the
   * same reason in reverse: a bare `true true true` names nothing, and what a
   * visibility toggle did is already visible on the chart.
   */
  private _paramSummary(): string {
    const out: string[] = [];
    for (const input of this._d.inputs) {
      if (input.type === 'color' || input.type === 'boolean') continue;
      const v = this._settings[input.key];
      if (v === undefined || v === null || v === '') continue;
      out.push(String(v));
    }
    return out.join(' ');
  }

  /** First settings-driven plot color, for the legend swatch. */
  private _legendColor(): string | undefined {
    for (const plot of this._d.plots) {
      const key = plot.colorKey;
      if (key !== undefined && typeof this._settings[key] === 'string') return this._settings[key] as string;
      if (typeof plot.style?.color === 'string') return plot.style.color;
    }
    return undefined;
  }

  /** Whether the indicator's plots are drawn. */
  public visible(): boolean {
    return this._visible;
  }

  /** Show or hide every plot without removing the instance (the eye button). */
  public setVisible(on: boolean): void {
    if (on === this._visible) return;
    this._visible = on;
    for (const series of this._series.values()) series.applyOptions({ visible: on });
    for (const band of this._fills) band.setVisible(on);
    // Markers are a separate primitive, so hiding the plots does not hide them;
    // re-running the sync clears the layer (or repopulates it) explicitly.
    this._syncMarkers(this._host.sourceBars());
    this._syncTable(this._host.sourceBars());
    this._legend?.setOptions({ hidden: !on });
  }

  /** The chart calls this when panes are reordered or one is removed. */
  public shiftPane(delta: number): void {
    this.paneIndex += delta;
  }

  /** The legend row, for the host to add pane-level actions to the first one. */
  public legend(): PaneLegend | null {
    return this._legend;
  }

  /**
   * Show one reading per plot on the legend row, each in its plot's own color —
   * a multi-plot source (an MA ribbon, MACD) is unreadable as a single number.
   * `index` is the crosshair's bar; omit it for the latest bar.
   */
  public updateLegendValues(index?: number): void {
    if (this._legend === null) return;
    const n = this._barCount;
    const i = index === undefined || index < 0 || index >= n ? n - 1 : index;
    if (i < 0) { this._legend.setValues([]); return; }
    const out: LegendValue[] = [];
    for (const plot of this._d.plots) {
      const v = this._values[plot.key]?.[i];
      if (v === null || v === undefined || !Number.isFinite(v)) continue;
      out.push({ text: formatValue(v), color: this._plotColor(plot) });
    }
    this._legend.setValues(out);
  }

  /** A band's colour: its settings key if it has one, else the declared value. */
  private _fillColor(fill: IndicatorFillSpec, up: boolean): string {
    const key = up ? fill.colorUpKey : fill.colorDownKey;
    const fromSettings = key !== undefined ? this._settings[key] : undefined;
    if (typeof fromSettings === 'string') return fromSettings;
    const declared = up ? fill.colorUp : fill.colorDown;
    return declared ?? (up ? '#26a69a' : '#ef5350');
  }

  /** Feed each band the two plots it spans, on the shared logical index. */
  private _syncFills(): void {
    const fills = this._d.fills ?? [];
    for (let i = 0; i < fills.length; i++) {
      const band = this._fills[i];
      if (band === undefined) continue;
      const spec = fills[i];
      const a = this._values[spec.between[0]];
      const b = this._values[spec.between[1]];
      band.setOptions({
        colorUp: this._fillColor(spec, true),
        colorDown: this._fillColor(spec, false),
        opacity: spec.opacity ?? 0.12,
      });
      if (a === undefined || b === undefined) { band.setPoints([]); continue; }
      const pts = [];
      for (let j = 0; j < this._barCount; j++) {
        pts.push({ index: j, a: a[j] ?? null, b: b[j] ?? null });
      }
      band.setPoints(pts);
    }
  }

  /**
   * Refresh the descriptor's signal markers. The layer is created lazily on the
   * first plot's series — so it shares the indicator's pane and price scale —
   * and is only created once the descriptor actually returns a marker, which
   * keeps the common no-marker indicator free of an extra primitive.
   */
  private _syncMarkers(bars: readonly Bar[]): void {
    if (this._d.markers === undefined) return;
    const markers = this._visible
      ? this._d.markers({ bars, values: this._values, settings: this._descriptorSettings() })
      : [];
    if (this._markers === null) {
      if (markers.length === 0) return;
      const first = this._series.get(this._d.plots[0]?.key ?? '');
      if (first === undefined) return;
      this._markers = first.createMarkers();
    }
    this._markers.setMarkers(markers);
  }

  /**
   * Refresh the descriptor's summary grid, created lazily on first use so an
   * indicator without the hook never costs an extra primitive.
   */
  private _syncTable(bars: readonly Bar[]): void {
    if (this._d.table === undefined) return;
    const spec = this._visible
      ? this._d.table({ bars, values: this._values, settings: this._descriptorSettings() })
      : null;
    const rows = spec?.rows ?? [];
    if (this._table === null) {
      if (rows.length === 0) return;
      this._table = this._host.addIndicatorTable(this.paneIndex);
    }
    if (spec?.options !== undefined) this._table.setOptions(spec.options);
    this._table.setRows(rows);
  }

  /** The chart type to draw a plot as: the settings override, else declared. */
  private _plotType(plot: IndicatorPlot): string {
    const v = this._settings[plotStyleKeys(plot).type];
    return typeof v === 'string' && v !== '' ? v : plot.type;
  }

  private _plotColor(plot: IndicatorPlot): string | undefined {
    const v = this._settings[plotStyleKeys(plot).color];
    if (typeof v === 'string') return v;
    return typeof plot.style?.color === 'string' ? plot.style.color : undefined;
  }

  /**
   * The series style for a plot: its declared defaults, then the legacy
   * `colorKey`, then the generated appearance settings. Opacity folds into the
   * colour as an alpha, since a canvas stroke has no separate opacity channel.
   */
  private _plotStyle(plot: IndicatorPlot): Record<string, unknown> {
    const k = plotStyleKeys(plot);
    const style: Record<string, unknown> = { ...(plot.style ?? {}), title: plot.title };
    const color = this._plotColor(plot);
    const opacity = num(this._settings[k.opacity], 100);
    if (color !== undefined) style.color = opacity >= 100 ? color : withAlpha(color, opacity / 100);
    const width = this._settings[k.width];
    if (typeof width === 'number' && width > 0) style.lineWidth = width;
    const lineStyle = this._settings[k.lineStyle];
    if (typeof lineStyle === 'string') style.lineStyle = lineStyle;
    return style;
  }

  /**
   * Run the descriptor's optional lifecycle (Tier-2 fetch / subscribe). Re-run
   * on every settings change so an indicator whose data depends on a setting
   * can reload; `_store` persists across the cycle, so a descriptor that caches
   * there can no-op when nothing data-affecting actually changed.
   */
  private _attach(): void {
    const detach = this._d.attach?.({
      settings: () => this._descriptorSettings(),
      bars: () => this._host.sourceBars(),
      requestRecompute: () => {
        if (this._removed) return;
        this._barCount = 0; // external data invalidates any calcTail state
        this.recompute();
      },
      store: this._store,
    });
    this._detach = typeof detach === 'function' ? detach : null;
  }

  public settings(): IndicatorSettings {
    return { ...this._settings };
  }

  /**
   * Settings as a *descriptor* sees them: the chart's zone rides along under
   * the reserved `timezone` key, because a `calc` is handed settings and never
   * the chart.
   *
   * It is deliberately not folded into `_settings`. That object is the user's
   * own values, it is what `settings()` returns and what `getState()` persists,
   * and baking the zone into it would mean a layout saved on a New York chart
   * kept computing on New York after being restored onto an IST one, silently
   * out of step with the axis beside it.
   *
   * The default zone returns `_settings` untouched, so every existing caller
   * allocates nothing and computes exactly what it computed before.
   */
  private _descriptorSettings(): Readonly<IndicatorSettings> {
    const zone = this._host.timezone?.() ?? DEFAULT_TIMEZONE;
    if (zone === DEFAULT_TIMEZONE) return this._settings;
    const cached = this._zoned;
    // `_settings` is replaced wholesale by `setSettings`, so identity is a
    // sufficient staleness check and costs one compare per recompute.
    if (cached !== null && cached.zone === zone && cached.base === this._settings) return cached.merged;
    const merged = { ...this._settings, timezone: zone };
    this._zoned = { zone, base: this._settings, merged };
    return merged;
  }

  public series(plotKey: string): SeriesApi | undefined {
    return this._series.get(plotKey);
  }

  public values(): IndicatorValues {
    return this._values;
  }

  public setSettings(patch: Readonly<IndicatorSettings>): void {
    if (this._removed) return;
    this._settings = { ...this._settings, ...patch };
    // Restyle before recomputing — appearance is independent of the maths, so a
    // colour or thickness change must not wait on a full recalculation.
    for (const plot of this._d.plots) {
      // A plot's chart type belongs to the series, not its style bag, so
      // switching it means building a new series rather than restyling.
      const wanted = this._plotType(plot);
      if (wanted !== this._plotTypes.get(plot.key)) {
        this._series.get(plot.key)?.remove();
        this._series.set(
          plot.key,
          this._host.addIndicatorSeries(wanted, this.paneIndex, this._plotStyle(plot), plot.priceScaleId),
        );
        this._plotTypes.set(plot.key, wanted);
        continue;
      }
      this._series.get(plot.key)?.applyOptions(this._plotStyle(plot) as never);
    }
    this._legend?.setOptions({ params: this._paramSummary(), color: this._legendColor() });
    this._applyLevels();
    this._applyRange();
    this._values = {};
    this._barCount = 0; // force a full recompute; settings invalidate any tail state
    this.recompute();
    this._detach?.();
    this._attach();
  }

  /**
   * Recompute from the host's source bars. Uses the descriptor's `calcTail`
   * when only the tail moved (a live tick) and it declares one; otherwise a
   * full `calc`.
   */
  public recompute(): void {
    if (this._removed) return;
    const bars = this._host.sourceBars();
    const n = bars.length;
    // Resolved once: the zone is fixed for the frame, and calc, calcTail and
    // every colorBy below must be told the same calendar.
    const settings = this._descriptorSettings();

    let values: IndicatorValues | null = null;
    const tailOnly = n > 0 && this._barCount > 0 && (n === this._barCount || n === this._barCount + 1);
    if (tailOnly && this._d.calcTail !== undefined) {
      const from = this._barCount - 1; // the previously-last bar may have been replaced
      const tail = this._d.calcTail(bars, settings, from, this._values, this._store);
      if (tail !== null) values = spliceTail(this._values, tail, from, n);
    }
    if (values === null) values = this._d.calc(bars, settings, this._store);

    this._values = values;
    this._barCount = n;

    for (const plot of this._d.plots) {
      const series = this._series.get(plot.key);
      if (series === undefined) continue;
      const col = values[plot.key];
      if (col === undefined) {
        series.setData([]);
        continue;
      }
      const out = new Array<{ time: number; value: number; color?: string }>(n);
      const colorBy = plot.colorBy;
      for (let i = 0; i < n; i++) {
        const v = col[i];
        const value = v === null || v === undefined ? NaN : v;
        const point: { time: number; value: number; color?: string } = { time: bars[i].time, value };
        if (colorBy !== undefined && Number.isFinite(value)) {
          const c = colorBy({ value, index: i, values, settings });
          if (c !== undefined) point.color = c;
        }
        out[i] = point;
      }
      series.setData(out);
    }
    this._syncFills();
    this._syncMarkers(bars);
    this._syncTable(bars);
    this.updateLegendValues();
  }

  private _applyLevels(): void {
    for (const line of this._levels) this._host.removeIndicatorLevel(line);
    this._levels = [];
    const levels = this._d.levels?.(this._descriptorSettings()) ?? [];
    let i = 0;
    for (const l of levels) {
      this._levels.push(
        this._host.addIndicatorLevel(
          l.price,
          l.color ?? '#8892a6',
          l.dashed ?? true,
          l.title ?? '',
          `${this.id}:level:${i++}`,
          this.paneIndex,
        ),
      );
    }
  }

  private _applyRange(): void {
    if (!this._ownPane) return; // a shared pane belongs to whoever created it
    this._host.setPaneRange(this.paneIndex, this._d.range?.(this._descriptorSettings()) ?? null);
  }

  public remove(): void {
    if (this._removed) return;
    this._removed = true;
    this._detach?.();
    this._detach = null;
    if (this._legend !== null) { this._host.removeIndicatorLegend(this._legend); this._legend = null; }
    for (const line of this._levels) this._host.removeIndicatorLevel(line);
    this._levels = [];
    for (const series of this._series.values()) series.remove();
    this._series.clear();
    for (const band of this._fills) this._host.removeIndicatorFill(band);
    this._fills.length = 0;
    if (this._markers !== null) { this._host.removeIndicatorMarkers(this._markers); this._markers = null; }
    if (this._table !== null) { this._host.removeIndicatorTable(this._table); this._table = null; }
    if (this._ownPane) this._host.setPaneRange(this.paneIndex, null);
  }
}

/**
 * Overlay a `calcTail` result (values for `[from, n)`) onto the previous full
 * result. Any key the tail omits, or a previous column of the wrong length,
 * forces the caller back to a full recompute by returning `null`.
 */
function spliceTail(
  previous: IndicatorValues,
  tail: IndicatorValues,
  from: number,
  n: number,
): IndicatorValues | null {
  const out: Record<string, (number | null)[]> = {};
  for (const key of Object.keys(tail)) {
    const prev = previous[key];
    const add = tail[key];
    if (prev === undefined || add === undefined) return null;
    if (add.length !== n - from) return null;
    const col = new Array<number | null>(n);
    for (let i = 0; i < from; i++) col[i] = prev[i] ?? null;
    for (let i = from; i < n; i++) col[i] = add[i - from] ?? null;
    out[key] = col;
  }
  return out;
}
