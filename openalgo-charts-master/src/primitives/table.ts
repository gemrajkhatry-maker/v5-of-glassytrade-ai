/**
 * A grid overlay pinned to a corner of the pane rather than to bars.
 *
 * Seasonality heatmaps, performance summaries and signal scoreboards are all
 * the same shape: a small table of coloured cells that stays put while the
 * chart pans underneath. That makes this a screen-space primitive like the
 * watermark and the pane legend, not a series: it has no time anchor, takes no
 * part in autoscale, and survives a zoom untouched.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import { contrastText } from '../render/pill';

export type TablePosition =
  | 'top-left' | 'top-center' | 'top-right'
  | 'middle-left' | 'middle-center' | 'middle-right'
  | 'bottom-left' | 'bottom-center' | 'bottom-right';

export interface TableCell {
  text: string;
  /** Cell fill. Transparent when omitted, so the pane shows through. */
  bgColor?: string;
  /** Text colour. Derived from `bgColor` for contrast when omitted. */
  textColor?: string;
  align?: 'left' | 'center' | 'right';
  /** Overrides the table's `fontSize` for this cell, for a heading row. */
  fontSize?: number;
  bold?: boolean;
}

export interface ChartTableOptions {
  position: TablePosition;
  /** Gap from the pane edge, media px. */
  margin: number;
  /** Column width in media px. A per-column array sizes each one separately. */
  cellWidth: number | readonly number[];
  cellHeight: number;
  fontSize: number;
  /** Grid line colour. Omit to draw no grid. */
  borderColor?: string;
  borderWidth: number;
  /**
   * Table width as a percentage of the plot, 0 or omitted to size from
   * `cellWidth` instead. Column proportions are preserved, so a per-column
   * `cellWidth` array still controls the relative widths, and the percentage
   * only decides the total.
   */
  widthPercent?: number;
  /** Table height as a percentage of the plot, 0 or omitted to size from `cellHeight`. */
  heightPercent?: number;
  /**
   * Relative row heights, one per row, defaulting to 1. A separator row is the
   * reason this exists: stretched to fill a pane, an equal split makes a rule
   * between two sections as tall as the sections themselves.
   */
  rowWeights?: readonly number[];
  /** Backdrop behind the whole grid, drawn before the cells. */
  background?: string;
  /** Hit-test id, so a host can route clicks the way it does for other primitives. */
  id?: string;
}

export const DEFAULT_CHART_TABLE_OPTIONS: ChartTableOptions = {
  position: 'bottom-right',
  margin: 8,
  cellWidth: 64,
  cellHeight: 18,
  fontSize: 11,
  borderWidth: 1,
};

/** Column x offsets and the total width, from a uniform or per-column setting. */
function columnEdges(cellWidth: number | readonly number[], cols: number): { x: number[]; total: number } {
  const x: number[] = [];
  let acc = 0;
  for (let c = 0; c < cols; c++) {
    x.push(acc);
    acc += typeof cellWidth === 'number' ? cellWidth : (cellWidth[c] ?? cellWidth[cellWidth.length - 1] ?? 0);
  }
  return { x, total: acc };
}

/** Top-left corner of the grid for a position keyword, in media px. */
export function tableOrigin(
  position: TablePosition,
  margin: number,
  w: number,
  h: number,
  plotW: number,
  plotH: number,
): { x: number; y: number } {
  const [vert, horz] = position.split('-') as ['top' | 'middle' | 'bottom', 'left' | 'center' | 'right'];
  const x = horz === 'left' ? margin : horz === 'right' ? plotW - w - margin : (plotW - w) / 2;
  const y = vert === 'top' ? margin : vert === 'bottom' ? plotH - h - margin : (plotH - h) / 2;
  return { x, y };
}

export class ChartTable implements IPrimitive {
  private _rows: readonly (readonly TableCell[])[] = [];
  private _opts: ChartTableOptions;
  private _host: PrimitiveHost | null = null;
  /** Last drawn rect in media px, for hit-testing without recomputing layout. */
  private _rect: { x: number; y: number; w: number; h: number } | null = null;

  public constructor(options: Partial<ChartTableOptions> = {}) {
    this._opts = { ...DEFAULT_CHART_TABLE_OPTIONS, ...options };
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'top'; }

  public options(): Readonly<ChartTableOptions> { return this._opts; }

  public setOptions(patch: Partial<ChartTableOptions>): void {
    this._opts = { ...this._opts, ...patch };
    this._host?.requestUpdate();
  }

