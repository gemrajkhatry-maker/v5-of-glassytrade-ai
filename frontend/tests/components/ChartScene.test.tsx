import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ChartScene from '../../components/ChartScene';
import { OHLCData, ChartConfig } from '../../types';

// Mock lightweight-charts
vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => ({
    addCandlestickSeries: vi.fn(() => ({
      setData: vi.fn(),
      update: vi.fn(),
      removePriceLine: vi.fn(),
      createPriceLine: vi.fn(() => ({})),
      setMarkers: vi.fn(),
      applyOptions: vi.fn(),
    })),
    addHistogramSeries: vi.fn(() => ({
      setData: vi.fn(),
      update: vi.fn(),
      priceScale: vi.fn(() => ({
        applyOptions: vi.fn(),
      })),
    })),
    remove: vi.fn(),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({
      scrollToPosition: vi.fn(),
      subscribeVisibleLogicalRangeChange: vi.fn(),
      unsubscribeVisibleLogicalRangeChange: vi.fn(),
      getVisibleLogicalRange: vi.fn(() => ({ from: 0, to: 100 })),
      logicalToCoordinate: vi.fn(() => 50),
      priceToCoordinate: vi.fn(() => 100),
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
          probability: 0.8,
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
});
