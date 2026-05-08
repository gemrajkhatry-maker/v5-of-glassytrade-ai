import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import StateTab from '../../../../components/intelligence/tabs/StateTab';

describe('StateTab', () => {
  const defaultProps = {
    marketState: 'BALANCED',
    hasDisplacement: false,
    legPoc: 50000,
    legVah: 50500,
    legVal: 49500,
    gapType: '',
    openingBias: '',
  };

  it('renders session state label', () => {
    render(<StateTab {...defaultProps} />);
    expect(screen.getByText('SESSION')).toBeInTheDocument();
  });

  it('renders leg state label', () => {
    render(<StateTab {...defaultProps} />);
    expect(screen.getByText('LEG')).toBeInTheDocument();
  });

  it('displays BALANCED market state', () => {
    render(<StateTab {...defaultProps} marketState="BALANCED" />);
    expect(screen.getAllByText('BALANCED')).toHaveLength(2);
  });

  it('displays TRENDING market state', () => {
    render(<StateTab {...defaultProps} marketState="TRENDING" />);
    expect(screen.getByText('TRENDING')).toBeInTheDocument();
  });

  it('displays IMBALANCED market state', () => {
    render(<StateTab {...defaultProps} marketState="IMBALANCED" />);
    expect(screen.getByText('IMBALANCED')).toBeInTheDocument();
  });

  it('displays DEAD market state', () => {
    render(<StateTab {...defaultProps} marketState="DEAD" />);
    expect(screen.getByText('DEAD MARKET')).toBeInTheDocument();
  });

  it('displays PROBING market state', () => {
    render(<StateTab {...defaultProps} marketState="PROBING" />);
    expect(screen.getByText('PROBING')).toBeInTheDocument();
  });

  it('shows DISPLACEMENT when hasDisplacement is true', () => {
    render(<StateTab {...defaultProps} hasDisplacement={true} />);
    expect(screen.getByText('DISPLACEMENT')).toBeInTheDocument();
  });

  it('shows BALANCED for leg when hasDisplacement is false', () => {
    render(<StateTab {...defaultProps} hasDisplacement={false} />);
    expect(screen.getAllByText('BALANCED')).toHaveLength(2);
  });

  it('displays leg POC value', () => {
    render(<StateTab {...defaultProps} legPoc={50123.5} />);
    expect(screen.getByText(/POC 50123\.5/)).toBeInTheDocument();
  });

  it('displays leg VAH and VAL when available', () => {
    render(<StateTab {...defaultProps} legVah={50800} legVal={49200} />);
    expect(screen.getByText(/49200\.0–50800\.0/)).toBeInTheDocument();
  });

  it('does not show POC when legPoc is 0', () => {
    render(<StateTab {...defaultProps} legPoc={0} />);
    expect(screen.queryByText(/POC/)).not.toBeInTheDocument();
  });

  it('shows gap type when provided', () => {
    render(<StateTab {...defaultProps} gapType="GAP UP" />);
    expect(screen.getByText(/GAP: GAP UP/)).toBeInTheDocument();
  });

  it('shows opening bias when provided', () => {
    render(<StateTab {...defaultProps} openingBias="BULLISH" />);
    expect(screen.getByText(/OPEN: BULLISH/)).toBeInTheDocument();
  });

  it('does not show gap section when both gapType and openingBias are empty', () => {
    const { container } = render(<StateTab {...defaultProps} gapType="" openingBias="" />);
    expect(screen.queryByText(/GAP:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/OPEN:/)).not.toBeInTheDocument();
  });

  it('applies orange color for IMBALANCED state', () => {
    const { container } = render(<StateTab {...defaultProps} marketState="IMBALANCED" />);
    const imbalancedText = screen.getByText('IMBALANCED');
    expect(imbalancedText.className).toContain('text-orange-400');
  });

  it('applies blue color for BALANCED state', () => {
    const { container } = render(<StateTab {...defaultProps} marketState="BALANCED" />);
    const balancedTexts = screen.getAllByText('BALANCED');
    // First BALANCED is session state
    expect(balancedTexts[0].className).toContain('text-blue-300');
  });

  it('applies warning color for DISPLACEMENT', () => {
    render(<StateTab {...defaultProps} hasDisplacement={true} />);
    const displacementText = screen.getByText('DISPLACEMENT');
    expect(displacementText.className).toContain('text-glassy-warning');
  });

  it('shows "Session & Leg" header', () => {
    render(<StateTab {...defaultProps} />);
    expect(screen.getByText('Session & Leg')).toBeInTheDocument();
  });

  it('renders Settings icon', () => {
    const { container } = render(<StateTab {...defaultProps} />);
    const settingsIcon = container.querySelector('svg');
    expect(settingsIcon).toBeInTheDocument();
  });

  it('handles undefined leg values gracefully', () => {
    render(<StateTab {...defaultProps} legPoc={undefined} legVah={undefined} legVal={undefined} />);
    expect(screen.queryByText(/POC/)).not.toBeInTheDocument();
  });

  it('displays both gap and opening bias when both provided', () => {
    render(<StateTab {...defaultProps} gapType="GAP DOWN" openingBias="BEARISH" />);
    expect(screen.getByText(/GAP: GAP DOWN/)).toBeInTheDocument();
    expect(screen.getByText(/OPEN: BEARISH/)).toBeInTheDocument();
  });

  it('applies bull color for GAP UP', () => {
    render(<StateTab {...defaultProps} gapType="GAP UP" />);
    const gapText = screen.getByText(/GAP:/);
    expect(gapText.className).toContain('text-glassy-bull-primary');
  });

  it('applies bear color for GAP DOWN', () => {
    render(<StateTab {...defaultProps} gapType="GAP DOWN" />);
    const gapText = screen.getByText(/GAP:/);
    expect(gapText.className).toContain('text-glassy-bear-primary');
  });

  it('applies bull color for BULLISH opening bias', () => {
    render(<StateTab {...defaultProps} openingBias="BULLISH" />);
    const openText = screen.getByText(/OPEN:/);
    expect(openText.className).toContain('text-glassy-bull-primary');
  });

  it('applies bear color for BEARISH opening bias', () => {
    render(<StateTab {...defaultProps} openingBias="BEARISH" />);
    const openText = screen.getByText(/OPEN:/);
    expect(openText.className).toContain('text-glassy-bear-primary');
  });
});
