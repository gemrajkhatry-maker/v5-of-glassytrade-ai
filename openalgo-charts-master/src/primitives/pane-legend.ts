/**
 * Pane legend (ARCHITECTURE.md §8) — the row at the top-left
 * of a pane: a color swatch, the source's name, its parameters, the value under
 * the crosshair, and inline action buttons on the right.
 *
 * Drawn on the canvas rather than in the DOM, like `BuySellButtons` and
 * `DomLadder`, so it composites into screenshots and costs no DOM per pane.
 * Buttons hit-test as `${id}::close`, `${id}::hide`, and `${id}::settings`, so
 * the host routes them through the same `subscribeClick` path as order pills.
 *
 * Rows stack: several legends on one pane offset each other vertically, which
 * the host does by giving each a `row` index.
 *
 * This row is also the chart's status line, so `statusLine` carries the
 * per-field switches a settings dialog expects (logo, title, market status,
 * chart values, bar change, volume, last day change, background). Every switch
 * defaults to the behaviour that predates it, so a caller that passes none sees
 * the row it always saw. Fields the primitive cannot compute (a logo bitmap,
 * whether the market is open, the change since yesterday's close) arrive
 * through `status`; with no source they draw nothing at all rather than a
 * placeholder.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import { withAlpha } from '../render/pill';

export type PaneLegendAction = 'hide' | 'settings' | 'up' | 'down' | 'maximize' | 'close';

/**
 * One reading on a legend row. Multi-plot sources show one per plot, each in
 * that plot's own color (an MA ribbon's four averages, MACD's three lines) —
 * a single string in a single color cannot say which number is which.
 */
export interface LegendValue {
  /** Dimmed prefix, e.g. `O` / `H` / `Vol`. */
  label?: string;
  text: string;
  /** Defaults to the row's `valueColor`, then `color`, then the theme text. */
  color?: string;
  /**
   * Which status-line switch owns this reading. Untagged readings are the
   * source's own last value, governed by `statusLine.lastValueLabel`.
   */
  field?: LegendField;
}

/**
 * Status-line groups a host can feed and switch off independently. The legend
 * never derives these: it tags what the host hands it, so one switch hides one
 * group and leaves the rest of the row alone.
 */
export type LegendField = 'ohlc' | 'change' | 'volume';

/**
 * Which name the title shows. `description` and `ticker` come from `status`;
 * with neither supplied the title falls back to `title`, which always exists.
 */
export type LegendTitleMode = 'symbol' | 'description' | 'ticker';

/**
 * The parts of the status line the primitive has no way to know. The host
 * supplies what it has; anything missing is simply not drawn.
 */
export interface LegendStatusData {
  /** Already-decoded logo (an `<img>`, an `ImageBitmap`, a canvas). */
  logo?: CanvasImageSource;
  /** Long name for `titleMode: 'description'`, e.g. `Apple Inc.`. */
  description?: string;
  /** Exchange ticker for `titleMode: 'ticker'`, e.g. `NASDAQ:AAPL`. */
  ticker?: string;
  /** Session state, e.g. `{ text: 'Market open', color: '#26a69a' }`. */
  marketStatus?: LegendValue;
  /** Change against the previous close, e.g. `{ text: '+1.20 (+0.75%)' }`. */
  lastDayChange?: LegendValue;
}

/**
 * A snapshot, or a getter the legend calls each frame, so live fields (market
 * status, day change) can change without the host patching options at tick
 * speed. Returning `null` means "nothing to show".
 */
export type LegendStatusSource = LegendStatusData | (() => LegendStatusData | null);

/**
 * Per-field switches for the status line. Every one defaults to on, so the
 * absent option object reproduces the row exactly as it drew before these
 * existed. A field whose data is missing draws nothing whether it is on or off.
 */
