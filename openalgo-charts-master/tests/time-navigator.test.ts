import { describe, it, expect, vi } from 'vitest';
import { TimeNavigator } from '../src/primitives/time-navigator';
import { Chart } from '../src/core/chart';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

/**
 * The hover-revealed zoom / step controls above the time axis. Hidden until the
 * pointer nears the bottom of the chart, then faded in.
 */

function rc(dpr = 1): PrimitiveRenderContext {
  return {
    dpr,
    plotWidth: 800, plotHeight: 400, priceAxisWidth: 56,
    timeScale: {} as never,
    priceScale: {} as never,
    dataLayer: {} as never,
    theme: { axisText: '#8b91a7', axisLine: '#2a3046', background: '#0d0e12' },
  } as unknown as PrimitiveRenderContext;
}

/** A canvas stub that records what was painted and at what alpha. */
function recorder() {
  const ops: { type: string; alpha: number }[] = [];
  const ctx: Record<string, unknown> = {
    canvas: {}, globalAlpha: 1,
    fillStyle: '', strokeStyle: '', lineWidth: 1, lineCap: '', lineJoin: '',
    font: '', textAlign: '', textBaseline: '',
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, setLineDash() {},
    roundRect() {},
    measureText: () => ({ width: 40 }),
    fill() { ops.push({ type: 'fill', alpha: ctx.globalAlpha as number }); },
    stroke() { ops.push({ type: 'stroke', alpha: ctx.globalAlpha as number }); },
    fillText() { ops.push({ type: 'fillText', alpha: ctx.globalAlpha as number }); },
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, ops };
}

describe('TimeNavigator', () => {
  it('draws nothing until the pointer reaches the reveal band', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    const { ctx, ops } = recorder();

    nav.draw(ctx, rc());                       // never hovered
    expect(ops).toHaveLength(0);

    nav.setPointer({ x: 400, y: 100 });        // well above the band
    nav.draw(ctx, rc());
    expect(ops).toHaveLength(0);

    nav.setPointer({ x: 400, y: 380 });        // inside the bottom 64px
    nav.draw(ctx, rc());
    expect(ops.length).toBeGreaterThan(0);
  });

  it('hides again when the pointer leaves', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    nav.setPointer({ x: 400, y: 380 });
    const shown = recorder();
    nav.draw(shown.ctx, rc());
    expect(shown.ops.length).toBeGreaterThan(0);

    nav.setPointer(null);
    const hidden = recorder();
    nav.draw(hidden.ctx, rc());
    expect(hidden.ops).toHaveLength(0);
  });

  it('fades in over time rather than snapping', () => {
    let t = 0;
    const nav = new TimeNavigator({ fadeSeconds: 0.2 }, () => t);
    nav.setPointer({ x: 400, y: 380 });

    // First frame establishes the clock; nothing has elapsed yet.
    nav.draw(recorder().ctx, rc());
    t = 100;                                    // 0.1s -> halfway
    const mid = recorder();
    nav.draw(mid.ctx, rc());
    const alphas = mid.ops.map((o) => o.alpha);
    expect(alphas.length).toBeGreaterThan(0);
    expect(Math.max(...alphas)).toBeGreaterThan(0);
    expect(Math.max(...alphas)).toBeLessThan(1);
    expect(nav.animating()).toBe(true);

    t = 400;                                    // well past the fade
    nav.draw(recorder().ctx, rc());
    expect(nav.animating()).toBe(false);
  });

  it('hit-tests its buttons only while visible', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    const { ctx } = recorder();

    nav.setPointer({ x: 400, y: 380 });
    nav.draw(ctx, rc());
    // Buttons are centred on the plot; probe the middle of the row.
    const y = 400 - 10 - 26 / 2;
    let found: string[] = [];
    for (let x = 300; x < 500; x++) {
      const h = nav.hitTest(x, y);
      if (h && !found.includes(h.externalId)) found.push(h.externalId);
    }
    expect(found.sort()).toEqual([
      'timenav::panLeftBar', 'timenav::panRightBar', 'timenav::zoomIn', 'timenav::zoomOut',
    ]);

    // Hidden: the same probe must find nothing, so the chart body keeps its clicks.
    nav.setPointer(null);
    nav.draw(ctx, rc());
    found = [];
    for (let x = 300; x < 500; x++) if (nav.hitTest(x, y)) found.push('hit');
    expect(found).toHaveLength(0);
  });

  it('reports pointer as a cursor hint on a button', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    nav.setPointer({ x: 400, y: 380 });
    nav.draw(recorder().ctx, rc());
    const y = 400 - 10 - 26 / 2;
    for (let x = 300; x < 500; x++) {
      const h = nav.hitTest(x, y);
      if (h) { expect(h.cursor).toBe('pointer'); return; }
    }
    throw new Error('no button found');
  });
});

