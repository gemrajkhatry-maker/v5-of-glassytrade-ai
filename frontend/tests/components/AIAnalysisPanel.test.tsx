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
    signal: { type: 'LONG', entry: 104.0, sl: 99.54, tp: 112.92, rr: 2.0, confidence: 1.0 },
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

  it('collapses the legacy AMT body behind a grayed details when a quant decision exists', () => {
    const { container } = render(
      <AIAnalysisPanel
        amtResult={amtResult}
        portfolio={portfolio}
        quantDecision={quantApproved}
      />
    );
    const legacy = [...container.querySelectorAll('details')].find(
      (el) => el.textContent?.includes('Legacy AMT Analysis')
    );
    expect(legacy).not.toBeNull();
    // Collapsed by default.
    expect(legacy!.getAttribute('open')).toBeNull();
    // Legacy body is grayed out (opacity applied).
    const body = legacy!.querySelector('div.opacity-60');
    expect(body).not.toBeNull();
  });

  it('renders the AMT body unwrapped when no quant decision exists', () => {
    const { container } = render(
      <AIAnalysisPanel amtResult={amtResult} portfolio={portfolio} />
    );
    expect(
      [...container.querySelectorAll('details')].some(
        (el) => el.textContent?.includes('Legacy AMT Analysis')
      )
    ).toBe(false);
    expect(screen.queryByText(/Quant Decision/i)).toBeNull();
  });
});
