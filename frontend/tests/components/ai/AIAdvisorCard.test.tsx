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
    expect(screen.queryByText(/Standing By/i)).toBeNull();
  });
});
