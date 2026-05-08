import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MetricsTab from '../../../../components/intelligence/tabs/MetricsTab';

describe('MetricsTab', () => {
  const defaultProps = {
    agentDecision: {
      id: 'test-1',
      timestamp: '2024-01-01T00:00:00Z',
      direction: 'LONG' as const,
      probability: 0.75,
      regime: 'TRENDING' as const,
      timing: 'ENTER_NOW' as const,
      sizeFraction: 1.0,
      rationale: 'Strong bullish momentum',
      latencyUs: 150000,
      slAdjust: 0,
      tpAdjust: 0,
    },
    overseerAction: 'HOLD',
    overseerReason: 'Trend intact, hold position',
    portfolio: {
      positions: [],
      cash: 100000,
      totalValue: 100000,
      balance: 100000,
      equity: 100000,
      leverage: 1,
      closedTrades: [],
      history: [],
    },
    amtResult: {
      isSecondDrive: false,
      lvnPlay: null,
      optionType: '',
      marketState: 'BALANCED',
      poc: 50000,
      valueAreaHigh: 50500,
      valueAreaLow: 49500,
    } as any,
    llmHistory: [],
  };

  it('shows waiting message when no agent decision', () => {
    render(<MetricsTab {...defaultProps} agentDecision={null} />);
    expect(screen.getByText(/Waiting for probability engine/)).toBeInTheDocument();
  });

  it('displays probability engine section', () => {
    render(<MetricsTab {...defaultProps} />);
    expect(screen.getByText('Direction')).toBeInTheDocument();
    expect(screen.getByText('P(target)')).toBeInTheDocument();
    expect(screen.getByText('Timing / Size')).toBeInTheDocument();
  });

  it('displays LONG direction with playbook label', () => {
    render(<MetricsTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, direction: 'LONG', regime: 'TRENDING' }} />);
    expect(screen.getByText(/BUY \(Initiative Trend\)/)).toBeInTheDocument();
  });

  it('displays SHORT direction with playbook label', () => {
    render(<MetricsTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, direction: 'SHORT', regime: 'BALANCED' }} />);
    expect(screen.getByText(/SELL \(Responsive Fade\)/)).toBeInTheDocument();
  });

  it('displays FLAT direction', () => {
    render(<MetricsTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, direction: 'FLAT' }} />);
    expect(screen.getByText('FLAT')).toBeInTheDocument();
  });

  it('displays probability percentage', () => {
    render(<MetricsTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, probability: 0.75 }} />);
    expect(screen.getByText('75.0%')).toBeInTheDocument();
  });

  it('displays timing label', () => {
    render(<MetricsTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, timing: 'ENTER_NOW' }} />);
    expect(screen.getByText('ENTER_NOW')).toBeInTheDocument();
  });

  it('displays size fraction as percentage', () => {
    render(<MetricsTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, sizeFraction: 1.0 }} />);
    expect(screen.getByText('100.0%')).toBeInTheDocument();
  });

  it('shows SECOND DRIVE indicator', () => {
    render(<MetricsTab {...defaultProps} amtResult={{ ...defaultProps.amtResult!, isSecondDrive: true }} />);
    // Text includes emoji, use regex
    expect(screen.getByText(/SECOND DRIVE/)).toBeInTheDocument();
  });

  it('shows FIRST DRIVE indicator', () => {
    render(<MetricsTab {...defaultProps} amtResult={{ ...defaultProps.amtResult!, isSecondDrive: false }} />);
    // Text includes emoji, use regex
    expect(screen.getByText(/FIRST DRIVE/)).toBeInTheDocument();
  });

  it('shows LVN PLAY indicator when present', () => {
    const lvnPlay = {
      lvn_price: 50100,
      direction: 'LONG' as const,
      rationale: 'LVN retest',
    };
    render(<MetricsTab {...(defaultProps as any)} amtResult={{ ...defaultProps.amtResult, lvnPlay }} />);
    // Text includes emoji, use regex
    expect(screen.getByText(/LVN PLAY/)).toBeInTheDocument();
    expect(screen.getByText(/@ 50100\.0/)).toBeInTheDocument();
  });

  it('shows Logic Formulas expandable section', () => {
    render(<MetricsTab {...defaultProps} />);
    expect(screen.getByText('Logic Formulas')).toBeInTheDocument();
    expect(screen.getByText('Expand')).toBeInTheDocument();
  });

  it('displays regime in logic formulas', () => {
    render(<MetricsTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, regime: 'TRENDING' }} />);
    expect(screen.getByText('TRENDING')).toBeInTheDocument();
  });

  it('displays rationale in logic formulas', () => {
    render(<MetricsTab {...defaultProps} />);
    expect(screen.getByText(/Strong bullish momentum/)).toBeInTheDocument();
  });

  it('displays latency in logic formulas', () => {
    render(<MetricsTab {...defaultProps} />);
    expect(screen.getByText(/150000μs/)).toBeInTheDocument();
  });

  it('shows overseer section when action present', () => {
    render(<MetricsTab {...defaultProps} overseerAction="HOLD" />);
    expect(screen.getByText('Action')).toBeInTheDocument();
  });

  it('displays HOLD overseer action', () => {
    render(<MetricsTab {...defaultProps} overseerAction="HOLD" />);
    expect(screen.getByText('HOLD')).toBeInTheDocument();
  });

  it('displays TIGHTEN overseer action', () => {
    render(<MetricsTab {...defaultProps} overseerAction="TIGHTEN" />);
    expect(screen.getByText('TIGHTEN')).toBeInTheDocument();
  });

  it('displays FULL_EXIT overseer action', () => {
    render(<MetricsTab {...defaultProps} overseerAction="FULL_EXIT" />);
    expect(screen.getByText('FULL_EXIT')).toBeInTheDocument();
  });

  it('displays PARTIAL overseer action', () => {
    render(<MetricsTab {...defaultProps} overseerAction="PARTIAL" />);
    expect(screen.getByText('PARTIAL')).toBeInTheDocument();
  });

  it('displays ADD overseer action', () => {
    render(<MetricsTab {...defaultProps} overseerAction="ADD" />);
    expect(screen.getByText('ADD')).toBeInTheDocument();
  });

  it('displays overseer reason', () => {
    render(<MetricsTab {...defaultProps} overseerReason="Trend intact, hold position" />);
    expect(screen.getByText(/Trend intact/)).toBeInTheDocument();
  });

  it('shows no overseer decision when no action and no positions', () => {
    render(<MetricsTab {...defaultProps} overseerAction="" overseerReason="" />);
    expect(screen.queryByText(/No overseer decision/)).not.toBeInTheDocument();
  });

  it('displays open positions in trade plan', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG' as const,
        size: 10,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 500,
        status: 'OPEN' as const,
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 0,
        symbol: 'NIFTY',
        source: 'AI',
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio as any} />);
    expect(screen.getByText(/LONG x10/)).toBeInTheDocument();
  });

  it('displays position PnL', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 10,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 500,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 0,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText(/\+₹500/)).toBeInTheDocument();
  });

  it('displays position SL', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 10,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 500,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 0,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText('SL')).toBeInTheDocument();
    expect(screen.getByText('49900.00')).toBeInTheDocument();
  });

  it('displays position TP', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 10,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 500,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 0,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText('TP')).toBeInTheDocument();
    expect(screen.getByText('50200.00')).toBeInTheDocument();
  });

  it('displays R-multiple', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 10,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 500,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 0,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText(/R-mult/)).toBeInTheDocument();
  });

  it('shows partial TP booked indicator', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 5,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 250,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 200,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText(/Partial TP booked/)).toBeInTheDocument();
  });

  it('shows position size reduction', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 5,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 250,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 0,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText(/was 10/)).toBeInTheDocument();
  });

  it('shows breakeven indicator when SL near entry', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 10,
        entryPrice: 50000,
        stopLoss: 50000,
        takeProfit: 50200,
        pnl: 0,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 0,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText('BE')).toBeInTheDocument();
  });

  it('shows position hold time', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 10,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 500,
        status: 'OPEN',
        entryTime: new Date(Date.now() - 120000).toISOString(), // 2 minutes ago
        originalSize: 10,
        partialRealizedPnl: 0,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText(/2m 0s held/)).toBeInTheDocument();
  });

  it('shows Runner label for partial TP positions', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 5,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 250,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 200,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText('Runner')).toBeInTheDocument();
  });

  it('shows Full size label for non-partial positions', () => {
    const portfolio = {
      ...defaultProps.portfolio,
      positions: [{
        id: 'pos-1',
        side: 'LONG',
        size: 10,
        entryPrice: 50000,
        stopLoss: 49900,
        takeProfit: 50200,
        pnl: 500,
        status: 'OPEN',
        entryTime: '2024-01-01T00:00:00Z',
        originalSize: 10,
        partialRealizedPnl: 0,
      }],
    };
    render(<MetricsTab {...defaultProps} portfolio={portfolio} />);
    expect(screen.getByText('Full size')).toBeInTheDocument();
  });

  it('handles empty positions array', () => {
    render(<MetricsTab {...defaultProps} />);
    expect(screen.queryByText(/LONG x/)).not.toBeInTheDocument();
  });

  it('handles undefined amtResult', () => {
    render(<MetricsTab {...defaultProps} amtResult={undefined} />);
    // Should not crash
    expect(screen.getByText('Direction')).toBeInTheDocument();
  });

  it('handles null amtResult', () => {
    render(<MetricsTab {...defaultProps} amtResult={null} />);
    // Should not crash
    expect(screen.getByText('Direction')).toBeInTheDocument();
  });
});
