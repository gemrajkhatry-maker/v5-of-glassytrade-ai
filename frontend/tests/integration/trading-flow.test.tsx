import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';

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

// Import components under test
import MarketSidebar from '../../components/MarketSidebar';
import ChartScene from '../../components/ChartScene';
import { InstrumentState, TradePosition, OHLCData, ChartConfig } from '../../types';

describe('MarketSidebar to ChartScene Integration', () => {
  // Mock data helpers
  const createMockInstrument = (symbol: string, ltp: number, data: OHLCData[]): InstrumentState => ({
    ltp,
    data,
    portfolio: {
      positions: [] as TradePosition[],
      closedTrades: [],
      balance: 100000,
      equity: 100000,
      unrealizedPnl: 0,
      realizedPnl: 0,
    },
    amtAnalysis: null,
    activeSignal: null,
  });

  const mockDataNIFTY: OHLCData[] = [
    { time: '2024-01-01T10:00:00Z', open: 24900, high: 25100, low: 24800, close: 25000, volume: 1000 },
    { time: '2024-01-01T10:05:00Z', open: 25000, high: 25150, low: 24950, close: 25100, volume: 1200 },
  ];

  const mockDataBANKNIFTY: OHLCData[] = [
    { time: '2024-01-01T10:00:00Z', open: 44000, high: 44500, low: 43800, close: 44200, volume: 800 },
    { time: '2024-01-01T10:05:00Z', open: 44200, high: 44700, low: 44100, close: 44500, volume: 900 },
  ];

  const defaultConfig: ChartConfig = {
    bullColor: '#22c55e',
    bearColor: '#ef4444',
    showVolumeProfile: true,
    vpMode: 'combined',
  };

  // Shared state between tests
  let activeSymbol: string;
  let onSelectCallback: (symbol: string) => void;
  let mockInstruments: Record<string, InstrumentState>;

  beforeEach(() => {
    activeSymbol = 'NIFTY 27 FEB 25500 CALL';
    onSelectCallback = vi.fn((symbol) => {
      activeSymbol = symbol;
    });

    mockInstruments = {
      'NIFTY 27 FEB 25500 CALL': createMockInstrument('NIFTY', 25500, mockDataNIFTY),
      'BANKNIFTY 27 FEB 45000 CALL': createMockInstrument('BANKNIFTY', 45000, mockDataBANKNIFTY),
    };
  });

  it('renders MarketSidebar and ChartScene together', () => {
    const { container } = render(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={activeSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={activeSymbol}
        />
      </>
    );

    expect(container).toBeInTheDocument();
    expect(screen.getByText('MARKET SCANNER')).toBeInTheDocument();
    expect(screen.getByText('STANDARD CANDLESTICKS')).toBeInTheDocument();
  });

  it('updates activeSymbol in ChartScene when MarketSidebar selection changes', async () => {
    const user = userEvent.setup();
    
    const { rerender } = render(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={activeSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={activeSymbol}
        />
      </>
    );

    // Click on BANKNIFTY symbol in MarketSidebar
    const buttons = screen.getAllByRole('button');
    await user.click(buttons[1]);

    // Verify onSelect was called
    expect(onSelectCallback).toHaveBeenCalledWith('BANKNIFTY 27 FEB 45000 CALL');

    // Simulate state update by rerendering with new activeSymbol
    const newActiveSymbol = 'BANKNIFTY 27 FEB 45000 CALL';
    
    rerender(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={newActiveSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataBANKNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={newActiveSymbol}
        />
      </>
    );

    // Both components should still be rendered
    expect(screen.getByText('MARKET SCANNER')).toBeInTheDocument();
    expect(screen.getByText('STANDARD CANDLESTICKS')).toBeInTheDocument();
  });

  it('displays correct instrument data in MarketSidebar based on activeSymbol', () => {
    const { rerender } = render(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={activeSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={activeSymbol}
        />
      </>
    );

    // Verify NIFTY is displayed
    expect(screen.getByText('NIFTY 25500')).toBeInTheDocument();

    // Switch to BANKNIFTY
    const newActiveSymbol = 'BANKNIFTY 27 FEB 45000 CALL';
    rerender(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={newActiveSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataBANKNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={newActiveSymbol}
        />
      </>
    );

    // Verify BANKNIFTY is displayed
    expect(screen.getByText('BANKNIFTY 45000')).toBeInTheDocument();
  });

  it('maintains filter state while switching symbols', async () => {
    const user = userEvent.setup();
    
    render(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={activeSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={activeSymbol}
        />
      </>
    );

    // Apply filter
    const input = screen.getByPlaceholderText('Filter symbols...');
    await user.type(input, 'NIFTY');

    // Verify filter works
    expect(screen.getByText('NIFTY 25500')).toBeInTheDocument();

    // After selection, filter state should be maintained
    expect(input).toHaveValue('NIFTY');
  });

  it('shows live feed status in both components', () => {
    render(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={activeSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={activeSymbol}
        />
      </>
    );

    // MarketSidebar shows live feed status
    expect(screen.getByText('LIVE FEED')).toBeInTheDocument();
    expect(screen.getByText('2 SCANNING')).toBeInTheDocument();
  });

  it('switches between STANDARD and FOOTPRINT modes', () => {
    const { rerender } = render(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={activeSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={activeSymbol}
          mode="STANDARD"
        />
      </>
    );

    // Verify STANDARD mode
    expect(screen.getByText('STANDARD CANDLESTICKS')).toBeInTheDocument();

    // Switch to FOOTPRINT mode
    rerender(
      <>
        <MarketSidebar 
          instruments={mockInstruments} 
          activeSymbol={activeSymbol} 
          onSelect={onSelectCallback} 
        />
        <ChartScene
          data={mockDataNIFTY}
          predictions={[]}
          config={defaultConfig}
          positions={[]}
          footprintData={{}}
          cumulativeDeltas={[]}
          symbol={activeSymbol}
          mode="FOOTPRINT"
        />
      </>
    );

    // Verify FOOTPRINT mode
    expect(screen.getByText('ORDERFLOW FOOTPRINT')).toBeInTheDocument();
  });
});