export interface LegendStatusLineOptions {
  /** Symbol logo, when `status` supplies one. */
  logo?: boolean;
  /** The bold name. Also the "name label" switch for an indicator row. */
  title?: boolean;
  /** Which name the title shows. Default `symbol`. */
  titleMode?: LegendTitleMode;
  /** Session state from `status.marketStatus`. */
  marketStatus?: boolean;
  /** The OHLC readout: readings tagged `field: 'ohlc'`. */
  chartValues?: boolean;
  /** Change over the hovered bar: readings tagged `field: 'change'`. */
  barChange?: boolean;
  /** Readings tagged `field: 'volume'`. */
  volume?: boolean;
  /** Change since the previous close, from `status.lastDayChange`. */
  lastDayChange?: boolean;
  /**
   * The source's own reading (untagged values). This is the scales-and-lines
   * "last value label" control, which lands here because the legend is what
   * draws that number on this row.
   */
  lastValueLabel?: boolean;
  /**
   * Plate behind the row's text, for legibility over candles. Off by default:
   * the row has never had one, and turning it on is a deliberate choice.
   */
  background?: boolean;
  /** Plate opacity, 0..1. Default 0.8, matching the hover plate. */
  backgroundOpacity?: number;
  /** Plate color. Defaults to the theme background. */
  backgroundColor?: string;
}

export interface PaneLegendOptions {
  /** Stable id; buttons hit-test as `${id}::close` etc. */
  id: string;
  /** Bold source name, e.g. `RSI`. */
  title: string;
  /** Dimmed parameter summary after the title, e.g. `14 close`. */
  params?: string;
  /** Swatch color; omitted draws no swatch. */
  color?: string;
  /**
   * Color for the live value. Defaults to `color`, then the theme's text — so a
   * row can tint its reading (an up/down change) without being forced to show a
   * swatch in that same color.
   */
  valueColor?: string;
  /** Vertical slot on the pane (0 = topmost). */
  row?: number;
  /**
   * Which inline action buttons to draw, left to right. Each hit-tests as
   * `${id}::<action>`:
   *  - `up` / `down` — move this pane one slot (`::up` / `::down`)
   *  - `hide`        — toggle visibility (`::hide`)
   *  - `maximize`    — expand this pane to fill the chart (`::maximize`)
   *  - `close`       — remove the source, and its pane if it empties (`::close`)
   *
   * Defaults to `['up', 'down', 'hide', 'maximize', 'close']` for pane sources
   * and `['hide', 'close']` for overlays (pass explicitly to override).
   */
  actions?: readonly PaneLegendAction[];
  /** Rendered as hidden (dimmed, eye hollow). */
  hidden?: boolean;
  /** Rendered as maximized (the maximize glyph becomes restore). */
  maximized?: boolean;
  /** Text size in media px. Default 11. */
  font?: number;
  /** Left inset from the plot edge in media px. Default 8. */
  left?: number;
  /** Top inset in media px. Default 6. */
  top?: number;
  /** Per-field status-line switches. Patching merges field by field. */
  statusLine?: LegendStatusLineOptions;
  /** Host-supplied status-line data (logo, names, market state, day change). */
  status?: LegendStatusSource;
}

const ROW_H = 18;
const GAP = 6;
const BTN = 16;
/** Square side of the symbol logo, in media px: fits the row with margin. */
const LOGO = 12;
/** Extra hover width past the text, so the controls can appear without a gap. */
const REVEAL_PAD = 130;
const FONT = 'ui-sans-serif, system-ui, sans-serif';
/** Shared empties, so the common "no options, no data" path allocates nothing. */
const NO_SWITCHES: LegendStatusLineOptions = {};
const NO_STATUS: LegendStatusData = {};

/**
 * One measured piece of the row. The whole row is measured before any of it is
 * drawn: the background plate has to be filled first to sit behind the text,
 * and it cannot know its width until the text has been measured.
 */
type Seg =
  | { k: 'logo'; img: CanvasImageSource; w: number; gap: number }
  | { k: 'dot'; color: string; w: number; gap: number }
  | { k: 'text'; text: string; color: string; bold: boolean; w: number; gap: number };

/** A reading draws unless the switch that owns its group is off. */
function fieldOn(s: LegendStatusLineOptions, field: LegendField | undefined): boolean {
  if (field === 'ohlc') return s.chartValues !== false;
  if (field === 'change') return s.barChange !== false;
  if (field === 'volume') return s.volume !== false;
  return s.lastValueLabel !== false;
}

/**
 * Per-source actions, mirroring the indicator legend toolbar: show/hide,
 * settings, delete. Pane-level actions (`up`/`down`/`maximize`) are added by the
 * host to the *first* legend on a pane, so extra rows stay uncluttered.
 */
const DEFAULT_ACTIONS: readonly PaneLegendAction[] = ['hide', 'settings', 'close'];

