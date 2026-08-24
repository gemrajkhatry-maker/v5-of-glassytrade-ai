/**
 * Multi-symbol comparison: put a second instrument on the primary one's pane
 * and read them together (NIFTY against BANKNIFTY, a stock against its index).
 *
 * Headless, in the spirit of `DrawingController` (src/draw/controller.ts) and
 * `ReplayController`: it owns the series, the alignment and the scales, and
 * ships no DOM, so the host draws its own symbol chips and legend rows from
 * `list()`.
 *
 * Three decisions carry the design:
 *
 * 1. **The comparison never touches the primary's axis.** It goes on the pane's
 *    hidden overlay scale (`priceScaleId: ''`, see `Pane._scaleFor`), which
 *    autoscales on its own and draws no ticks, so a 46,000 instrument next to a
 *    22,000 one cannot compress the primary's candles or relabel its ladder.
 *
 * 2. **Comparability comes from the scale, not from the data.** The bars handed
 *    over are stored as the instrument's own prices, so the legend, the
 *    crosshair and any live update still speak in real prices. What makes the
 *    lines readable together is the pane mode: `percentage` and
 *    `indexed-to-100` give every scale its own baseline (the first *visible*
 *    bar, so panning re-bases), and `_mirror` then gives the overlay the same
 *    band of percent the primary's axis is showing. Without that mirror each
 *    scale would autoscale to its own data and a 1% mover would look exactly
 *    like a 10% mover, both filling the pane.
 *
 * 3. **Alignment is by timestamp** and lives in `./align`, which documents what
 *    happens in each direction of mismatch.
 *
 * Known limit: a pane has exactly *one* hidden overlay scale, so every
 * comparison on a pane shares one baseline. That is exactly right for one
 * comparison, which is the common case, and it is why a second comparison in
 * the same pane is quoted against the first instrument's price. Keyed overlay
 * scales in `Pane` are the fix; until then, put further instruments on their
 * own pane with `paneIndex`.
 */
import type { PriceScale, PriceScaleMode } from '../scale/price-scale';
import type { PriceScaleId, SeriesApi } from '../model/series';
import type { SeriesType } from '../model/chart-type-registry';
import type { SeriesStyle } from '../render/series-style';
import type { Bar, SeriesDataItem } from '../model/bar';
import type { IPrimitive } from '../primitives/primitive';
import type { AddSeriesOptions } from '../core/chart';
import { alignToPrimary, EMPTY_ALIGNMENT, type ComparisonAlignment } from './align';

/**
 * How the pane quotes prices while a comparison is on it. The two rebasing
 * modes are the reason the lines are comparable at all; `none` leaves the
 * pane's own mode alone, for a host that wants the raw overlay.
 */
export type ComparisonMode = 'percentage' | 'indexed-to-100' | 'none';

export interface ComparisonOptions {
  /** Instrument label, e.g. 'BANKNIFTY'. Carried on the handle for the host's UI. */
  symbol: string;
  /** The instrument's own bars. Aligned to the primary series, see `./align`. */
  bars: readonly SeriesDataItem[];
  /** Line colour shorthand; `style.color` wins if both are given. */
  color?: string;
  /** Style overrides merged onto the chart type's defaults. */
  style?: SeriesStyle;
  /** Renderer for the comparison. Default 'line'. */
  type?: SeriesType;
  /** Pane to draw on. Default 0, the price pane. */
  paneIndex?: number;
}

export interface ComparisonControllerOptions {
  /** Pane mode applied while any comparison is on it. Default 'percentage'. */
  mode?: ComparisonMode;
}

/** What `addComparison` hands back: one instrument on the chart. */
export interface ComparisonHandle {
  readonly symbol: string;
  /**
   * The series this comparison draws through, for style patches and markers.
   * Data set on it directly skips alignment (use `setBars`), and removing it
   * directly leaves the pane rebased with nothing on it (use `remove`).
   */
  readonly series: SeriesApi;
  readonly paneIndex: number;
  /** The hidden scale it maps to. Never the pane's own price axis. */
  priceScale(): PriceScale;
  /** How the last alignment against the primary's bars went. */
  alignment(): ComparisonAlignment;
  /** Replace the instrument's bars (a longer history, a refreshed fetch). */
  setBars(bars: readonly SeriesDataItem[]): void;
  /** Take this instrument off the chart. Safe to call twice. */
  remove(): void;
  /** Every comparison on this chart, in the order they were added. */
  list(): readonly ComparisonHandle[];
}

