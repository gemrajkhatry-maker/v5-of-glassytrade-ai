/**
 * One `DrawingLayer` per pane: renders every drawing on it and answers the
 * chart's hit-test. Anchors live in `{ time, price }`, so the layer maps them
 * through the *fractional* index helpers — the gapless axis means an anchor can
 * sit between bars (inside a collapsed weekend) or past the last one (a forward
 * projection), and whole-index lookups have nothing to return there.
 *
 * Hit ids are `draw:<id>` for the body and `draw:<id>#<n>` for anchor `n`, so
 * the controller can tell "move the whole shape" from "move this handle".
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from 'openalgo-charts';
import type { Drawing, ScreenPoint } from './types';
import { getDrawingTool, hasDrawingTool } from './tools';

/** Grab radius for a shape, in media px. */
const GRAB = 6;
/** Anchor handle radius, in media px. */
const HANDLE = 5;

/**
 * Which anchors get a grab handle. A freehand stroke carries one anchor per
 * sample, so handling all of them buries the ink under dozens of circles and
 * makes the shape itself impossible to grab — only the two ends mean anything,
 * which is what a brush shows elsewhere.
 */
function handleIndices(toolId: string, count: number): number[] {
  if (hasDrawingTool(toolId) && getDrawingTool(toolId).freehand === true && count > 2) {
    return [0, count - 1];
  }
  return Array.from({ length: count }, (_, i) => i);
}

export class DrawingLayer implements IPrimitive {
  private _drawings: Drawing[] = [];
  private _host: PrimitiveHost | null = null;
  private _selected: string | null = null;
  /** Anchors of the in-progress drawing, plus the live cursor point. */
  private _preview: Drawing | null = null;

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'top'; }
  /** Drawings overlay the price range; they never drive it. */
  public autoscaleInfo(): null { return null; }

  public setDrawings(drawings: readonly Drawing[]): void {
    this._drawings = drawings.slice();
    this._host?.requestUpdate();
  }

  public setSelected(id: string | null): void {
    if (id === this._selected) return;
    this._selected = id;
    this._host?.requestUpdate();
  }

  public setPreview(drawing: Drawing | null): void {
    this._preview = drawing;
    this._host?.requestUpdate();
  }

  /** Map an anchor to media px on this pane. */
  private _project(rc: PrimitiveRenderContext, time: number, price: number): ScreenPoint {
    return {
      x: rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(time)),
      y: rc.priceScale.priceToY(price),
    };
  }

  private _points(rc: PrimitiveRenderContext, d: Drawing): ScreenPoint[] {
    return d.points.map((p) => this._project(rc, p.time, p.price));
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const all = this._preview === null ? this._drawings : [...this._drawings, this._preview];
    for (const d of all) {
      if (d.visible === false || !hasDrawingTool(d.tool)) continue;
      const tool = getDrawingTool(d.tool);
      if (d.points.length < Math.max(1, tool.points)) continue;
      const media = this._points(rc, d);
      // Skip anything entirely off-pane; a fib grid with a far anchor would
      // otherwise stroke thousands of off-screen px every frame.
      if (!media.some((p) => Number.isFinite(p.x) && Number.isFinite(p.y))) continue;

      const style = {
        color: d.style.color ?? rc.theme.lineColor,
        lineWidth: d.style.lineWidth ?? 1.5,
        ...d.style,
      };
      const dpr = rc.dpr;
      ctx.save();
      if (d === this._preview) ctx.globalAlpha = 0.7;
      tool.draw({
        ctx, rc, drawing: d, selected: d.id === this._selected,
        pts: media.map((p) => ({ x: p.x * dpr, y: p.y * dpr })),
        style: { ...style, color: style.color, lineWidth: style.lineWidth },
        formatPrice: (v) => rc.priceScale.format(v),
      });
      ctx.restore();

      if (d.id === this._selected && d.locked !== true) this._drawHandles(ctx, rc, media, d.tool);
    }
  }

  private _drawHandles(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, pts: readonly ScreenPoint[], toolId: string): void {
    const dpr = rc.dpr;
    ctx.save();
    ctx.setLineDash([]);
    ctx.lineWidth = Math.max(1, Math.round(1.5 * dpr));
    for (const i of handleIndices(toolId, pts.length)) {
      const p = pts[i];
      ctx.beginPath();
      ctx.arc(p.x * dpr, p.y * dpr, HANDLE * dpr, 0, Math.PI * 2);
      ctx.fillStyle = rc.theme.background;
      ctx.fill();
      ctx.strokeStyle = rc.theme.lineColor;
      ctx.stroke();
    }
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    // Handles of the selected drawing win: they sit on top of its own body, and
    // grabbing an anchor must beat dragging the whole shape.
    if (this._selected !== null) {
      const sel = this._drawings.find((d) => d.id === this._selected);
      if (sel !== undefined && sel.locked !== true) {
        const pts = this._points(rc, sel);
        for (const i of handleIndices(sel.tool, pts.length)) {
          if (Math.hypot(x - pts[i].x, y - pts[i].y) <= HANDLE + 2) {
            return {
              externalId: `draw:${sel.id}#${i}`,
              zOrder: 'top', distance: 0, cursor: 'grabbing', draggable: true,
            };
          }
        }
      }
    }

    let best: { id: string; distance: number } | null = null;
    // Iterate newest-first so the most recently added shape wins a tie.
    for (let i = this._drawings.length - 1; i >= 0; i--) {
      const d = this._drawings[i];
      if (d.visible === false || d.locked === true || !hasDrawingTool(d.tool)) continue;
      const tool = getDrawingTool(d.tool);
      if (d.points.length < Math.max(1, tool.points)) continue;
      const dist = tool.distance(x, y, { pts: this._points(rc, d), drawing: d, rc });
      // A non-finite distance must miss, not hit: `NaN > GRAB` is false, so a
      // drawing with an unmappable anchor would otherwise swallow every click
      // on the pane.
      if (dist === null || !Number.isFinite(dist) || dist > GRAB) continue;
      if (best === null || dist < best.distance) best = { id: d.id, distance: dist };
    }
    if (best === null) return null;
    return {
      externalId: `draw:${best.id}`,
      zOrder: 'top', distance: best.distance, cursor: 'move', draggable: true,
    };
  }
}