/**
 * Action icons as vector strokes rather than text glyphs — `⛶`, `🗑`, and the
 * arrows render inconsistently (or as emoji) across platforms and font stacks,
 * and a stroked path stays crisp at any DPR.
 */
function drawGlyph(
  ctx: CanvasRenderingContext2D,
  action: PaneLegendAction,
  cx: number,
  cy: number,
  font: number,
  dpr: number,
  o: PaneLegendOptions,
): void {
  const r = font * 0.42;                 // half-extent of the icon box
  const w = Math.max(1, Math.round(1.4 * dpr));
  ctx.save();
  ctx.strokeStyle = ctx.fillStyle;
  ctx.lineWidth = w;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  switch (action) {
    case 'up':
      ctx.moveTo(cx, cy + r); ctx.lineTo(cx, cy - r);
      ctx.moveTo(cx - r * 0.62, cy - r * 0.35); ctx.lineTo(cx, cy - r);
      ctx.lineTo(cx + r * 0.62, cy - r * 0.35);
      break;
    case 'down':
      ctx.moveTo(cx, cy - r); ctx.lineTo(cx, cy + r);
      ctx.moveTo(cx - r * 0.62, cy + r * 0.35); ctx.lineTo(cx, cy + r);
      ctx.lineTo(cx + r * 0.62, cy + r * 0.35);
      break;
    case 'hide': {
      // Eye: two arcs forming a lens, with a pupil. Hidden state strikes it through.
      ctx.moveTo(cx - r, cy);
      ctx.quadraticCurveTo(cx, cy - r * 1.15, cx + r, cy);
      ctx.quadraticCurveTo(cx, cy + r * 1.15, cx - r, cy);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, r * 0.34, 0, Math.PI * 2);
      if (o.hidden === true) {
        ctx.moveTo(cx - r, cy + r * 0.85); ctx.lineTo(cx + r, cy - r * 0.85);
      }
      break;
    }
    case 'maximize':
      if (o.maximized === true) {
        // restore: inward corner brackets
        ctx.moveTo(cx - r, cy - r * 0.25); ctx.lineTo(cx - r * 0.25, cy - r * 0.25); ctx.lineTo(cx - r * 0.25, cy - r);
        ctx.moveTo(cx + r, cy + r * 0.25); ctx.lineTo(cx + r * 0.25, cy + r * 0.25); ctx.lineTo(cx + r * 0.25, cy + r);
      } else {
        // maximize: four outward corner brackets
        ctx.moveTo(cx - r, cy - r * 0.4); ctx.lineTo(cx - r, cy - r); ctx.lineTo(cx - r * 0.4, cy - r);
        ctx.moveTo(cx + r * 0.4, cy - r); ctx.lineTo(cx + r, cy - r); ctx.lineTo(cx + r, cy - r * 0.4);
        ctx.moveTo(cx + r, cy + r * 0.4); ctx.lineTo(cx + r, cy + r); ctx.lineTo(cx + r * 0.4, cy + r);
        ctx.moveTo(cx - r * 0.4, cy + r); ctx.lineTo(cx - r, cy + r); ctx.lineTo(cx - r, cy + r * 0.4);
      }
      break;
    case 'settings': {
      // Gear: a ring plus eight short teeth.
      ctx.arc(cx, cy, r * 0.46, 0, Math.PI * 2);
      for (let i = 0; i < 8; i++) {
        const a = (i * Math.PI) / 4;
        const dx = Math.cos(a);
        const dy = Math.sin(a);
        ctx.moveTo(cx + dx * r * 0.68, cy + dy * r * 0.68);
        ctx.lineTo(cx + dx * r, cy + dy * r);
      }
      break;
    }
    case 'close':
      // Trash: lid, can, and two tick marks.
      ctx.moveTo(cx - r * 0.8, cy - r * 0.55); ctx.lineTo(cx + r * 0.8, cy - r * 0.55);
      ctx.moveTo(cx - r * 0.3, cy - r * 0.55); ctx.lineTo(cx - r * 0.3, cy - r * 0.85);
      ctx.lineTo(cx + r * 0.3, cy - r * 0.85); ctx.lineTo(cx + r * 0.3, cy - r * 0.55);
      ctx.moveTo(cx - r * 0.6, cy - r * 0.55); ctx.lineTo(cx - r * 0.45, cy + r * 0.85);
      ctx.lineTo(cx + r * 0.45, cy + r * 0.85); ctx.lineTo(cx + r * 0.6, cy - r * 0.55);
      break;
  }
  ctx.stroke();
  ctx.restore();
}