/**
 * The slice of a pane the controller reads. Declared structurally, like
 * `ReplayViewport`, so nothing here depends on `Pane` beyond the two members
 * that decide where a comparison can go.
 */
export interface ComparisonPane {
  readonly priceScale: PriceScale;
  series(): readonly { readonly scaleId: string }[];
}

/**
 * The slice of the chart this controller needs. `Chart` satisfies it; declaring
 * it structurally keeps the controller testable against a stub.
 */
export interface ComparisonChartHost {
  addSeries(type: SeriesType, options: AddSeriesOptions): SeriesApi;
  panes(): readonly ComparisonPane[];
  addPrimitive(primitive: IPrimitive, paneIndex?: number): void;
  removePrimitive(primitive: IPrimitive): void;
  primarySeries(): SeriesApi | null;
  /** Only `length` is read: it changes exactly when the shared time axis does. */
  readonly dataLayer: { readonly length: number };
}

/** Per-pane state: the scale the comparisons share and the mode we swapped in. */
interface PaneEntry {
  readonly paneIndex: number;
  readonly scaleId: PriceScaleId;
  readonly scale: PriceScale;
  /** The pane's own price axis. Read to mirror it, never written. */
  readonly primary: PriceScale;
  readonly savedPrimaryMode: PriceScaleMode;
  readonly savedScaleMode: PriceScaleMode;
  /** The mode we put in force, or null if we left the pane alone. */
  applied: PriceScaleMode | null;
  readonly sync: IPrimitive;
  count: number;
}

interface ItemState {
  readonly series: SeriesApi;
  readonly entry: PaneEntry;
  bars: readonly SeriesDataItem[];
  alignment: ComparisonAlignment;
  removed: boolean;
}

export class ComparisonController {
  private readonly _chart: ComparisonChartHost;
  private _mode: ComparisonMode;
  private readonly _panes = new Map<number, PaneEntry>();
  /** Insertion-ordered, and the handle is the key so `remove` is a lookup. */
  private readonly _items = new Map<ComparisonHandle, ItemState>();
  /**
   * `dataLayer.length` as of the last alignment. Alignment depends only on the
   * primary's set of *times*, and that set is what the length counts, so this
   * is an O(1) staleness check for a per-frame hook (see `sync`).
   */
  private _alignedAt = -1;
  /** Guards `realign` against re-entry through its own `setData` repaint. */
  private _realigning = false;

  public constructor(chart: ComparisonChartHost, options: ComparisonControllerOptions = {}) {
    this._chart = chart;
    this._mode = options.mode ?? 'percentage';
  }

  // ── public API ──────────────────────────────────────────────────────────

  /** Put an instrument on the chart alongside the primary series. */
  public add(options: ComparisonOptions): ComparisonHandle {
    if (this._chart.primarySeries() === null) {
      throw new Error('openalgo-charts: a comparison needs a primary series to align against');
    }
    const paneIndex = options.paneIndex ?? 0;
    const style: SeriesStyle = { ...options.style };
    if (style.color === undefined && options.color !== undefined) style.color = options.color;
    const existing = this._panes.get(paneIndex);
    const scaleId = existing?.scaleId ?? this._scaleIdFor(paneIndex);
    const series = this._chart.addSeries(options.type ?? 'line', { paneIndex, style, priceScaleId: scaleId });
    const entry = existing ?? this._openPane(paneIndex, scaleId, series.priceScale());
    entry.count++;

    const state: ItemState = {
      series, entry, bars: options.bars, alignment: EMPTY_ALIGNMENT, removed: false,
    };
    const handle: ComparisonHandle = {
      symbol: options.symbol,
      series,
      paneIndex,
      priceScale: () => entry.scale,
      alignment: () => state.alignment,
      setBars: (bars: readonly SeriesDataItem[]): void => {
        state.bars = bars;
        if (!state.removed) this._align(state, this._primaryBars());
      },
      remove: (): void => { this.remove(handle); },
      list: () => this.list(),
    };
    this._items.set(handle, state);
    this._align(state, this._primaryBars());
    this._alignedAt = this._chart.dataLayer.length;
    return handle;
  }

  /** Take one instrument off. Returns false if it was already gone. */
  public remove(handle: ComparisonHandle): boolean {
    const state = this._items.get(handle);
    if (state === undefined || state.removed) return false;
    state.removed = true;
    this._items.delete(handle);
    // The pane is put back first, then the series goes: dropping the series
    // raises a full repaint, and a host running frames synchronously would
    // otherwise paint one more time in a mode we were about to restore.
    const entry = state.entry;
    if (--entry.count <= 0) this._closePane(entry);
    state.series.remove();
    return true;
  }

