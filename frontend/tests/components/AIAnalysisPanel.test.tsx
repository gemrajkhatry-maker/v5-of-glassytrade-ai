import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AIAnalysisPanel } from '../../components/AIAnalysisPanel';
import { AMTAnalysis, Portfolio, QuantDecisionAnalysis } from '../../types';

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
      <AIAnalysisPanel amtResult={amtResult} portfolio={portfolio} />
    );
    expect(screen.queryByText('CVD Trend')).toBeNull();
    const sparkline = container.querySelector('svg[class="flex-shrink-0"]');
    expect(sparkline).toBeNull();
  });

  it('does not render the fabricated ENGINE ARMED badge', () => {
    const { container } = render(
      <AIAnalysisPanel amtResult={amtResult} portfolio={portfolio} />
    );
    expect(container.textContent).not.toContain('[ENGINE ARMED]');
  });

  it('wraps diagnostic tiers in a collapsed details element', () => {
    const { container } = render(
      <AIAnalysisPanel amtResult={amtResult} portfolio={portfolio} />
    );
    const details = [...container.querySelectorAll('details')].find(
      (el) => el.textContent?.includes('Diagnostics')
    );
    expect(details).not.toBeNull();
    expect(details!.getAttribute('open')).toBeNull();
  });

  it('renders market structure only inside the Diagnostics tier', () => {
    const { container } = render(
      <AIAnalysisPanel amtResult={amtResult} portfolio={portfolio} />
    );
    const diagnostics = [...container.querySelectorAll('details')].find(
      (el) => el.textContent?.includes('Diagnostics')
    );
    expect(diagnostics).not.toBeNull();
    expect(diagnostics!.textContent).toContain('BALANCE');
  });
});

describe('AIAnalysisPanel quant decision precedence (F-07)', () => {
  const quantApproved: QuantDecisionAnalysis = {
    approved: true,
    reason: 'Triple-A',
    phase: 'AGGRESSION',
    signal: { type: 'LONG', entry: 104.0, sl: 99.54, tp: 112.92, rr: 2.0, modelLabel: 'Triple-A' },
  };

  const quantRejected: QuantDecisionAnalysis = {
    approved: false,
    reason: 'NO_EDGE',
    phase: 'WAITING',
    signal: null,
  };

  const portfolio: Portfolio = {
    balance: 100000,
    equity: 100500,
    leverage: 1,
    positions: [],
    closedTrades: [],
  };

  it('renders the quant decision as the primary card when present', () => {
    render(
      <AIAnalysisPanel
        amtResult={amtResult}
        portfolio={portfolio}
        quantDecision={quantApproved}
      />
    );
    expect(screen.getByText(/Quant Decision/i)).toBeInTheDocument();
    expect(screen.getByText(/Approved/i)).toBeInTheDocument();
    expect(screen.getByText(/LONG @ 104.00/i)).toBeInTheDocument();
    expect(screen.getByText(/RR 2.0/i)).toBeInTheDocument();
  });

  it('does not fabricate a signal when quantDecision has none', () => {
    render(
      <AIAnalysisPanel
        amtResult={amtResult}
        portfolio={portfolio}
        quantDecision={quantRejected}
      />
    );
    expect(screen.getByText(/Standing By/i)).toBeInTheDocument();
    // The reason may also appear in the legacy MODEL I/O footer fallback.
    expect(screen.getAllByText(/NO_EDGE/i).length).toBeGreaterThan(0);
    // No fabricated LONG/SHORT price line.
    expect(screen.queryByText(/LONG @/i)).toBeNull();
    expect(screen.queryByText(/SHORT @/i)).toBeNull();
  });

  it('renders QuantDecisionCard in the cockpit tab when quant decision exists', () => {
    render(
      <AIAnalysisPanel
        amtResult={amtResult}
        portfolio={portfolio}
        quantDecision={quantApproved}
      />
    );
    // Cockpit tab is active by default — QuantDecisionCard should render
    expect(screen.queryByText(/Quant Decision/i)).not.toBeNull();
    // No LegacyAmtWrapper <details> element (that component is removed)
    expect(
      document.querySelectorAll('details').length === 0 ||
      [...document.querySelectorAll('details')].every(
        (el) => !el.textContent?.includes('Legacy AMT Analysis')
      )
    ).toBe(true);
  });

  it('does not render LegacyAmtWrapper when no quant decision exists', () => {
    render(
      <AIAnalysisPanel amtResult={amtResult} portfolio={portfolio} />
    );
    expect(
      [...document.querySelectorAll('details')].some(
        (el) => el.textContent?.includes('Legacy AMT Analysis')
      )
    ).toBe(false);
  });
});

