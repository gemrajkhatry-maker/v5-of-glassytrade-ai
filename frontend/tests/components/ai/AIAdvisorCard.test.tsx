import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import AIAdvisorCard from '../../../components/ai/AIAdvisorCard';
import type { QuantDecisionAnalysis } from '../../../types';

describe('AIAdvisorCard alignment label', () => {
  const flatAgent = {
    direction: 'FLAT' as const,
    action: 'FLAT',
    setup: 'NO_EDGE',
    confidence: 'Medium',
    rationale: 'NIFTY mid-value near POC. Neutral order flow.',
    source: 'AMT_RULE',
    modelLabel: '',
    regime: '',
    timing: '',
    sizeFraction: 0,
    latencyUs: 0,
  };

  const quantStandingBy: QuantDecisionAnalysis = {
    approved: false,
    reason: 'NO_EDGE',
    phase: 'WAITING',
    signal: null,
  };

  it('shows Aligned — No Setup when both AI and Quant are flat', () => {
    render(<AIAdvisorCard agentDecision={flatAgent} quantDecision={quantStandingBy} />);
    expect(screen.getByText(/Aligned — No Setup/i)).toBeInTheDocument();
    expect(screen.getByText(/Role: Auction Scanner/i)).toBeInTheDocument();
  });

  it('switches to Role: Position Manager when portfolio has an active open position', () => {
    const portfolioWithPos = {
      balance: 1000000,
      equity: 1000500,
      leverage: 10,
      positions: [
        {
          id: 'pos-1',
          symbol: 'GOLDM OCT FUT',
          side: 'LONG' as const,
          source: 'AMT',
          entryPrice: 153211,
          size: 3,
          stopLoss: 152625,
          takeProfit: 157491,
          pnl: 350,
          status: 'OPEN' as const,
          currentPrice: 153327,
        },
      ],
      closedTrades: [],
    };

    render(
      <AIAdvisorCard
        agentDecision={flatAgent}
        quantDecision={quantStandingBy}
        portfolio={portfolioWithPos}
      />
    );
    expect(screen.getByText(/Role: Position Manager/i)).toBeInTheDocument();
    expect(screen.getByText(/LONG @ ₹153211/i)).toBeInTheDocument();
    expect(screen.getByText(/PnL: \+₹350/i)).toBeInTheDocument();
  });

  it('shows Role: Position Manager directly when agentDecision has role POSITION_MANAGEMENT', () => {
    const posAgent = {
      ...flatAgent,
      role: 'POSITION_MANAGEMENT',
      action: 'HOLD',
      direction: 'LONG' as const,
      activePosition: {
        side: 'LONG',
        entryPrice: 153211,
        currentPrice: 153327,
        pnl: 348,
        stopLoss: 152625,
        takeProfit: 157491,
        barsHeld: 3,
        isRiskFree: false,
        rrAchieved: 0.2,
      },
    };

    render(<AIAdvisorCard agentDecision={posAgent} quantDecision={quantStandingBy} />);
    expect(screen.getByText(/Role: Position Manager/i)).toBeInTheDocument();
    expect(screen.getByText(/HOLD \(TREND INTACT\)/i)).toBeInTheDocument();
  });
});
