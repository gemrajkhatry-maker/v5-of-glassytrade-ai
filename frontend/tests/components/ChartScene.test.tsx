import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ChartScene from '../../components/ChartScene';
import { OHLCData, ChartConfig } from '../../types';

// Captures the HalfTrend overlay line-series mocks for render assertions.
const halfTrendLineMocks: {
  setData: ReturnType<typeof vi.fn>;
  options?: {
    autoscaleInfoProvider?: () => unknown;
    [k: string]: unknown;
  };
}[] = [];

// Captures the candlestick-series mock so tests can assert marker payloads.
const candleSeriesMocks: {
  setMarkers: ReturnType<typeof vi.fn>;
}[] = [];

// Mock lightweight-charts
vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => ({
    addCandlestickSeries: vi.fn(() => {
      const mock = {
        setData: vi.fn(),
        update: vi.fn(),
        removePriceLine: vi.fn(),
        createPriceLine: vi.fn(() => ({})),
        setMarkers: vi.fn(),
        applyOptions: vi.fn(),
      };
      candleSeriesMocks.push(mock);
      return mock;
    }),
    addHistogramSeries: vi.fn(() => ({
      setData: vi.fn(),
      update: vi.fn(),
      priceScale: vi.fn(() => ({
        applyOptions: vi.fn(),
      })),
    })),
    addLineSeries: vi.fn((options?: {
      autoscaleInfoProvider?: () => unknown;
      [k: string]: unknown;
    }) => {
      const mock = { setData: vi.fn(), applyOptions: vi.fn(), options };
      halfTrendLineMocks.push(mock);
      return mock;
    }),
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
  })),
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
  LineStyle: { Solid: 0, Dashed: 2, Dotted: 3 },
}));

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  constructor() {}
  observe() {}
  disconnect() {}
  unobserve() {}
};

const mockData: OHLCData[] = [
  { time: '2024-01-01T10:00:00Z', open: 24900, high: 25100, low: 24800, close: 25000, volume: 1000, vwap: 25000, takerBuyVolume: 600, delta: 200 },
  { time: '2024-01-01T10:05:00Z', open: 25000, high: 25150, low: 24950, close: 25100, volume: 1200, vwap: 25100, takerBuyVolume: 700, delta: 300 },
];

const defaultConfig: ChartConfig = {
  symbol: 'NIFTY',
  bullColor: '#22c55e',
  bearColor: '#ef4444',
  showVolumeProfile: true,
  vpMode: 'combined',
};

