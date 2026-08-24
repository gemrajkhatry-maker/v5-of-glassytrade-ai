import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import GlassPanel from '../../components/GlassPanel';

describe('GlassPanel', () => {
  it('renders children correctly', () => {
    render(
      <GlassPanel>
        <div data-testid="child">Test Content</div>
      </GlassPanel>
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
    expect(screen.getByTestId('child')).toHaveTextContent('Test Content');
  });

  it('applies custom className to outer container', () => {
    render(
      <GlassPanel className="custom-class">
        <div>Content</div>
      </GlassPanel>
    );
    // The outer div has the className, the inner div has 'relative z-10'
    const outer = screen.getByText('Content').parentElement?.parentElement;
    expect(outer).toHaveClass('custom-class');
  });

  it('renders with default glass styling', () => {
    const { container } = render(
      <GlassPanel>
        <div>Content</div>
      </GlassPanel>
    );
    // The outermost div has the institutional solid-background styling
    const outer = container.firstChild as HTMLElement;
    expect(outer).toHaveClass('bg-glassy-bg-secondary');
    expect(outer).toHaveClass('border-glassy-border-default');
    expect(outer).toHaveClass('rounded-md');
  });

  it('handles click events', async () => {
    const handleClick = vi.fn();
    const user = userEvent.setup();
    
    render(
      <GlassPanel>
        <button onClick={handleClick}>Click Me</button>
      </GlassPanel>
    );
    
    await user.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('renders multiple children', () => {
    render(
      <GlassPanel>
        <div>Child 1</div>
        <div>Child 2</div>
      </GlassPanel>
    );
    expect(screen.getByText('Child 1')).toBeInTheDocument();
    expect(screen.getByText('Child 2')).toBeInTheDocument();
  });

  it('applies transition classes', () => {
    const { container } = render(
      <GlassPanel>
        <div>Content</div>
      </GlassPanel>
    );
    const outer = container.firstChild as HTMLElement;
    expect(outer).toHaveClass('transition-all');
    expect(outer).toHaveClass('duration-300');
  });
});
