import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MarketSidebar from '../../components/MarketSidebar';
import { InstrumentState, TradePosition } from '../../types';

// Helper to create mock instrument state
const createMockInstrument = (symbol?: string, overrides: Partial<InstrumentState> = {}): InstrumentState => ({
  symbol: symbol || 'NIFTY 27 FEB 25500 CALL',
  ltp: 25000,
  data: [
    { time: '2024-01-01T10:00:00Z', open: 24900, high: 25100, low: 24800, close: 25000, volume: 1000, vwap: 25000, takerBuyVolume: 600, delta: 200 },
    { time: '2024-01-01T10:05:00Z', open: 25000, high: 25150, low: 24950, close: 25100, volume: 1200, vwap: 25100, takerBuyVolume: 700, delta: 300 },
  ],
  orderBook: null,
  portfolio: {
    positions: [] as TradePosition[],
    closedTrades: [],
    balance: 100000,
    equity: 100000,
    leverage: 10,
    history: [],
    realizedPnl: 0,
  },
  modelWeights: { trend: 0.2, momentum: 0.2, delta: 0.2, orderBook: 0.2, volatility: 0.2 },
  generation: 0,
  aiAnalysis: null,
  genAIAnalysis: null,
  amtAnalysis: null,
  agentDecision: null,
  llmHistory: [],
  predictions: [],
  overseerAction: '',
  overseerReason: '',
  stats: null,
  depth20Active: false,
  lastUpdate: Date.now(),
  ...overrides,
});

describe('MarketSidebar', () => {
  const mockOnSelect = vi.fn();
  
  const defaultProps = {
    instruments: {
      'NIFTY 27 FEB 25500 CALL': createMockInstrument('NIFTY 27 FEB 25500 CALL', { ltp: 25500 }),
      'NIFTY 27 FEB 25600 CALL': createMockInstrument('NIFTY 27 FEB 25600 CALL', { ltp: 25600 }),
    },
    activeSymbol: 'NIFTY 27 FEB 25500 CALL',
    onSelect: mockOnSelect,
  };

  beforeEach(() => {
    mockOnSelect.mockClear();
  });

  it('renders market scanner header', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByText('MARKET SCANNER')).toBeInTheDocument();
  });

  it('displays symbol count', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByText('2 of 2')).toBeInTheDocument();
  });

  it('renders filter input', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByPlaceholderText('Filter symbols...')).toBeInTheDocument();
  });

  it('filters symbols based on search input', async () => {
    const user = userEvent.setup();
    render(<MarketSidebar {...defaultProps} />);
    
    const input = screen.getByPlaceholderText('Filter symbols...');
    await user.type(input, '25600');
    
    // After filtering, should show only the symbol with 25600
    const symbols = screen.getAllByRole('listitem');
    expect(symbols.length).toBe(1);
    expect(symbols[0]).toHaveTextContent('25600');
  });

  it('calls onSelect when symbol is clicked', async () => {
    const user = userEvent.setup();
    render(<MarketSidebar {...defaultProps} />);
    
    const buttons = screen.getAllByRole('listitem');
    await user.click(buttons[1]);
    
    expect(mockOnSelect).toHaveBeenCalledWith('NIFTY 27 FEB 25600 CALL');
  });

  it('displays live feed status', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByText('LIVE FEED')).toBeInTheDocument();
  });

  it('shows visible count in footer', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByText('2 VISIBLE')).toBeInTheDocument();
  });

  it('renders trade history section', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByText('NIFTY 25500 TRADES')).toBeInTheDocument();
  });

  it('displays empty state when no matching symbols', async () => {
    const user = userEvent.setup();
    render(<MarketSidebar {...defaultProps} />);
    
    const input = screen.getByPlaceholderText('Filter symbols...');
    await user.type(input, 'XXXXX');
    
    expect(screen.getByText('No matching symbols')).toBeInTheDocument();
  });

  it('shows loading state for symbols without price', () => {
    const props = {
      ...defaultProps,
      instruments: {
        'NIFTY 27 FEB 25500 CALL': createMockInstrument('NIFTY 27 FEB 25500 CALL', { ltp: undefined, data: [] }),
      },
      activeSymbol: 'NIFTY 27 FEB 25500 CALL',
      onSelect: mockOnSelect,
    };
    
    render(<MarketSidebar {...props} />);
    // When no data, shows "Waiting for scanner..." or similar message
    expect(screen.getByText(/scanner|waiting/i)).toBeInTheDocument();
  });

  it('displays symbol name correctly', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByText('NIFTY 25500')).toBeInTheDocument();
  });

  it('has symbol list items', () => {
    render(<MarketSidebar {...defaultProps} />);
    const items = screen.getAllByRole('listitem');
    expect(items.length).toBeGreaterThan(0);
  });
});
