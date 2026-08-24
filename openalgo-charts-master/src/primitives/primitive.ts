/**
 * Primitive / plugin API (ARCHITECTURE.md §8). The extension point that keeps
 * the core small and powers markers, events, indicators, and the trade layer.
 * A primitive draws on a pane, optionally contributes to autoscale, and
 * optionally hit-tests for hover/drag.
 */
import type { TimeScale } from '../scale/time-scale';
import type { PriceScale } from '../scale/price-scale';
import type { DataLayer } from '../model/data-layer';
import type { Bar } from '../model/bar';
import type { ChartTheme } from '../theme';

export type ZOrder = 'bottom' | 'normal' | 'top';

export interface PrimitiveRenderContext {
  timeScale: TimeScale;
  priceScale: PriceScale;
  dataLayer: DataLayer;
  plotWidth: number;
  plotHeight: number;
  priceAxisWidth: number;
  dpr: number;
  theme: ChartTheme;
  /**
   * The pane's primary price series, for a primitive that needs what price
   * actually did rather than just the scales — a forecast scoring itself, say.
   * Lazy, so nothing pays for it unless asked. Absent on synthetic contexts.
   */
  bars?: () => readonly Bar[];
  /** externalId of the primitive hit under the pointer (hover state), if any. */
  hoverId?: string | null;
  /** externalId of the line being dragged (active state), if any. */
  dragId?: string | null;
}

export interface PrimitiveHit {
  externalId: string;
  zOrder: ZOrder;
  /** Pixel distance from the cursor (smaller wins ties before z-order). */
  distance: number;
  cursor?: string;
  /**
   * Arm a drag on press. Price lines set `cursor: 'ns-resize'` and move on one
   * axis; anything that moves on **both** (a drawing anchor, a whole shape)
   * declares it here, and the drag callbacks receive time as well as price.
   */
  draggable?: boolean;
}

/** Injected when a primitive is attached; lets it request a repaint. */
export interface PrimitiveHost {
  requestUpdate(): void;
}

/**
 * Where chart furniture lives, as distinct from pane furniture.
 *
 * A price line belongs to a pane. A brand mark, a corner clock or a session
 * badge belongs to the CHART: it should sit at an edge of the whole stack, and
 * follow that edge as indicator panes come and go. `chart-bottom` is the common
 * case, and it also survives maximize, which hides the other panes entirely and
 * would otherwise take a pane-0 watermark with it.
 */
export type PrimitiveAnchor = 'chart-top' | 'chart-bottom';

/** Passed to `addPrimitive` instead of a pane index to anchor to the chart. */
export interface PrimitivePlacement {
  anchor: PrimitiveAnchor;
}

export interface IPrimitive {
  /** Layer order vs series: 'bottom' (behind), 'normal' (over), 'top' (overlay). */
  zOrder(): ZOrder;
  draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void;
  /** Optional: expand the pane's autoscale range so this primitive isn't clipped. */
  autoscaleInfo?(): { min: number; max: number } | null;
  /**
   * Optional: run once per frame after every scale on the pane has been
   * measured, and before anything is painted.
   *
   * `draw` is too late for anything that has to change a scale, because the
   * price axis is painted near the top of `paintBase` while primitives draw
   * further down: a range corrected in `draw` labels its axis one frame late,
   * and on a static chart that frame never comes. A comparison overlay lining
   * its scale up with the pane's own is the case this exists for.
   */
  afterAutoscale?(): void;
  /** Optional: topmost hit under (x,y) in media px (relative to the pane plot). */
  hitTest?(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null;
  attached?(host: PrimitiveHost): void;
  detached?(): void;
}

/** Pick the best hit across primitives: nearest distance, then z-order priority. */
export function bestHit(hits: readonly (PrimitiveHit | null)[]): PrimitiveHit | null {
  const order: Record<ZOrder, number> = { top: 2, normal: 1, bottom: 0 };
  let best: PrimitiveHit | null = null;
  for (const h of hits) {
    if (h === null) continue;
    if (
      best === null ||
      h.distance < best.distance ||
      (h.distance === best.distance && order[h.zOrder] > order[best.zOrder])
    ) {
      best = h;
    }
  }
  return best;
}
