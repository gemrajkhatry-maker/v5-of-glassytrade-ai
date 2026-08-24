import { describe, it, expect } from 'vitest';
import { ChartTable, tableOrigin } from '../src/primitives/table';
import { makeCtx } from './helpers/fake-ctx';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

function rc(dpr = 1): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 0, max: 100 });
  const timeScale = new TimeScale();
  timeScale.setWidth(600);
  return {
    timeScale, priceScale, dataLayer: new DataLayer(),
    plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr, theme: darkTheme,
  };
}

const grid = [
  [{ text: 'Year' }, { text: 'Jan' }],
  [{ text: '2024', bgColor: '#222222' }, { text: '1.2%', bgColor: '#26a69a' }],
];

describe('tableOrigin', () => {
  it('pins each corner inside the margin', () => {
    // 100x40 table in a 600x400 plot, margin 8.
    expect(tableOrigin('top-left', 8, 100, 40, 600, 400)).toEqual({ x: 8, y: 8 });
    expect(tableOrigin('bottom-right', 8, 100, 40, 600, 400)).toEqual({ x: 492, y: 352 });
    expect(tableOrigin('top-right', 8, 100, 40, 600, 400)).toEqual({ x: 492, y: 8 });
    expect(tableOrigin('bottom-left', 8, 100, 40, 600, 400)).toEqual({ x: 8, y: 352 });
  });

  it('centres on the axis the keyword names, ignoring the margin there', () => {
    expect(tableOrigin('middle-center', 8, 100, 40, 600, 400)).toEqual({ x: 250, y: 180 });
    expect(tableOrigin('top-center', 8, 100, 40, 600, 400)).toEqual({ x: 250, y: 8 });
    expect(tableOrigin('middle-left', 8, 100, 40, 600, 400)).toEqual({ x: 8, y: 180 });
  });
});

describe('ChartTable', () => {
  it('draws one filled rect per cell that declares a background', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({ cellWidth: 50, cellHeight: 20 });
    t.setRows(grid);
    t.draw(ctx, rc());
    // Only the second row's two cells carry a bgColor; a cell without one is
    // left transparent so the pane shows through.
    expect(rec.ops.filter((o) => o.type === 'fillRect')).toHaveLength(2);
  });

  it('draws nothing at all when there are no rows', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable();
    t.draw(ctx, rc());
    expect(rec.ops).toHaveLength(0);
  });

  it('scales geometry by the device ratio', () => {
    const at = (dpr: number): number => {
      const { ctx, rec } = makeCtx();
      const t = new ChartTable({ position: 'top-left', margin: 10, cellWidth: 50, cellHeight: 20 });
      t.setRows(grid);
      t.draw(ctx, rc(dpr));
      return rec.ops.find((o) => o.type === 'fillRect')?.args[0] ?? -1;
    };
    // The first filled cell sits at x = margin, so its bitmap x is margin * dpr.
    expect(at(1)).toBe(10);
    expect(at(2)).toBe(20);
  });

  it('derives readable ink from the cell background when no text colour is given', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable();
    // A near-white fill must not take white text.
    t.setRows([[{ text: 'x', bgColor: '#ffffff' }]]);
    t.draw(ctx, rc());
    const inks = rec.ops.filter((o) => o.type === 'fillText').map((o) => o.fillStyle);
    expect(inks[0]).not.toBe('#ffffff');
  });

  it('honours a per-column width array', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: [30, 90], cellHeight: 20 });
    t.setRows([[{ text: 'a', bgColor: '#111' }, { text: 'b', bgColor: '#222' }]]);
    t.draw(ctx, rc());
    const rects = rec.ops.filter((o) => o.type === 'fillRect');
    expect(rects[0].args[2]).toBe(30); // first column width
    expect(rects[1].args[0]).toBe(30); // second column starts where the first ends
    expect(rects[1].args[2]).toBe(90);
  });

  it('is a top-layer primitive so it never hides under a series', () => {
    expect(new ChartTable().zOrder()).toBe('top');
  });

  it('hit-tests only inside its own rect, and only when given an id', () => {
    const { ctx } = makeCtx();
    const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 50, cellHeight: 20, id: 'seasonality' });
    t.setRows(grid);
    t.draw(ctx, rc());
    expect(t.hitTest(10, 10)?.externalId).toBe('seasonality');
    expect(t.hitTest(500, 300)).toBeNull();

    const anon = new ChartTable({ position: 'top-left', margin: 0 });
    anon.setRows(grid);
    anon.draw(ctx, rc());
    expect(anon.hitTest(10, 10)).toBeNull();
  });

  it('reports no hit before it has ever drawn', () => {
    const t = new ChartTable({ id: 'x' });
    t.setRows(grid);
    expect(t.hitTest(0, 0)).toBeNull();
  });

  it('tolerates ragged rows, drawing each to its own length', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({ cellWidth: 40, cellHeight: 20 });
    t.setRows([
      [{ text: 'a', bgColor: '#111' }, { text: 'b', bgColor: '#111' }, { text: 'c', bgColor: '#111' }],
      [{ text: 'd', bgColor: '#111' }],
    ]);
    t.draw(ctx, rc());
    expect(rec.ops.filter((o) => o.type === 'fillRect')).toHaveLength(4);
  });
});