  /** Every comparison on the chart, in the order they were added. */
  public list(): readonly ComparisonHandle[] {
    return Array.from(this._items.keys());
  }

  /** Take them all off, putting every pane back the way it was found. */
  public clear(): void {
    for (const handle of this.list()) this.remove(handle);
  }

  /**
   * Change the mode the panes are held in while comparisons are on them.
   * Panes that already have one switch immediately.
   */
  public setMode(mode: ComparisonMode): void {
    if (mode === this._mode) return;
    this._mode = mode;
    for (const entry of this._panes.values()) {
      this._restoreMode(entry);
      this._applyMode(entry);
    }
    this._repaint();
  }

  public get mode(): ComparisonMode {
    return this._mode;
  }

  /**
   * Re-project every instrument onto the primary's current bars. Called for
   * free when the shared time axis changes (see `sync`); a host only needs it
   * after replacing the primary's data with a *different* set of the same
   * length, which the length check cannot see.
   */
  public realign(): void {
    if (this._realigning) return;
    this._realigning = true;
    const bars = this._primaryBars();
    for (const state of this._items.values()) this._align(state, bars);
    // After the writes, not before: a comparison losing bars the primary no
    // longer has shortens the axis, and the length we want recorded is the one
    // the next frame will read.
    this._alignedAt = this._chart.dataLayer.length;
    this._realigning = false;
  }

  /**
   * Bring the overlay scales in line with the primary axis, re-aligning first
   * if the shared time axis has moved under us (a live bar, history paged in,
   * a replay step). Runs once per base paint through the per-pane hook.
   *
   * Re-aligning here writes series data mid-frame, which is safe because the
   * hook is a `bottom` primitive: it runs after the pane has autoscaled and
   * before any series is drawn, so the frame that notices the change is also
   * the frame that draws it. The repaint that write asks for lands on the next
   * frame, or re-enters this one on a host that runs frames synchronously,
   * which is what `realign`'s guard is for.
   */
  public sync(): void {
    if (this._chart.dataLayer.length !== this._alignedAt) this.realign();
    for (const entry of this._panes.values()) this._mirror(entry);
  }

  /** Remove every comparison and forget the chart. */
  public destroy(): void {
    this.clear();
    controllers.delete(this._chart);
  }

  // ── plumbing ────────────────────────────────────────────────────────────

  /**
   * Where a comparison can sit on a pane. The hidden overlay is the right
   * answer, but there is only one of it per pane and the volume histogram in
   * the price pane is usually already on it (that is what `priceScaleId: ''`
   * is best known for). Sharing it would autoscale price and volume together
   * and flatten both, so when it is taken the comparison goes to the left axis
   * instead: a visible second ladder is a far smaller surprise than an
   * invisible line at the bottom of the pane.
   */
  private _scaleIdFor(paneIndex: number): PriceScaleId {
    const pane = this._chart.panes()[paneIndex];
    if (pane === undefined) return '';
    return pane.series().some((s) => s.scaleId === '') ? 'left' : '';
  }

  private _openPane(paneIndex: number, scaleId: PriceScaleId, scale: PriceScale): PaneEntry {
    const primary = this._chart.panes()[paneIndex].priceScale;
    const entry: PaneEntry = {
      paneIndex,
      scaleId,
      scale,
      primary,
      savedPrimaryMode: primary.options.mode,
      savedScaleMode: scale.options.mode,
      applied: null,
      // A primitive that paints nothing, used purely as a frame hook.
      // `afterAutoscale` runs once every scale on the pane has been measured and
      // before anything is painted, which is the only window in which the
      // overlay's range can be corrected and still reach its own axis: the price
      // axes are drawn near the top of `paintBase`, well before primitives, so a
      // correction made in `draw` labelled the left ladder from the range of the
      // previous frame, and on a chart that had stopped repainting, never.
      sync: { zOrder: () => 'bottom', draw: (): void => {}, afterAutoscale: (): void => { this.sync(); } },
      count: 0,
    };
    this._panes.set(paneIndex, entry);
    this._applyMode(entry);
    this._chart.addPrimitive(entry.sync, paneIndex);
    return entry;
  }

  private _closePane(entry: PaneEntry): void {
    this._restoreMode(entry);
    this._chart.removePrimitive(entry.sync);
    this._panes.delete(entry.paneIndex);
  }

