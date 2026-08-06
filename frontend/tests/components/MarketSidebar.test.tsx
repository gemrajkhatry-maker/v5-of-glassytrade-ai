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
  orderBook: null,    portfolio: {
    positions: [] as TradePosition[],
    closedTrades: [],
    balance: 100000,
    equity: 100000,
    leverage: 10,
  },
  modelWeights: { trend: 0.2, momentum: 0.2, delta: 0.2, orderBook: 0.2, volatility: 0.2 },
  generation: 0,
  aiAnalysis: null,
  genAIAnalysis: null,
  amtAnalysis: null,
  riskState: null,
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
    // CSS `uppercase` transform — match case-insensitively
    expect(screen.getByText(/market scanner/i)).toBeInTheDocument();
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
    const symbols = screen.getAllByRole('button');
    expect(symbols.length).toBe(1);
    expect(symbols[0]).toHaveTextContent('25600');
  });

  it('calls onSelect when symbol is clicked', async () => {
    const user = userEvent.setup();
    render(<MarketSidebar {...defaultProps} />);
    
    const buttons = screen.getAllByRole('button');
    await user.click(buttons[1]);
    
    expect(mockOnSelect).toHaveBeenCalledWith('NIFTY 27 FEB 25600 CALL');
  });

  it('displays live feed status', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByText(/live feed/i)).toBeInTheDocument();
  });

  it('shows visible count in footer', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.getByText(/2 visible/i)).toBeInTheDocument();
  });

  it('does not render the recent-trades panel (closedTrades is canonical in JournalPage)', () => {
    render(<MarketSidebar {...defaultProps} />);
    expect(screen.queryByText(/trades/i)).toBeNull();
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
    // Symbol cards render as buttons (not listitems) in the current design
    const items = screen.getAllByRole('button');
    expect(items.length).toBeGreaterThan(0);
  });

  it('does not show probability in the sidebar (canonical location is the banner)', () => {
    const props = {
      ...defaultProps,
      instruments: {
        'NIFTY 27 FEB 25500 CALL': createMockInstrument('NIFTY 27 FEB 25500 CALL', {
          agentDecision: {
            direction: 'LONG' as const,
            probability: 0.6,
            regime: 'TRENDING',
            timing: 'ENTER_NOW',
            sizeFraction: 0.5,
            latencyUs: 0,
            rationale: 'x',
          },
        }),
      },
    };

    render(<MarketSidebar {...props} />);
    expect(screen.queryByText(/Prob/i)).toBeNull();
    expect(screen.queryByText(/60%/)).toBeNull();
  });

  it('does not show UNSAFE badge even when runtimeSafety.unsafeToTrade is set', () => {
    // Backend never sends runtimeSafety, so no symbol may ever show UNSAFE.
    const props = {
      ...defaultProps,
      instruments: {
        'NIFTY 27 FEB 25500 CALL': createMockInstrument('NIFTY 27 FEB 25500 CALL', {
          agentDecision: {
            direction: 'LONG' as const,
            probability: 0.6,
            regime: 'TRENDING',
            timing: 'MONITOR',
            sizeFraction: 0.5,
            latencyUs: 0,
            rationale: 'x',
          },
          runtimeSafety: { brokerBound: false, feedStale: true, unsafeToTrade: true },
        }),
      },
    };

    render(<MarketSidebar {...props} />);
    expect(screen.queryByText(/UNSAFE/)).not.toBeInTheDocument();
  });
});
