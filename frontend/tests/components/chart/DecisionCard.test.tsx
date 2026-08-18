import { describe, it, expect } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import DecisionCard from '../../../components/chart/DecisionCard';

describe('DecisionCard', () => {
  // Props mirror the real agentDecision contract.
  const defaultProps = {
    direction: 'LONG' as const,
    regime: 'TRENDING',
    rationale: 'Strong bullish momentum with volume confirmation',
  };

  it('renders LONG direction with correct icon', () => {
    render(<DecisionCard {...defaultProps} />);
    expect(screen.getByText(/▲ LONG/)).toBeInTheDocument();
  });

  it('renders SHORT direction with correct icon', () => {
    render(<DecisionCard {...defaultProps} direction="SHORT" />);
    expect(screen.getByText(/▼ SHORT/)).toBeInTheDocument();
  });

  it('renders FLAT direction with correct icon', () => {
    render(<DecisionCard {...defaultProps} direction="FLAT" />);
    expect(screen.getByText(/— FLAT/)).toBeInTheDocument();
  });

  it('shows regime in parentheses for LONG TRENDING', () => {
    render(<DecisionCard {...defaultProps} />);
    expect(screen.getByText(/Trend/)).toBeInTheDocument();
  });

  it('shows regime in parentheses for SHORT BALANCED', () => {
    render(<DecisionCard {...defaultProps} direction="SHORT" regime="BALANCED" />);
    expect(screen.getByText(/Reversion/)).toBeInTheDocument();
  });

  it('renders rationale when expanded', () => {
    const { container } = render(<DecisionCard {...defaultProps} />);
    
    const expandButton = container.querySelector('button');
    if (expandButton) {
      act(() => {
        expandButton.click();
      });
    }
    
    expect(screen.getByText(/Strong bullish momentum/)).toBeInTheDocument();
  });

  it('shows "Current Decision" header', () => {
    render(<DecisionCard {...defaultProps} />);
    expect(screen.getByText('Current Decision')).toBeInTheDocument();
  });

  it('shows "Decision" label', () => {
    render(<DecisionCard {...defaultProps} />);
    expect(screen.getByText('Decision')).toBeInTheDocument();
  });

  it('applies emerald color for LONG direction', () => {
    const { container } = render(<DecisionCard {...defaultProps} />);
    const directionText = container.querySelector('.text-emerald-400');
    expect(directionText).toBeInTheDocument();
  });

  it('applies red color for SHORT direction', () => {
    const { container } = render(<DecisionCard {...defaultProps} direction="SHORT" />);
    const directionText = container.querySelector('.text-red-400');
    expect(directionText).toBeInTheDocument();
  });

  it('applies slate color for FLAT direction', () => {
    const { container } = render(<DecisionCard {...defaultProps} direction="FLAT" />);
    const directionText = container.querySelector('.text-slate-400');
    expect(directionText).toBeInTheDocument();
  });

  it('handles empty rationale gracefully', () => {
    render(<DecisionCard {...defaultProps} rationale="" />);
    // Component should render without crashing
    expect(screen.getByText(/▲ LONG/)).toBeInTheDocument();
  });

  it('does not show regime for FLAT direction', () => {
    render(<DecisionCard {...defaultProps} direction="FLAT" regime="TRENDING" />);
    const flatText = screen.getByText(/— FLAT/);
    expect(flatText.textContent).not.toContain('Trend');
  });
});