  /** Replace the grid. Rows may be ragged; each is drawn to its own length. */
  public setRows(rows: readonly (readonly TableCell[])[]): void {
    this._rows = rows;
    this._host?.requestUpdate();
  }

  public rows(): readonly (readonly TableCell[])[] { return this._rows; }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._rect = null;
    const rows = this._rows;
    if (rows.length === 0) return;
    const o = this._opts;
    const dpr = rc.dpr;
    let cols = 0;
    for (const r of rows) if (r.length > cols) cols = r.length;
    if (cols === 0) return;

    const edges = columnEdges(o.cellWidth, cols);
    let colX = edges.x;
    let w = edges.total;
    // A percentage stretches the grid to the pane it sits in. The columns keep
    // their declared proportions, so a heatmap with a wide year column still
    // reads correctly at any width.
    if (o.widthPercent !== undefined && o.widthPercent > 0 && w > 0) {
      const target = (rc.plotWidth * o.widthPercent) / 100;
      const k = target / w;
      colX = colX.map((v) => v * k);
      w = target;
    }
    // Row tops and the total height, from the weights and the base cell height.
    const weights = rows.map((_, r) => {
      const w2 = o.rowWeights?.[r];
      return typeof w2 === 'number' && w2 > 0 ? w2 : 1;
    });
    const weightTotal = weights.reduce((a, b) => a + b, 0);
    let unit = o.cellHeight;
    let h = unit * weightTotal;
    if (o.heightPercent !== undefined && o.heightPercent > 0) {
      h = (rc.plotHeight * o.heightPercent) / 100;
      unit = h / weightTotal;
    }
    const rowY: number[] = [];
    for (let r = 0, acc = 0; r < rows.length; r++) { rowY.push(acc); acc += unit * weights[r]; }
    const origin = tableOrigin(o.position, o.margin, w, h, rc.plotWidth, rc.plotHeight);
    this._rect = { x: origin.x, y: origin.y, w, h };

    const px = (v: number): number => Math.round(v * dpr);
    const ox = px(origin.x);
    const oy = px(origin.y);

    ctx.save();
    if (o.background !== undefined) {
      ctx.fillStyle = o.background;
      ctx.fillRect(ox, oy, px(w), px(h));
    }

    ctx.textBaseline = 'middle';
    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      const cellTop = oy + px(rowY[r]);
      const rowH = px(unit * weights[r]);
      for (let c = 0; c < row.length; c++) {
        const cell = row[c];
        const cellLeft = ox + px(colX[c]);
        const cellW = px((colX[c + 1] ?? w) - colX[c]);

        if (cell.bgColor !== undefined) {
          ctx.fillStyle = cell.bgColor;
          ctx.fillRect(cellLeft, cellTop, cellW, rowH);
        }
        if (o.borderColor !== undefined && o.borderWidth > 0) {
          ctx.strokeStyle = o.borderColor;
          ctx.lineWidth = Math.max(1, px(o.borderWidth));
          ctx.strokeRect(cellLeft, cellTop, cellW, rowH);
        }
        if (cell.text === '') continue;

        // Shrink the type when a stretched row is shorter than the declared
        // font, so a tall grid in a short pane stays legible instead of
        // overlapping into its neighbours.
        const size = Math.min(px(cell.fontSize ?? o.fontSize), Math.floor(rowH * 0.62));
        ctx.font = `${cell.bold === true ? '600 ' : ''}${size}px system-ui, sans-serif`;
        // A cell with a fill picks its own readable ink; one without falls back
        // to the axis colour, which is legible on either theme's background.
        ctx.fillStyle = cell.textColor
          ?? (cell.bgColor !== undefined ? contrastText(cell.bgColor) : rc.theme.axisText);
        const pad = px(4);
        const align = cell.align ?? 'center';
        ctx.textAlign = align;
        const tx = align === 'left' ? cellLeft + pad
          : align === 'right' ? cellLeft + cellW - pad
          : cellLeft + cellW / 2;
        ctx.fillText(cell.text, tx, cellTop + rowH / 2);
      }
    }
    ctx.restore();
  }

  public hitTest(x: number, y: number): PrimitiveHit | null {
    const r = this._rect;
    if (this._opts.id === undefined || r === null) return null;
    if (x < r.x || x > r.x + r.w || y < r.y || y > r.y + r.h) return null;
    return { externalId: this._opts.id, zOrder: 'top', distance: 0, cursor: 'default' };
  }
}
