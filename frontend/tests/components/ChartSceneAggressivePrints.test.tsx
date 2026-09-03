/**
 * F1 (block0) regression: aggressive-print overlays, IB-break retest zones,
 * and session time markers must convert print/candle times with the same
 * canonical toISTTimestamp() conversion used by the candle series.
 *
 * Three overlay sites previously computed bare UTC seconds while candles were
 * stored IST-shifted (+5:30). On an IST session range every overlay timestamp
 * landed ~19800s BEFORE the first candle, so timeToCoordinate returned null
 * and the overlays silently vanished.
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import ChartScene from '../../components/ChartScene';
import { OHLCData, ChartConfig } from '../../types';

// IST offset seconds (UTC+5:30) — mirrors frontend/constants.ts
const IST_OFFSET = 19800;

// toISTTimestamp equivalent for assertions
const istTs = (iso: string) => Math.floor(new Date(iso).getTime() / 1000) + IST_OFFSET;

// ---- Mock lightweight-charts with a REAL linear time scale -----------------
// Candles are 1-minute bars; each bar occupies BAR_PX pixels. A time between
// two bars maps proportionally, exactly like lightweight-charts' logical
// scale. This lets us assert "the bubble landed inside the candle range".
const BAR_PX = 10;
let candleTimes: number[] = [];

vi.mock('lightweight-charts', () => {
  const makeLinearTimeScale = () => ({
    fitContent: vi.fn(),
    scrollToPosition: vi.fn(),
    subscribeVisibleLogicalRangeChange: vi.fn(),
    unsubscribeVisibleLogicalRangeChange: vi.fn(),
    getVisibleLogicalRange: vi.fn(() => ({ from: 0, to: 100 })),
    logicalToCoordinate: vi.fn(() => 50),
    options: vi.fn(() => ({ barSpacing: BAR_PX })),
    // Bar i sits at x = i*BAR_PX + BAR_PX/2. Times outside the candle range
    // return null (lightweight-charts behaviour).
    timeToCoordinate: vi.fn((t: number) => {
      const times = candleTimes;
      if (!times.length) return null;
      if (t < times[0] || t > times[times.length - 1]) return null;
      const idx = times.indexOf(t);
      if (idx >= 0) return idx * BAR_PX + BAR_PX / 2;
      let lo = 0;
      while (lo < times.length - 1 && times[lo + 1] < t) lo++;
      const hi = Math.min(lo + 1, times.length - 1);
      const span = Math.max(1, times[hi] - times[lo]);
      const frac = (t - times[lo]) / span;
      return lo * BAR_PX + BAR_PX / 2 + frac * BAR_PX;
    }),
  });
  return {
    createChart: vi.fn(() => ({
      addCandlestickSeries: vi.fn(() => ({
        setData: vi.fn((points: Array<{ time: number }>) => {
          candleTimes = points.map(p => Number(p.time));
        }),
        update: vi.fn(),
        removePriceLine: vi.fn(),
        createPriceLine: vi.fn(() => ({})),
        setMarkers: vi.fn(),
        applyOptions: vi.fn(),
        priceToCoordinate: vi.fn((price: number) => Math.max(0, Math.min(300, 300 - price / 100))),
      })),
      addHistogramSeries: vi.fn(() => ({
        setData: vi.fn(),
        update: vi.fn(),
        priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
        applyOptions: vi.fn(),
      })),
      addLineSeries: vi.fn(() => ({
        setData: vi.fn(),
        applyOptions: vi.fn(),
      })),
      remove: vi.fn(),
      applyOptions: vi.fn(),
      timeScale: makeLinearTimeScale,
      priceScale: vi.fn(() => ({ applyOptions: vi.fn(), width: vi.fn(() => 600) })),
    })),
    ColorType: { Solid: 'solid' },
    CrosshairMode: { Normal: 0 },
    LineStyle: { Solid: 0, Dashed: 2, Dotted: 3 },
  };
});

global.ResizeObserver = class ResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
};

type ArcCall = { x: number; y: number; radius: number };
type RectCall = { x: number; y: number; w: number; h: number };
const arcCalls: ArcCall[] = [];
const rectCalls: RectCall[] = [];

const makeCtx = () => ({
  clearRect: vi.fn(),
  beginPath: vi.fn(),
  arc: vi.fn((x: number, y: number, radius: number) => {
    arcCalls.push({ x, y, radius });
  }),
  fill: vi.fn(),
  stroke: vi.fn(),
  moveTo: vi.fn(),
  lineTo: vi.fn(),
  fillRect: vi.fn((x: number, y: number, w: number, h: number) => {
    rectCalls.push({ x, y, w, h });
  }),
  fillText: vi.fn(),
  setLineDash: vi.fn(),
  createRadialGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
});

// jsdom canvas has no 2d context — patch per-test so captures stay isolated.
beforeAll(() => {
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    value: function () { return makeCtx(); },
  });
});

beforeEach(() => {
  arcCalls.length = 0;
  rectCalls.length = 0;
});

// IST-session range: 2024-01-01 (Monday) 09:15 IST == 03:45Z
const SESSION_START_ISO = '2024-01-01T03:45:00Z';
const N_BARS = 60;

const mockData: OHLCData[] = Array.from({ length: N_BARS }, (_, i) => {
  const d = new Date(new Date(SESSION_START_ISO).getTime() + i * 60_000);
  return {
    time: d.toISOString().replace('.000Z', 'Z'),
    open: 25000,
    high: 25100,
    low: 24900,
    close: 25000 + i,
    volume: 1000,
    vwap: 25000,
    takerBuyVolume: 600,
    delta: 200,
  } as OHLCData;
});

const defaultConfig: ChartConfig = {
  symbol: 'NIFTY',
  bullColor: '#22c55e',
  bearColor: '#ef4444',
  showVolumeProfile: false,
  vpMode: 'combined',
};

const waitForPaint = () => new Promise(r => setTimeout(r, 60));

describe('ChartScene aggressive-print overlays (IST alignment)', () => {
  it('draws each aggressive print at a non-null x within the candle range', async () => {
    const prints = [
      { time: mockData[10].time, price: 25050, volume: 500, side: 'BUY' },
      { time: mockData[20].time, price: 25080, volume: 1200, side: 'SELL' },
      { time: mockData[25].time, price: 25060, volume: 300, side: 'BUY' },
    ];
    const amt = {
      poc: 25050,
      valueAreaHigh: 25100,
      valueAreaLow: 25000,
      profile: [{ price: 25000, volume: 100, delta: 10 }],
      legProfile: [],
      aggressivePrints: prints,
    };

    render(<ChartScene data={mockData} config={defaultConfig} positions={[]} amtAnalysis={amt as any} />);
    await waitForPaint();

    expect(candleTimes.length).toBe(N_BARS);
    expect(arcCalls.length).toBeGreaterThanOrEqual(prints.length);
    const firstCandleX = BAR_PX / 2;
    const lastCandleX = (N_BARS - 1) * BAR_PX + BAR_PX / 2;
    for (const c of arcCalls.slice(0, prints.length)) {
      expect(Number.isFinite(c.x)).toBe(true);
      expect(c.x).toBeGreaterThanOrEqual(firstCandleX);
      expect(c.x).toBeLessThanOrEqual(lastCandleX);
    }
  });

  it('aligns the IB break retest zone with the break candle instead of vanishing', async () => {
    // Close crosses UP through breakLevel 25040 exactly at bar 20.
    const data = mockData.map((d, i) => ({
      ...d,
      close: i < 20 ? 25000 : 25060,
    }));
    const amt = {
      poc: 25050,
      valueAreaHigh: 25100,
      valueAreaLow: 25000,
      breakDirection: 'UP',
      breakLevel: 25040,
      profile: [{ price: 25000, volume: 100, delta: 10 }],
      legProfile: [],
      aggressivePrints: [],
    };

    render(<ChartScene data={data} config={defaultConfig} positions={[]} amtAnalysis={amt as any} />);
    await waitForPaint();

    // The retest-zone box starts AT the break candle's x (> first candle).
    // With bare-UTC math the zone silently disappeared because
    // timeToCoordinate returned null for the shifted timestamp.
    expect(rectCalls.length).toBeGreaterThan(0);
    const zoneLeftValues = rectCalls.map(r => r.x);
    expect(Math.max(...zoneLeftValues)).toBeGreaterThanOrEqual(BAR_PX / 2);
    expect(Math.max(...zoneLeftValues)).toBeLessThanOrEqual((N_BARS - 1) * BAR_PX + BAR_PX / 2);
  });
});