export class PaneLegend implements IPrimitive {
  private _opts: Required<Pick<PaneLegendOptions, 'id' | 'title'>> & PaneLegendOptions;
  private _host: PrimitiveHost | null = null;
  private _values: LegendValue[] = [];
  /** Button geometry from the last draw, in media px, for hit-testing. */
  private _buttons: { id: string; x: number; y: number }[] = [];
  /** Right edge of the drawn row, in media px. */
  private _width = 0;

  public constructor(opts: PaneLegendOptions) {
    this._opts = { font: 11, left: 8, top: 6, row: 0, ...opts };
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'top'; }
  public autoscaleInfo(): null { return null; }

  /** A single live reading after the params (typically crosshair-driven). */
  public setValue(text: string, color?: string): void {
    this.setValues(text === '' ? [] : [{ text, color }]);
  }

  /** One reading per plot, each in its own color. */
  public setValues(values: readonly LegendValue[]): void {
    const same = values.length === this._values.length
      && values.every((v, i) => v.text === this._values[i].text
        && v.label === this._values[i].label && v.color === this._values[i].color
        && v.field === this._values[i].field);
    if (same) return;
    this._values = values.map((v) => ({ ...v }));
    this._host?.requestUpdate();
  }

  public setOptions(patch: Partial<PaneLegendOptions>): void {
    // Switches merge field by field: a settings dialog toggles one checkbox at
    // a time, and a shallow spread would silently reset the other nine.
    const prev = this._opts.statusLine;
    this._opts = { ...this._opts, ...patch };
    if (patch.statusLine !== undefined) {
      this._opts.statusLine = { ...prev, ...patch.statusLine };
    }
    this._host?.requestUpdate();
  }

  /** Resolve the host's status data for this frame; `{}` when it has none. */
  private _status(): LegendStatusData {
    const src = this._opts.status;
    if (src === undefined) return NO_STATUS;
    return (typeof src === 'function' ? src() : src) ?? NO_STATUS;
  }

