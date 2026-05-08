import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AnalysisTabs from '../../../components/intelligence/AnalysisTabs';

describe('AnalysisTabs', () => {
  const defaultProps = {
    activeTab: 'state',
    onTabChange: vi.fn(),
    hasAMTData: true,
    marketState: 'BALANCED',
    aggScore: 0.35,
  };

  it('renders all 5 tab buttons', () => {
    render(<AnalysisTabs {...defaultProps} />);
    expect(screen.getByText('State')).toBeInTheDocument();
    expect(screen.getByText('Location')).toBeInTheDocument();
    expect(screen.getByText('Aggression')).toBeInTheDocument();
    expect(screen.getByText('Metrics')).toBeInTheDocument();
    expect(screen.getByText('Decision')).toBeInTheDocument();
  });

  it('highlights the active tab with correct styling', () => {
    const { container } = render(<AnalysisTabs {...defaultProps} activeTab="state" />);
    const buttons = container.querySelectorAll('button');
    const stateButton = buttons[0];
    expect(stateButton?.className).toContain('bg-glassy-bg-elevated');
    expect(stateButton?.className).toContain('text-glassy-text-primary');
  });

  it('calls onTabChange when tab is clicked', async () => {
    const user = userEvent.setup();
    const mockOnTabChange = vi.fn();
    render(<AnalysisTabs {...defaultProps} onTabChange={mockOnTabChange} />);
    
    await user.click(screen.getByText('Location'));
    expect(mockOnTabChange).toHaveBeenCalledWith('location');
  });

  it('shows badges when hasAMTData is true', () => {
    render(<AnalysisTabs {...defaultProps} hasAMTData={true} marketState="BALANCED" />);
    expect(screen.getByText('BALANCED')).toBeInTheDocument();
  });

  it('does not show badges when hasAMTData is false', () => {
    render(<AnalysisTabs {...defaultProps} hasAMTData={false} marketState="BALANCED" />);
    expect(screen.queryByText('BALANCED')).not.toBeInTheDocument();
  });

  it('displays market state badge', () => {
    render(<AnalysisTabs {...defaultProps} marketState="TRENDING" />);
    expect(screen.getByText('TRENDING')).toBeInTheDocument();
  });

  it('displays market state badge for state tab', () => {
    render(<AnalysisTabs {...defaultProps} marketState="TRENDING" hasAMTData={true} />);
    expect(screen.getByText('TRENDING')).toBeInTheDocument();
  });

  it('displays aggression percentage badge for aggression tab', () => {
    render(<AnalysisTabs {...defaultProps} aggScore={0.35} hasAMTData={true} />);
    expect(screen.getByText('35%')).toBeInTheDocument();
  });

  it('does not show badges when hasAMTData is false', () => {
    render(<AnalysisTabs {...defaultProps} hasAMTData={false} />);
    expect(screen.queryByText('TRENDING')).not.toBeInTheDocument();
    expect(screen.queryByText('35%')).not.toBeInTheDocument();
  });

  it('applies active styling to state tab', () => {
    const { container } = render(<AnalysisTabs {...defaultProps} activeTab="state" />);
    const buttons = container.querySelectorAll('button');
    expect(buttons[0]?.className).toContain('bg-glassy-bg-elevated');
    expect(buttons[0]?.className).toContain('text-glassy-text-primary');
  });

  it('applies active styling to location tab', () => {
    const { container } = render(<AnalysisTabs {...defaultProps} activeTab="location" />);
    const buttons = container.querySelectorAll('button');
    expect(buttons[1]?.className).toContain('bg-glassy-bg-elevated');
    expect(buttons[1]?.textContent).toContain('Location');
  });

  it('applies active styling to aggression tab', () => {
    const { container } = render(<AnalysisTabs {...defaultProps} activeTab="aggression" />);
    const buttons = container.querySelectorAll('button');
    expect(buttons[2]?.className).toContain('bg-glassy-bg-elevated');
    expect(buttons[2]?.textContent).toContain('Aggression');
  });

  it('applies active styling to metrics tab', () => {
    const { container } = render(<AnalysisTabs {...defaultProps} activeTab="metrics" />);
    const buttons = container.querySelectorAll('button');
    expect(buttons[3]?.className).toContain('bg-glassy-bg-elevated');
    expect(buttons[3]?.textContent).toContain('Metrics');
  });

  it('applies active styling to decision tab', () => {
    const { container } = render(<AnalysisTabs {...defaultProps} activeTab="decision" />);
    const buttons = container.querySelectorAll('button');
    expect(buttons[4]?.className).toContain('bg-glassy-bg-elevated');
    expect(buttons[4]?.textContent).toContain('Decision');
  });

  it('renders tabs in correct order', () => {
    const { container } = render(<AnalysisTabs {...defaultProps} />);
    const buttons = container.querySelectorAll('button');
    expect(buttons[0]?.textContent).toContain('State');
    expect(buttons[1]?.textContent).toContain('Location');
    expect(buttons[2]?.textContent).toContain('Aggression');
    expect(buttons[3]?.textContent).toContain('Metrics');
    expect(buttons[4]?.textContent).toContain('Decision');
  });
});
