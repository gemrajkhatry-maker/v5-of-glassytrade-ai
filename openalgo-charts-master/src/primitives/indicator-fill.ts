/**
 * Shaded band between two indicator plots — the Ichimoku cloud, a Bollinger
 * channel, a Keltner envelope.
 *
 * A pair of lines is not the same picture as a filled region: the fill is what
 * makes "price is above the cloud" or "the cloud flipped" readable at a glance,
 * and which side is on top is itself the signal. So the band is drawn as two
 * runs — one where A leads, one where B does — and the crossings between them
 * are split at the exact intersection rather than at the nearest bar, or the
 * colours would bleed a bar past every flip.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from './primitive';

export interface IndicatorFillOptions {
  /** Fill colour where the first series is above the second. */
  colorUp: string;
  /** Fill colour where the second is above the first. */
  colorDown: string;
  /** 0..1. Defaults to 0.12 — a band must not drown the candles it sits behind. */
  opacity?: number;
}

/** One bar's pair of values; `null` where either plot has no value yet. */
export interface FillPoint {
  /** Logical index on the shared time axis (fractional is fine). */
  index: number;
  a: number | null;
  b: number | null;
}

export class IndicatorFill implements IPrimitive {
  private _points: FillPoint[] = [];
  private _opts: IndicatorFillOptions;
  private _host: PrimitiveHost | null = null;
  private _visible = true;

  public constructor(options: IndicatorFillOptions) {
    this._opts = { opacity: 0.12, ...options };
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  /** Behind the series, so the lines and candles stay crisp on top of it. */
  public zOrder(): ZOrder { return 'bottom'; }
  /** The plots it spans already drive the scale; the fill must not widen it. */
  public autoscaleInfo(): null { return null; }

  public setPoints(points: readonly FillPoint[]): void {
    this._points = points.slice();
    this._host?.requestUpdate();
  }

  public setOptions(patch: Partial<IndicatorFillOptions>): void {
    this._opts = { ...this._opts, ...patch };
    this._host?.requestUpdate();
  }

  public setVisible(on: boolean): void {
    this._visible = on;
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    if (!this._visible || this._points.length < 2) return;
    const dpr = rc.dpr;
    const x = (i: number): number => rc.timeScale.indexToX(i) * dpr;
    const y = (v: number): number => rc.priceScale.priceToY(v) * dpr;

    ctx.save();
    ctx.globalAlpha = this._opts.opacity ?? 0.12;

    // Walk the series accumulating one polygon per constant-sign run. A gap
    // (either value missing) closes the current run — bridging it would fill
    // across a stretch where the indicator has no opinion.
    let run: { up: boolean; top: number[]; bot: number[]; xs: number[] } | null = null;
    const flush = (): void => {
      if (run !== null && run.xs.length >= 2) {
        ctx.beginPath();
        ctx.moveTo(run.xs[0], run.top[0]);
        for (let i = 1; i < run.xs.length; i++) ctx.lineTo(run.xs[i], run.top[i]);
        for (let i = run.xs.length - 1; i >= 0; i--) ctx.lineTo(run.xs[i], run.bot[i]);
        ctx.closePath();
        ctx.fillStyle = run.up ? this._opts.colorUp : this._opts.colorDown;
        ctx.fill();
      }
      run = null;
    };

    for (let i = 0; i < this._points.length; i++) {
      const p = this._points[i];
      if (p.a === null || p.b === null || !Number.isFinite(p.a) || !Number.isFinite(p.b)) {
        flush();
        continue;
      }
      const up = p.a >= p.b;
      const px = x(p.index);
      const ya = y(p.a);
      const yb = y(p.b);

      if (run !== null && run.up !== up) {
        // Sign flipped: end the run at the crossing so the colours meet on the
        // intersection instead of a bar boundary.
        const prev = this._points[i - 1];
        if (prev !== undefined && prev.a !== null && prev.b !== null) {
          const d0 = prev.a - prev.b;
          const d1 = p.a - p.b;
          const t = d0 === d1 ? 0 : d0 / (d0 - d1);
          const cx = x(prev.index + (p.index - prev.index) * t);
          const cy = y(prev.a + (p.a - prev.a) * t);
          run.xs.push(cx); run.top.push(cy); run.bot.push(cy);
          flush();
          run = { up, xs: [cx], top: [cy], bot: [cy] };
        } else {
          flush();
        }
      }
      if (run === null) run = { up, xs: [], top: [], bot: [] };
      run.xs.push(px);
      run.top.push(ya);
      run.bot.push(yb);
    }
    flush();
    ctx.restore();
  }
}