  public options(): PaneLegendOptions {
    return this._opts;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const o = this._opts;
    const dpr = rc.dpr;
    const f = (o.font ?? 11) * dpr;
    const y = ((o.top ?? 6) + (o.row ?? 0) * ROW_H) * dpr;
    const cy = y + (ROW_H * dpr) / 2;
    const x0 = (o.left ?? 8) * dpr;
    let x = x0;
    const dim = o.hidden === true;
    const s = o.statusLine ?? NO_SWITCHES;
    const data = this._status();
    const dimText = withAlpha(rc.theme.axisText, 0.55);

    ctx.save();
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    ctx.globalAlpha = dim ? 0.45 : 1;

    const segs: Seg[] = [];
    const text = (t: string, color: string, bold: boolean, gap: number): void => {
      ctx.font = `${bold ? '600 ' : ''}${f}px ${FONT}`;
      segs.push({ k: 'text', text: t, color, bold, w: ctx.measureText(t).width, gap: gap * dpr });
    };
    // Label plus number, the shape every reading takes: the crosshair values,
    // the market state and the day change all render through this.
    const reading = (v: LegendValue, fallback: string): void => {
      if (v.label !== undefined && v.label !== '') text(v.label, dimText, false, 3);
      text(v.text, v.color ?? fallback, false, GAP);
    };

    if (data.logo !== undefined && s.logo !== false) {
      segs.push({ k: 'logo', img: data.logo, w: LOGO * dpr, gap: 5 * dpr });
    }
    if (o.color !== undefined) segs.push({ k: 'dot', color: o.color, w: 6 * dpr, gap: 5 * dpr });
    if (s.title !== false) {
      const mode = s.titleMode ?? 'symbol';
      const alt = mode === 'description' ? data.description : mode === 'ticker' ? data.ticker : undefined;
      text(alt ?? o.title, rc.theme.axisText, true, GAP);
    }
    if (o.params !== undefined && o.params !== '') text(o.params, dimText, false, GAP);
    if (data.marketStatus !== undefined && s.marketStatus !== false) {
      reading(data.marketStatus, dimText);
    }
    // Readings: one per plot, each in its plot's color, with a dimmed label.
    const valueColor = o.valueColor ?? o.color ?? rc.theme.axisText;
    for (const v of this._values) {
      if (fieldOn(s, v.field)) reading(v, valueColor);
    }
    if (data.lastDayChange !== undefined && s.lastDayChange !== false) {
      reading(data.lastDayChange, valueColor);
    }

    // The plate goes down before a single glyph does, which is the whole point
    // of measuring first: text over plate, never plate over text.
    const last = segs[segs.length - 1];
    if (s.background === true && last !== undefined) {
      const pad = 4 * dpr;
      const w = segs.reduce((a, sg) => a + sg.w + sg.gap, 0) - last.gap + pad * 2;
      ctx.globalAlpha = 1;
      ctx.fillStyle = withAlpha(s.backgroundColor ?? rc.theme.background, s.backgroundOpacity ?? 0.8);
      ctx.beginPath();
      ctx.roundRect(x0 - pad, cy - (ROW_H / 2) * dpr, w, ROW_H * dpr, 4 * dpr);
      ctx.fill();
      ctx.globalAlpha = dim ? 0.45 : 1;
    }

    for (const sg of segs) {
      if (sg.k === 'text') {
        ctx.font = `${sg.bold ? '600 ' : ''}${f}px ${FONT}`;
        ctx.fillStyle = sg.color;
        ctx.fillText(sg.text, x, cy);
      } else if (sg.k === 'dot') {
        ctx.fillStyle = sg.color;
        ctx.beginPath();
        ctx.arc(x + 3 * dpr, cy, 3 * dpr, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.drawImage(sg.img, x, cy - sg.w / 2, sg.w, sg.w);
      }
      x += sg.w + sg.gap;
    }

    // Actions appear on hover only, so a row of legends reads as clean text
    // until you approach one. The row itself hit-tests (as `::row`), which is
    // what makes the pointer "arrive" and reveal them.
    this._buttons = [];
    const active = typeof rc.hoverId === 'string' && rc.hoverId.startsWith(`${o.id}::`);
    const actions = o.actions ?? DEFAULT_ACTIONS;
    if (active && actions.length > 0) {
      // Soft plate behind the controls, so glyphs stay legible over candles.
      const plateW = (actions.length * (BTN + 2) + 6) * dpr;
      ctx.globalAlpha = 1;
      ctx.fillStyle = withAlpha(rc.theme.background, 0.82);
      ctx.beginPath();
      ctx.roundRect(x - 3 * dpr, cy - (ROW_H / 2) * dpr, plateW, ROW_H * dpr, 5 * dpr);
      ctx.fill();
      x += 2 * dpr;
      for (const action of actions) {
        const id = `${o.id}::${action}`;
        const bx = x;
        this._buttons.push({ id, x: bx / dpr, y: y / dpr });
        const hovered = rc.hoverId === id;
        if (hovered) {
          ctx.fillStyle = withAlpha(rc.theme.axisText, 0.16);
          ctx.beginPath();
          ctx.roundRect(bx, cy - (BTN / 2) * dpr, BTN * dpr, BTN * dpr, 4 * dpr);
          ctx.fill();
        }
        ctx.globalAlpha = dim ? 0.5 : hovered ? 1 : 0.75;
        ctx.fillStyle = action === 'close' && hovered ? '#ff6b6b' : rc.theme.axisText;
        drawGlyph(ctx, action, bx + (BTN / 2) * dpr, cy, f, dpr, o);
        ctx.globalAlpha = 1;
        x += (BTN + 2) * dpr;
      }
    }

    this._width = x / dpr;
    ctx.restore();
  }

  public hitTest(x: number, y: number): PrimitiveHit | null {
    const o = this._opts;
    const top = (o.top ?? 6) + (o.row ?? 0) * ROW_H;
    if (y < top || y > top + ROW_H) return null;
    for (const b of this._buttons) {
      if (x >= b.x && x <= b.x + BTN) {
        return { externalId: b.id, zOrder: 'top', distance: 0, cursor: 'pointer' };
      }
    }
    // The row itself: reveals the controls and swallows the click so it never
    // reaches the host's click handler as a phantom id.
    const right = Math.max(this._width, (o.left ?? 8) + 40) + REVEAL_PAD;
    if (x >= (o.left ?? 8) - 4 && x <= right) {
      return { externalId: `${o.id}::row`, zOrder: 'top', distance: 0, cursor: 'default' };
    }
    return null;
  }
}