describe('ChartTable percentage sizing', () => {
  it('stretches to a share of the plot width, keeping column proportions', () => {
    const { ctx, rec } = makeCtx();
    // Declared 30/90 is a 1:3 split. At 100% of a 600px plot that must become
    // 150/450, not 30/90 nudged over.
    const t = new ChartTable({
      position: 'top-left', margin: 0, cellWidth: [30, 90], cellHeight: 20, widthPercent: 100,
    });
    t.setRows([[{ text: 'a', bgColor: '#111' }, { text: 'b', bgColor: '#222' }]]);
    t.draw(ctx, rc());
    const rects = rec.ops.filter((o) => o.type === 'fillRect');
    expect(rects[0].args[2]).toBe(150);
    expect(rects[1].args[0]).toBe(150);
    expect(rects[1].args[2]).toBe(450);
  });

  it('divides a share of the plot height evenly across the rows', () => {
    const { ctx, rec } = makeCtx();
    // 50% of a 400px plot is 200px over 4 rows, so each row is 50px.
    const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 40, heightPercent: 50 });
    t.setRows(Array.from({ length: 4 }, () => [{ text: 'x', bgColor: '#111' }]));
    t.draw(ctx, rc());
    const rects = rec.ops.filter((o) => o.type === 'fillRect');
    expect(rects[0].args[3]).toBe(50);
    expect(rects[1].args[1]).toBe(50); // second row starts where the first ends
  });

  it('falls back to the fixed cell sizes when a percentage is zero or absent', () => {
    const at = (opts: Record<string, unknown>): number[] => {
      const { ctx, rec } = makeCtx();
      const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 40, cellHeight: 20, ...opts });
      t.setRows([[{ text: 'x', bgColor: '#111' }]]);
      t.draw(ctx, rc());
      const r = rec.ops.find((o) => o.type === 'fillRect');
      return [r?.args[2] ?? -1, r?.args[3] ?? -1];
    };
    expect(at({})).toEqual([40, 20]);
    expect(at({ widthPercent: 0, heightPercent: 0 })).toEqual([40, 20]);
  });

  it('shrinks the type rather than overflowing a short stretched row', () => {
    const { ctx, rec } = makeCtx();
    // 10% of 400px over 10 rows is a 4px row; an 11px font would spill.
    const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 40, fontSize: 11, heightPercent: 10 });
    t.setRows(Array.from({ length: 10 }, () => [{ text: 'x' }]));
    t.draw(ctx, rc());
    const fonts = rec.ops.filter((o) => o.type === 'fillText');
    expect(fonts.length).toBeGreaterThan(0);
    // 4px row * 0.62 floors to 2px, well under the declared 11.
    expect(ctx.font).toContain('2px');
  });
});

describe('ChartTable row weights', () => {
  it('splits a stretched height in proportion to the weights', () => {
    const { ctx, rec } = makeCtx();
    // Weights 1/0.5/1 over 200px (50% of a 400px plot): 80 / 40 / 80.
    const t = new ChartTable({
      position: 'top-left', margin: 0, cellWidth: 40, heightPercent: 50,
      rowWeights: [1, 0.5, 1],
    });
    t.setRows([[{ text: 'a', bgColor: '#111' }], [{ text: 'b', bgColor: '#222' }], [{ text: 'c', bgColor: '#333' }]]);
    t.draw(ctx, rc());
    const r = rec.ops.filter((o) => o.type === 'fillRect');
    expect(r.map((o) => o.args[3])).toEqual([80, 40, 80]);
    expect(r.map((o) => o.args[1])).toEqual([0, 80, 120]);
  });

  it('treats a missing, zero or negative weight as 1', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({
      position: 'top-left', margin: 0, cellWidth: 40, cellHeight: 10,
      rowWeights: [2, 0, -1],
    });
    t.setRows([[{ text: 'a', bgColor: '#111' }], [{ text: 'b', bgColor: '#222' }], [{ text: 'c', bgColor: '#333' }]]);
    t.draw(ctx, rc());
    expect(rec.ops.filter((o) => o.type === 'fillRect').map((o) => o.args[3])).toEqual([20, 10, 10]);
  });
});
