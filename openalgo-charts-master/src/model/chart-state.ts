/**
 * Serialisable chart state — the keystone the persistence-shaped features hang
 * off (saved layouts, templates, an objects panel, favourites, drawings).
 *
 * The rule that shapes this type: **the chart serialises what the chart owns.**
 * Series *data* is the application's — it knows the symbol, the timeframe, and
 * the feed — so `restoreState` never recreates series. It restores the things
 * the chart is the source of truth for (viewport, grid, panes, price scales,
 * indicators) and reports the series it saw so an app can rebuild them itself
 * and re-apply their styling.
 */
import type { SeriesStyle } from '../render/series-style';
import type { PriceScaleId } from './series';
import type { IndicatorSettings } from './indicator-registry';
import type { PriceScaleMode } from '../scale/price-scale';

/** Bumped when the shape changes incompatibly; `restoreState` ignores unknown versions. */
export const CHART_STATE_VERSION = 1;

export interface PriceScaleState {
  marginTop: number;
  marginBottom: number;
  minMove: number;
  mode: PriceScaleMode;
  inverted: boolean;
  /** False when the user (or an indicator's fixed range) pinned the scale. */
  autoScale: boolean;
  /** The pinned range, present only when `autoScale` is false. */
  range?: { min: number; max: number };
}

export interface PaneState {
  /** Relative height weight among panes. */
  weight: number;
  priceScale: PriceScaleState;
}

/** A series descriptor — enough to rebuild the shell, never the data. */
export interface SeriesState {
  type: string;
  style: SeriesStyle;
  paneIndex: number;
  priceScaleId: PriceScaleId;
}

export interface IndicatorState {
  indicatorId: string;
  settings: IndicatorSettings;
  paneIndex: number;
}

export interface ChartState {
  version: number;
  /** Visible logical range at save time. */
  viewport?: { from: number; to: number };
  barSpacing?: number;
  grid?: { vertLines: boolean; horzLines: boolean };
  crosshairMode?: 'normal' | 'magnet';
  panes?: PaneState[];
  /** Informational: `restoreState` does not recreate these (it has no data). */
  series?: SeriesState[];
  indicators?: IndicatorState[];
  /**
   * Opaque slot the drawing tier fills. The base engine round-trips it
   * untouched, so an app that persists state keeps drawings for free once the
   * tier is loaded.
   */
  drawings?: unknown;
}

/** What `restoreState` actually applied, so a caller can finish the job. */
export interface RestoreReport {
  /** True when the payload was a recognised, applicable state object. */
  applied: boolean;
  /** Series descriptors found in the state — the app rebuilds these itself. */
  series: SeriesState[];
  /** Indicator instances recreated. */
  indicators: number;
  /** Set when the payload was rejected. */
  reason?: string;
}
