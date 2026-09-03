import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import ChartScene from '../../components/ChartScene';
import { OHLCData, ChartConfig } from '../../types';

// Track series mock calls
let candleSeriesMock: any;
let volumeSeriesMock: any;

vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => {
    candleSeriesMock = {
      setData: vi.fn(),
      update: vi.fn(),
      removePriceLine: vi.fn(),
      createPriceLine: vi.fn(() => ({})),
      setMarkers: vi.fn(),
      applyOptions: vi.fn(),
    };
    volumeSeriesMock = {
      setData: vi.fn(),
      update: vi.fn(),
      priceScale: vi.fn(() => ({
        applyOptions: vi.fn(),
      })),
    };
    const lineSeriesMock = {
      setData: vi.fn(),
      applyOptions: vi.fn(),
    };
    return {
      addCandlestickSeries: vi.fn(() => candleSeriesMock),
      addHistogramSeries: vi.fn(() => volumeSeriesMock),
      addLineSeries: vi.fn(() => lineSeriesMock),
      remove: vi.fn(),
      applyOptions: vi.fn(),
      timeScale: vi.fn(() => ({
        fitContent: vi.fn(),
        scrollToPosition: vi.fn(),
        subscribeVisibleLogicalRangeChange: vi.fn(),
        unsubscribeVisibleLogicalRangeChange: vi.fn(),
        getVisibleLogicalRange: vi.fn(() => ({ from: 0, to: 100 })),
        logicalToCoordinate: vi.fn(() => 50),
        priceToCoordinate: vi.fn(() => 100),
        timeToCoordinate: vi.fn(() => 50),
        options: vi.fn(() => ({ barSpacing: 6 })),
      })),
      priceScale: vi.fn(() => ({
        applyOptions: vi.fn(),
      })),
    };
  }),
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
  LineStyle: { Solid: 0, Dashed: 2, Dotted: 3 },
}));

global.ResizeObserver = class ResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
} as any;

const sampleData: OHLCData[] = [
  { time: '2026-08-27T10:00:00+05:30', open: 100, high: 105, low: 99, close: 104, volume: 1000, vwap: 102, takerBuyVolume: 600, delta: 200 },
  { time: '2026-08-27T10:05:00+05:30', open: 104, high: 108, low: 103, close: 107, volume: 1200, vwap: 105, takerBuyVolume: 700, delta: 200 },
];

describe('ChartScene Dual-Timeframe & Tick Isolation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: sampleData }),
      })
    );
  });

  it('1m chart ignores 5m ticks (barIntervalSec === 300)', () => {
    const tickBus = new EventTarget();
    const config: ChartConfig = {
      symbol: 'TEST',
      interval: '1m',
      bullColor: '#22c55e',
      bearColor: '#ef4444',
      showVolumeProfile: false,
      vpMode: 'off',
    };

    render(
      <ChartScene
        data={sampleData}
        tickBus={tickBus}
        symbol="TEST"
        config={config}
        positions={[]}
      />
    );

    // Send a 5m tick (300s)
    const tick5m = {
      time: '2026-08-27T10:10:00+05:30',
      open: 107,
      high: 110,
      low: 106,
      close: 109,
      volume: 500,
      barIntervalSec: 300,
    };

    tickBus.dispatchEvent(new CustomEvent('tick', { detail: { symbol: 'TEST', tick: tick5m } }));

    // 1m chart should NOT call update for 5m tick
    expect(candleSeriesMock.update).not.toHaveBeenCalled();
  });

  it('1m chart accepts 1m ticks (barIntervalSec === 60)', () => {
    const tickBus = new EventTarget();
    const config: ChartConfig = {
      symbol: 'TEST',
      interval: '1m',
      bullColor: '#22c55e',
      bearColor: '#ef4444',
      showVolumeProfile: false,
      vpMode: 'off',
    };

    render(
      <ChartScene
        data={sampleData}
        tickBus={tickBus}
        symbol="TEST"
        config={config}
        positions={[]}
      />
    );

    // Send a 1m tick (60s)
    const tick1m = {
      time: '2026-08-27T10:10:00+05:30',
      open: 107,
      high: 108,
      low: 106,
      close: 108,
      volume: 100,
      barIntervalSec: 60,
    };

    tickBus.dispatchEvent(new CustomEvent('tick', { detail: { symbol: 'TEST', tick: tick1m } }));

    // 1m chart SHOULD call update for matching 1m tick
    expect(candleSeriesMock.update).toHaveBeenCalled();
  });

  it('5m chart accepts 5m ticks (barIntervalSec === 300)', () => {
    const tickBus = new EventTarget();
    const config: ChartConfig = {
      symbol: 'TEST',
      interval: '5m',
      bullColor: '#22c55e',
      bearColor: '#ef4444',
      showVolumeProfile: true,
      vpMode: 'session',
    };

    render(
      <ChartScene
        data={sampleData}
        tickBus={tickBus}
        symbol="TEST"
        config={config}
        positions={[]}
      />
    );

    // Send a 5m tick (300s)
    const tick5m = {
      time: '2026-08-27T10:10:00+05:30',
      open: 107,
      high: 110,
      low: 106,
      close: 109,
      volume: 500,
      barIntervalSec: 300,
    };

    tickBus.dispatchEvent(new CustomEvent('tick', { detail: { symbol: 'TEST', tick: tick5m } }));

    // 5m chart SHOULD call update for matching 5m tick
    expect(candleSeriesMock.update).toHaveBeenCalled();
  });
});
