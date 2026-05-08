import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import AggressionTab from '../../../../components/intelligence/tabs/AggressionTab';

describe('AggressionTab', () => {
  const defaultProps = {
    deltaScore: 0.35,
    aggScore: 0.40,
    formatCVD: (cvd: number) => cvd.toFixed(2),
    agentDecision: { probability: 0.75 },
    amtResult: {
      ofi: 0.125,
      cvdSlope: 15.5,
      cvdDivergence: '',
      deltaNormalizedOption: 0.35,
      breakDirection: '',
      sessionVwap: 50000,
      valueAreaHigh: 50500,
      valueAreaLow: 49500,
      balanceRatio: 0.60,
      profileShape: 'D',
      profileType: 'Session',
    },
    symbol: 'NIFTY',
    orderBook: {
      bids: [{ price: 49995 }],
      asks: [{ price: 50005 }],
    },
    depth20Active: false,
  };

  it('displays Volume Aggression header', () => {
    render(<AggressionTab {...defaultProps} />);
    expect(screen.getByText('Volume Aggression')).toBeInTheDocument();
  });

  it('displays Market Metrics header', () => {
    render(<AggressionTab {...defaultProps} />);
    expect(screen.getByText('Market Metrics')).toBeInTheDocument();
  });

  it('shows BULLS IN CONTROL for positive delta', () => {
    render(<AggressionTab {...defaultProps} deltaScore={0.35} aggScore={0.40} />);
    expect(screen.getByText('[BULLS IN CONTROL]')).toBeInTheDocument();
  });

  it('shows BEARS IN CONTROL for negative delta', () => {
    render(<AggressionTab {...defaultProps} deltaScore={-0.35} aggScore={0.40} />);
    expect(screen.getByText('[BEARS IN CONTROL]')).toBeInTheDocument();
  });

  it('shows DELTA NEUTRAL for near-zero delta', () => {
    render(<AggressionTab {...defaultProps} deltaScore={0.02} aggScore={0.40} />);
    expect(screen.getByText('[DELTA NEUTRAL / NEGLIGIBLE]')).toBeInTheDocument();
  });

  it('displays delta score value', () => {
    render(<AggressionTab {...defaultProps} deltaScore={0.35} />);
    expect(screen.getByText('+0.35')).toBeInTheDocument();
  });

  it('displays negative delta score', () => {
    render(<AggressionTab {...defaultProps} deltaScore={-0.25} />);
    expect(screen.getByText('-0.25')).toBeInTheDocument();
  });

  it('displays delta confidence percentage', () => {
    render(<AggressionTab {...defaultProps} deltaScore={0.75} agentDecision={{ probability: 0.75 }} />);
    expect(screen.getByText('75.0%')).toBeInTheDocument();
  });

  it('shows ~50% confidence for delta neutral', () => {
    render(<AggressionTab {...defaultProps} deltaScore={0.02} agentDecision={{ probability: 0.50 }} />);
    expect(screen.getByText('~50%')).toBeInTheDocument();
  });

  it('displays aggression score', () => {
    render(<AggressionTab {...defaultProps} aggScore={0.40} />);
    expect(screen.getByText('0.40 (Bullish)')).toBeInTheDocument();
  });

  it('displays bearish aggression label', () => {
    render(<AggressionTab {...defaultProps} deltaScore={-0.35} aggScore={-0.40} />);
    // Should show negative value
    const aggText = screen.getByText(/-0\.40/);
    expect(aggText).toBeInTheDocument();
  });

  it('displays OFI value with positive indicator', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, ofi: 0.125 }} />);
    expect(screen.getByText('+0.125')).toBeInTheDocument();
  });

  it('displays OFI value with negative indicator', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, ofi: -0.080 }} />);
    expect(screen.getByText('-0.080')).toBeInTheDocument();
  });

  it('displays CVD Slope value', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, cvdSlope: 15.5 }} />);
    expect(screen.getByText(/15\.50/)).toBeInTheDocument();
  });

  it('shows BULLISH label for positive CVD slope', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, cvdSlope: 25.0 }} />);
    expect(screen.getByText(/BULLISH/)).toBeInTheDocument();
  });

  it('shows BEARISH label for negative CVD slope', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, cvdSlope: -25.0 }} />);
    expect(screen.getByText(/BEARISH/)).toBeInTheDocument();
  });

  it('shows FLAT label for near-zero CVD slope', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, cvdSlope: 0.005 }} />);
    expect(screen.getByText(/FLAT/)).toBeInTheDocument();
  });

  it('displays CVD divergence when present', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, cvdDivergence: 'BEARISH_DIV' }} />);
    expect(screen.getByText(/BEARISH/)).toBeInTheDocument();
  });

  it('displays balance ratio in VA', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, balanceRatio: 0.60 }} />);
    // Text may be split across elements, use regex
    expect(screen.getByText(/60%/)).toBeInTheDocument();
  });

  it('shows ABOVE VA when LTP > VAH', () => {
    render(<AggressionTab {...defaultProps} amtResult={{
      ...defaultProps.amtResult,
      sessionVwap: 51000,
      valueAreaHigh: 50500,
      balanceRatio: 0,
    }} />);
    expect(screen.getByText('0% in VA (Above ↑)')).toBeInTheDocument();
  });

  it('shows BELOW VA when LTP < VAL', () => {
    render(<AggressionTab {...defaultProps} amtResult={{
      ...defaultProps.amtResult,
      sessionVwap: 49000,
      valueAreaLow: 49500,
      balanceRatio: 0,
    }} />);
    expect(screen.getByText('0% in VA (Below ↓)')).toBeInTheDocument();
  });

  it('shows TRANSITIONING for balance ratio 50-70%', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, balanceRatio: 0.60 }} />);
    expect(screen.getByText(/TRANSITIONING/)).toBeInTheDocument();
  });

  it('displays profile shape B Bimodal', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, profileShape: 'B' }} />);
    expect(screen.getByText('B Bimodal')).toBeInTheDocument();
  });

  it('displays profile shape P Top-heavy', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, profileShape: 'P' }} />);
    expect(screen.getByText('P Top-heavy')).toBeInTheDocument();
  });

  it('displays profile shape b Bottom-heavy', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, profileShape: 'b' }} />);
    expect(screen.getByText('b Bottom-heavy')).toBeInTheDocument();
  });

  it('displays profile shape D Balanced', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, profileShape: 'D' }} />);
    expect(screen.getByText('D Balanced')).toBeInTheDocument();
  });

  it('displays profile type', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, profileType: 'Session' }} />);
    expect(screen.getByText('(Session)')).toBeInTheDocument();
  });

  it('displays spread in basis points', () => {
    render(<AggressionTab {...defaultProps} />);
    // Spread is rendered, use flexible matching
    const spreadText = screen.getByText(/bps/);
    expect(spreadText).toBeInTheDocument();
  });

  it('displays Depth-5 when depth20Active is false', () => {
    render(<AggressionTab {...defaultProps} depth20Active={false} />);
    expect(screen.getByText('Depth-5')).toBeInTheDocument();
  });

  it('displays Depth-20 when depth20Active is true', () => {
    render(<AggressionTab {...defaultProps} depth20Active={true} />);
    expect(screen.getByText('Depth-20')).toBeInTheDocument();
  });

  it('renders Activity icon', () => {
    const { container } = render(<AggressionTab {...defaultProps} />);
    const activityIcons = container.querySelectorAll('svg');
    expect(activityIcons.length).toBeGreaterThan(0);
  });

  it('handles missing OFI gracefully', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, ofi: undefined }} />);
    // Should default to 0
    expect(screen.getByText(/0\.000/)).toBeInTheDocument();
  });

  it('handles missing CVD slope gracefully', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, cvdSlope: undefined }} />);
    // Should show FLAT
    const cvdText = screen.getByText(/0\.00/);
    expect(cvdText.textContent).toContain('FLAT');
  });

  it('handles missing balance ratio gracefully', () => {
    render(<AggressionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, balanceRatio: undefined }} />);
    // Should show 0%
    expect(screen.getByText(/0% in VA/)).toBeInTheDocument();
  });

  it('handles null agent decision', () => {
    render(<AggressionTab {...defaultProps} agentDecision={null} />);
    // Should not crash
    expect(screen.getByText('Volume Aggression')).toBeInTheDocument();
  });

  it('handles empty order book', () => {
    render(<AggressionTab {...defaultProps} orderBook={null} />);
    // Should show dash for spread
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThan(0);
  });
});
