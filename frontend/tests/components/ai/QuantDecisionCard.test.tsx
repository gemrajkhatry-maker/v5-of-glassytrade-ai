import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import QuantDecisionCard from '../../../components/ai/QuantDecisionCard';
import { QuantDecisionAnalysis } from '../../../types';

const approved: QuantDecisionAnalysis = {
  approved: true,
  reason: 'Triple-A',
  phase: 'AGGRESSION',
  signal: { type: 'LONG', entry: 104.0, sl: 99.54, tp: 112.92, rr: 2.0, confidence: 0.87 },
};

const rejected: QuantDecisionAnalysis = {
  approved: false,
  reason: 'NO_EDGE',
  phase: 'WAITING',
  signal: null,
};

describe('QuantDecisionCard', () => {
  it('renders nothing when there is no quant decision', () => {
    const { container } = render(<QuantDecisionCard quantDecision={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the approved signal with SL/TP/confidence', () => {
    render(<QuantDecisionCard quantDecision={approved} />);
    expect(screen.getByText(/Quant Decision/i)).toBeInTheDocument();
    expect(screen.getByText(/Approved/i)).toBeInTheDocument();
    expect(screen.getByText(/LONG @ 104.00/i)).toBeInTheDocument();
    expect(screen.getByText(/RR 2.0/i)).toBeInTheDocument();
    expect(screen.getByText('99.54')).toBeInTheDocument();
    expect(screen.getByText('112.92')).toBeInTheDocument();
    expect(screen.getByText('87%')).toBeInTheDocument();
    expect(screen.getByText(/Phase: AGGRESSION/i)).toBeInTheDocument();
  });

  it('renders Standing By state and reason when there is no signal', () => {
    render(<QuantDecisionCard quantDecision={rejected} />);
    expect(screen.getByText(/Standing By/i)).toBeInTheDocument();
    expect(screen.getAllByText(/NO_EDGE/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/LONG @/i)).toBeNull();
    expect(screen.queryByText(/SHORT @/i)).toBeNull();
  });
});