// ── integration: the chart owns one and its buttons drive the time scale ─────

function mountChart(options: Record<string, unknown> = {}) {
  const doc = fakeDocument();
  const container = doc.createElement('div') as unknown as Record<string, unknown>;
  container.clientWidth = 800;
  container.clientHeight = 600;
  container.ownerDocument = doc;
  container.contains = () => false;
  container.tabIndex = 0;

  const chart = new Chart(container as unknown as HTMLElement, {
    document: doc, pixelRatio: () => 1,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
    ...options,
  });
  chart.addSeries('candlestick').setData([
    { time: 1000, open: 10, high: 12, low: 8, close: 11 },
    { time: 1060, open: 11, high: 13, low: 9, close: 12 },
    { time: 1120, open: 12, high: 14, low: 10, close: 13 },
  ]);
  return { chart, el: container as unknown as FakeElement };
}

function stubEnv(): void {
  vi.stubGlobal('window', {});
  vi.stubGlobal('requestAnimationFrame', () => 0);
  vi.stubGlobal('cancelAnimationFrame', () => {});
}

describe('chart time navigator', () => {
  it('is present by default and can be turned off', () => {
    stubEnv();
    const on = mountChart().chart;
    const has = (c: Chart): boolean =>
      c.panes().some((p) => p.primitives().some((x) => x instanceof TimeNavigator));
    expect(has(on)).toBe(true);

    const off = mountChart({ timeNavigator: false }).chart;
    expect(has(off)).toBe(false);
    vi.unstubAllGlobals();
  });

  it('zoom and step buttons move the time scale', () => {
    stubEnv();
    const { chart } = mountChart();
    const nav = chart.panes()
      .flatMap((p) => p.primitives())
      .find((x) => x instanceof TimeNavigator) as TimeNavigator;

    // Reveal, then paint so the buttons have geometry to hit.
    nav.setPointer({ x: 300, y: 560 });
    chart.applySize(800, 600);

    // A fresh chart sits at max bar spacing, so zoom *out* first — zooming in
    // from the clamp would look like a no-op and prove nothing.
    const beforeSpacing = chart.timeScale.barSpacing;
    (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction('timenav::zoomOut');
    const zoomedOut = chart.timeScale.barSpacing;
    expect(zoomedOut).toBeLessThan(beforeSpacing);

    (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction('timenav::zoomIn');
    expect(chart.timeScale.barSpacing).toBeGreaterThan(zoomedOut);

    // One bar per step, in each direction.
    const offset = chart.timeScale.rightOffset;
    (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction('timenav::panRightBar');
    expect(chart.timeScale.rightOffset).toBe(offset + 1);
    (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction('timenav::panLeftBar');
    expect(chart.timeScale.rightOffset).toBe(offset);
    vi.unstubAllGlobals();
  });

  it('keeps the navigator on the bottom pane when panes are added', () => {
    stubEnv();
    const { chart } = mountChart();
    const paneOf = (): number =>
      chart.panes().findIndex((p) => p.primitives().some((x) => x instanceof TimeNavigator));
    expect(paneOf()).toBe(0);

    // A second pane pushes the time axis down; the controls must follow it.
    chart.addSeries('histogram', { paneIndex: 1 })
      .setData([{ time: 1000, open: 0, high: 5, low: 0, close: 5 }]);
    chart.applySize(800, 600);
    expect(paneOf()).toBe(1);
    expect(chart.panes()[0].primitives().some((x) => x instanceof TimeNavigator)).toBe(false);
    vi.unstubAllGlobals();
  });
});
