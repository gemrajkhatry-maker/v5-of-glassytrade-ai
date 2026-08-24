/**
 * Candlestick renderer (ARCHITECTURE.md §6). Pure geometry helpers are split
 * out for unit testing; drawing happens in the bitmap (device-px) scope.
 */
import type { Bar } from '../model/bar';

export interface CandleStyle {
  upColor: string;
  downColor: string;
  borderUpColor: string;
  borderDownColor: string;
  wickUpColor: string;
  wickDownColor: string;
  borderVisible: boolean;
  wickVisible: boolean;
  /**
   * Paint the body at all. Off leaves the candle as its outline and wick, which
   * is what a settings dialog's "Body" switch means.
   *
   * Distinct from `hollow`, which empties only the UP candles and is the
   * hollow-candle chart type. This empties both, and it is the one switch here
   * that can legitimately leave nothing drawn: with borders off as well, a
   * candle is reduced to its wick. That is two deliberate switches rather than
   * an accident, so it is honoured rather than second-guessed.
   */
  bodyVisible?: boolean;
  /** Draw up-candle bodies as outlines only (hollow candles). */
  hollow?: boolean;
  /**
   * "Color bars based on previous close": a bar is up when it closed above the
   * bar before it rather than above its own open. Body, border and wick all
   * follow the same verdict, so the candle never disagrees with itself.
   */
  colorByPreviousClose?: boolean;
  /** Per-bar body-width scale 0..1 (volume candles); 1 = full width. */
  widthScale?: (bar: Bar) => number;
}

export const DEFAULT_CANDLE_STYLE: CandleStyle = {
  upColor: '#26a69a',
  downColor: '#ef5350',
  borderUpColor: '#26a69a',
  borderDownColor: '#ef5350',
  wickUpColor: '#26a69a',
  wickDownColor: '#ef5350',
  borderVisible: true,
  wickVisible: true,
};

/**
 * Pure: optimal candle body width in device px for a given bar spacing. Leaves
 * a ~1px gap between candles, keeps a minimum of 1px, and matches odd/even
 * parity with the wick so the body stays symmetric about the (1px) wick.
 */
export function optimalBarWidth(barSpacing: number, dpr: number): number {
  const raw = Math.floor(barSpacing * dpr * 0.8);
  let w = Math.max(1, raw);
  if (w >= 2) {
    const wick = Math.max(1, Math.floor(dpr));
    if (w % 2 !== wick % 2) w -= 1;
  }
  return Math.max(1, w);
}

export interface CandleDrawItem {
  /** Bar center x, media px. */
  x: number;
  bar: Bar;
  /**
   * Close of the bar immediately before this one when that bar is not itself in
   * `items`, which is the case for the first visible bar after a scroll. Only
   * read when `colorByPreviousClose` is on, and only for the first item.
   */
  prevClose?: number;
}

/**
 * Draw candles onto a bitmap-scope context. `priceToY` and `x` are media-px;
 * everything is multiplied by `dpr` and snapped to device pixels here.
 */
export function drawCandles(
  ctx: CanvasRenderingContext2D,
  items: readonly CandleDrawItem[],
  priceToY: (price: number) => number,
  barSpacing: number,
  dpr: number,
  style: CandleStyle = DEFAULT_CANDLE_STYLE,
): void {
  const bodyW = optimalBarWidth(barSpacing, dpr);
  const wickW = Math.max(1, Math.floor(dpr));

  for (let i = 0; i < items.length; i++) {
    const { x, bar } = items[i];
    // Previous-close colouring needs the bar before this one. The first drawn
    // bar has none in `items`, so it takes the caller's `prevClose` (the bar
    // left of the visible range) and otherwise falls back to open-vs-close:
    // the first bar of history has nothing to compare against, and inventing a
    // reference would make it lie. A non-finite reference (a whitespace gap)
    // falls back too, or every bar after a gap would go down off a NaN test.
    const ref = i > 0 ? items[i - 1].bar.close : items[i].prevClose;
    const up = style.colorByPreviousClose === true && ref !== undefined && Number.isFinite(ref)
      ? bar.close >= ref
      : bar.close >= bar.open;
    const cx = Math.round(x * dpr);
    const yOpen = Math.round(priceToY(bar.open) * dpr);
    const yClose = Math.round(priceToY(bar.close) * dpr);
    const yHigh = Math.round(priceToY(bar.high) * dpr);
    const yLow = Math.round(priceToY(bar.low) * dpr);

    // Per-bar width (volume candles scale the body by relative volume).
    const scale = style.widthScale ? Math.max(0.05, Math.min(1, style.widthScale(bar))) : 1;
    const w = scale === 1 ? bodyW : Math.max(1, Math.round(bodyW * scale));
    const halfW = Math.floor(w / 2);

    if (style.wickVisible) {
      ctx.fillStyle = up ? style.wickUpColor : style.wickDownColor;
      ctx.fillRect(cx - Math.floor(wickW / 2), yHigh, wickW, Math.max(1, yLow - yHigh));
    }

    const top = Math.min(yOpen, yClose);
    const bodyH = Math.max(1, Math.abs(yClose - yOpen));
    const color = up ? style.upColor : style.downColor;
    const borderColor = up ? style.borderUpColor : style.borderDownColor;

    if (style.hollow && up) {
      // Hollow up candle: the outline is the body, so it is drawn whether or not
      // borders are on. With Borders on it takes the border colour like any
      // other candle; with Borders off it falls back to the body colour, since
      // dropping the outline would erase the candle entirely.
      ctx.strokeStyle = style.borderVisible ? borderColor : color;
      ctx.lineWidth = Math.max(1, wickW);
      ctx.strokeRect(cx - halfW + 0.5, top + 0.5, w - 1, bodyH - 1);
    } else {
      const filled = style.bodyVisible !== false;
      if (filled) {
        ctx.fillStyle = color;
        ctx.fillRect(cx - halfW, top, w, bodyH);
      }
      // A filled body takes its border in hollow mode too: in that mode only the
      // up candles go hollow, and the down ones are ordinary filled candles.
      // Below 3px the 1px inset outline would swallow the body, so it is
      // dropped rather than repainting the candle in the border colour. With the
      // body hidden there is no fill to swallow and the outline IS the candle,
      // so that width guard does not apply.
      if (style.borderVisible && (!filled || w >= 3)) {
        ctx.strokeStyle = borderColor;
        ctx.lineWidth = 1;
        ctx.strokeRect(cx - halfW + 0.5, top + 0.5, w - 1, bodyH - 1);
      }
    }
  }
}