  private _applyMode(entry: PaneEntry): void {
    if (this._mode === 'none') return;
    entry.applied = this._mode;
    entry.primary.setOptions({ mode: this._mode });
    // The overlay is rebased too, or it would keep quoting absolute prices
    // under an axis that no longer does. `chart.setPriceScaleOptions` leaves
    // overlays out of a mode change for the opposite (and correct) reason: it
    // cannot tell a comparison from a volume histogram.
    entry.scale.setOptions({ mode: this._mode });
  }

  private _restoreMode(entry: PaneEntry): void {
    const applied = entry.applied;
    if (applied === null) return;
    entry.applied = null;
    // Only put back what is still ours: a user who switched the pane to log
    // while comparing keeps their choice instead of having it silently undone.
    if (entry.primary.options.mode === applied) entry.primary.setOptions({ mode: entry.savedPrimaryMode });
    if (entry.scale.options.mode === applied) entry.scale.setOptions({ mode: entry.savedScaleMode });
  }

  /**
   * Give the overlay the same band of percent the primary axis is showing, so
   * equal moves land on equal pixels and the divergence between two
   * instruments is the thing you see.
   *
   * Both scales rebase against a baseline of their own (the first visible bar
   * on each), and a rebase maps price to the ratio `price / baseline`. So the
   * two scales agree exactly when their ranges hold the same ratios, which is
   * one multiplication: the primary's range times `baseline_overlay /
   * baseline_primary`. It holds for `indexed-to-100` and `percentage` alike,
   * since they are one ladder a hundred points apart.
   *
   * A null baseline means this scale is not rebasing (linear, logarithmic, or
   * a pane with nothing visible on it yet). Then there is no shared ladder to
   * join and the overlay keeps its own autoscale, which is what mode 'none'
   * asks for: two instruments each filling the pane, comparable in shape only.
   *
   * The overlay stays under autoscale throughout, even though the range it
   * measures is overwritten here every frame. That measurement is one pass over
   * bars the renderer is about to walk anyway, and paying for it buys the
   * failure mode we want: a chart that stops calling `sync` falls back to an
   * independently scaled overlay instead of freezing on a stale range.
   */
  private _mirror(entry: PaneEntry): void {
    // Gate on the mode, not merely on a baseline being present. The two used
    // to be the same thing only by accident, and a baseline that outlived its
    // mode kept this mirroring a percentage ladder the user had switched off.
    if (entry.applied === null) return;
    const bp = entry.primary.baseline;
    const bc = entry.scale.baseline;
    if (bp === null || bc === null || !entry.primary.scaled) return;
    const k = bc / bp;
    const range = entry.primary.priceRange();
    entry.scale.setPriceRange({ min: range.min * k, max: range.max * k });
  }

  private _primaryBars(): readonly Bar[] {
    return this._chart.primarySeries()?.getData() ?? [];
  }

  private _align(state: ItemState, primary: readonly Bar[]): void {
    const result = alignToPrimary(primary, state.bars);
    state.alignment = result.alignment;
    state.series.setData(result.items);
  }

  /**
   * Ask for a full repaint after a mode change. The pane hands a rebasing scale
   * its baseline during the autoscale pass, so a `Light` repaint (all a
   * primitive's `requestUpdate` raises) would paint the new mode before it has
   * anything to quote against. `applyOptions` is the series handle's own route
   * to a Full invalidation, and an empty patch changes no style. Several of
   * them coalesce into one frame, so asking every comparison costs nothing.
   */
  private _repaint(): void {
    for (const state of this._items.values()) state.series.applyOptions({});
  }
}

/** One controller per chart, so `addComparison` can be called as a free function. */
const controllers = new WeakMap<ComparisonChartHost, ComparisonController>();

/**
 * The controller for a chart, created on first use. Use it to change the mode
 * for the whole chart, to list what is on it, or to clear it.
 */
export function comparisonController(
  chart: ComparisonChartHost,
  options?: ComparisonControllerOptions,
): ComparisonController {
  let controller = controllers.get(chart);
  if (controller === undefined) {
    controller = new ComparisonController(chart, options);
    controllers.set(chart, controller);
  }
  return controller;
}

/**
 * Put an instrument on the chart next to the primary one:
 *
 * ```ts
 * const bn = addComparison(chart, { symbol: 'BANKNIFTY', bars, color: '#f0b90b' });
 * ```
 *
 * The pane switches to percentage while any comparison is on it and goes back
 * to the mode it had when the last one leaves.
 */
export function addComparison(chart: ComparisonChartHost, options: ComparisonOptions): ComparisonHandle {
  return comparisonController(chart).add(options);
}
