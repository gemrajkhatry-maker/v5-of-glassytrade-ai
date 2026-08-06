import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AIAnalysisPanel } from '../../components/AIAnalysisPanel';
import { AMTAnalysis, Portfolio } from '../../types';

const amtResult: AMTAnalysis = {
  marketState: 'BALANCED',
  poc: 25000,
  valueAreaHigh: 25100,
  valueAreaLow: 24900,
  lvns: [],
  hvns: [],
  aggression: 0.5,
  setup: null,
  profile: [],
  aggressivePrints: [],
  legProfile: [],
  legLvns: [],
  legPoc: 0,
  legVah: 0,
  legVal: 0,
  hasDisplacement: false,
  cvdSlope: 50,
};

const portfolio: Portfolio = {
  balance: 100000,
  equity: 100500,
  leverage: 1,
  positions: [],
  closedTrades: [],
};

describe('AIAnalysisPanel', () => {
  it('does not render a simulated CVD sparkline', () => {
    const { container } = render(
      <AIAnalysisPanel analysis={null} amtResult={amtResult} portfolio={portfolio} />
    );
    expect(screen.queryByText('CVD Trend')).toBeNull();
    const sparkline = container.querySelector('svg[class="flex-shrink-0"]');
    expect(sparkline).toBeNull();
  });

  it('does not render the fabricated ENGINE ARMED badge', () => {
    const { container } = render(
      <AIAnalysisPanel analysis={null} amtResult={amtResult} portfolio={portfolio} />
    );
    expect(container.textContent).not.toContain('[ENGINE ARMED]');
  });

  it('wraps diagnostic tiers in a collapsed details element', () => {
    const { container } = render(
      <AIAnalysisPanel analysis={null} amtResult={amtResult} portfolio={portfolio} />
    );
    const details = [...container.querySelectorAll('details')].find(
      (el) => el.textContent?.includes('Diagnostics')
    );
    expect(details).not.toBeNull();
    expect(details!.getAttribute('open')).toBeNull();
  });

  it('renders market structure only inside the Diagnostics tier', () => {
    const { container } = render(
      <AIAnalysisPanel analysis={null} amtResult={amtResult} portfolio={portfolio} />
    );
    const diagnostics = [...container.querySelectorAll('details')].find(
      (el) => el.textContent?.includes('Diagnostics')
    );
    expect(diagnostics).not.toBeNull();
    expect(diagnostics!.textContent).toContain('BALANCE');
  });
});