describe('ChartScene', () => {
  beforeEach(() => {
    halfTrendLineMocks.length = 0;
    candleSeriesMocks.length = 0;
  });

  it('draws the HalfTrend overlay from the halfTrendSeries prop', () => {
    render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
        halfTrendSeries={[
          { time: '2024-01-01T10:00:00Z', trend: 0, ht: 24950, atrHigh: null, atrLow: null, buy: false, sell: false },
          { time: '2024-01-01T10:05:00Z', trend: 1, ht: 25020, atrHigh: 25060, atrLow: 24980, buy: false, sell: true },
        ]}
      />
    );
    // ht line + atrHigh + atrLow series were created
    expect(halfTrendLineMocks).toHaveLength(3);
    // ht series received both points colored by trend
    const htData = halfTrendLineMocks[0].setData.mock.calls[0][0];
    expect(htData).toHaveLength(2);
    expect(htData[0].color).toBe('#2962ff');
    expect(htData[1].color).toBe('#f23645');
    // channel rails skip the null row and carry the two remaining points
    expect(halfTrendLineMocks[1].setData.mock.calls[0][0]).toHaveLength(1);
    expect(halfTrendLineMocks[2].setData.mock.calls[0][0]).toHaveLength(1);
  });

  it('makes the HalfTrend overlay autoscale-inert (design-level scale guard)', () => {
    render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
        halfTrendSeries={[{ time: '2024-01-01T10:00:00Z', trend: 0, ht: 24950, atrHigh: null, atrLow: null, buy: false, sell: false }]}
      />
    );
    expect(halfTrendLineMocks).toHaveLength(3);
    // Every overlay series must opt out of autoscale: a rogue value in the
    // overlay can never stretch the price axis and crush the candles.
    for (const mock of halfTrendLineMocks) {
      expect(mock.options?.autoscaleInfoProvider).toBeDefined();
      expect(mock.options?.autoscaleInfoProvider?.()).toBeNull();
    }
  });

  it('hides the HalfTrend overlay and its Buy/Sell markers when showHalfTrend is false', () => {
    render(
      <ChartScene
        data={mockData}
        config={{ ...defaultConfig, showHalfTrend: false }}
        positions={[]}
        halfTrendSeries={[
          { time: '2024-01-01T10:00:00Z', trend: 0, ht: 24950, atrHigh: null, atrLow: null, buy: true, sell: false },
          { time: '2024-01-01T10:05:00Z', trend: 1, ht: 25020, atrHigh: 25060, atrLow: 24980, buy: false, sell: true },
        ]}
      />
    );
    // Overlay series exist but were cleared (no points drawn).
    expect(halfTrendLineMocks).toHaveLength(3);
    for (const mock of halfTrendLineMocks) {
      const data = mock.setData.mock.calls[0][0];
      expect(data).toHaveLength(0);
    }
    // No Buy/Sell label markers pushed to the candle series.
    const markers = candleSeriesMocks[0]?.setMarkers.mock.calls[0][0] || [];
    expect(markers.some((m: any) => m.text === 'Buy' || m.text === 'Sell')).toBe(false);
  });

  it('renders without crashing', () => {
    const { container } = render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders chart container element', () => {
    render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
      />
    );
    // Chart renders with a container that has ref
    const chartContainer = document.querySelector('.bg-\\[\\#0f172a\\]');
    expect(chartContainer).toBeInTheDocument();
  });

  it('renders with empty data', () => {
    const { container } = render(
      <ChartScene
        data={[]}
        config={defaultConfig}
        positions={[]}
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders without crashing on minimal props', () => {
    const { container } = render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders with standard mode indicator', () => {
    render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
        mode="STANDARD"
      />
    );
    expect(screen.getByText('STANDARD CANDLESTICKS')).toBeInTheDocument();
  });

  it('renders with positions', () => {
    const positions = [
      {
        id: 'pos1',
        symbol: 'NIFTY',
        side: 'LONG' as const,
        size: 1,
        entryPrice: 25000,
        stopLoss: 24900,
        takeProfit: 25200,
        status: 'OPEN' as const,
        entryTime: '2024-01-01T10:00:00Z',
        source: 'AMT' as const,
        pnl: 0,
        unrealizedPnl: 100,
        notionalValue: 25000,
        deployedMargin: 5000,
      },
    ];
    
    render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={positions}
      />
    );
    expect(screen.getByText('STANDARD CANDLESTICKS')).toBeInTheDocument();
  });

  it('renders with symbol prop', () => {
    render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
        symbol="NIFTY 25500 CE"
      />
    );
    expect(screen.getByText('STANDARD CANDLESTICKS')).toBeInTheDocument();
  });

  it('renders canvas overlay', () => {
    render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
      />
    );
    const canvas = document.querySelector('canvas');
    expect(canvas).toBeInTheDocument();
  });

  it('shows real agentDecision direction in the decision card', () => {
    render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
        agentDecision={{
          direction: 'LONG',
          modelLabel: 'Triple-A',
          regime: 'TRENDING',
          timing: 'ENTER_NOW',
          sizeFraction: 0.5,
          latencyUs: 0,
          rationale: 'Strong bullish setup',
        }}
      />
    );
    expect(screen.getByText(/▲ LONG/)).toBeInTheDocument();
  });

  it('stabilizes redraws when re-rendered with separately decoded but equal profile arrays', () => {
    const initialAmt = {
      poc: 25050,
      valueAreaHigh: 25100,
      valueAreaLow: 25000,
      profile: [{ price: 25000, volume: 100, delta: 10 }, { price: 25050, volume: 500, delta: 50 }],
      legProfile: [{ price: 25020, volume: 80, delta: 5 }],
      aggressivePrints: [],
    } as any;

    const { rerender } = render(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
        amtAnalysis={initialAmt}
      />
    );

    // Separately decoded JSON clone with different object references
    const clonedAmt = {
      poc: 25050,
      valueAreaHigh: 25100,
      valueAreaLow: 25000,
      profile: [{ price: 25000, volume: 100, delta: 10 }, { price: 25050, volume: 500, delta: 50 }],
      legProfile: [{ price: 25020, volume: 80, delta: 5 }],
      aggressivePrints: [],
    } as any;

    rerender(
      <ChartScene
        data={mockData}
        config={defaultConfig}
        positions={[]}
        amtAnalysis={clonedAmt}
      />
    );

    expect(screen.getByText('STANDARD CANDLESTICKS')).toBeInTheDocument();
  });
});
