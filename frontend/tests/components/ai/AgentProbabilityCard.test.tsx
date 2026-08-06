import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import AgentProbabilityCard from '../../../components/ai/AgentProbabilityCard';
import { AgentDecision } from '../../../types';

const decision: AgentDecision = {
  direction: 'LONG',
  probability: 0.72,
  regime: 'TRENDING',
  timing: 'ENTER_NOW',
  sizeFraction: 0.5,
  latencyUs: 420,
  rationale: 'High conviction momentum continuation',
};

describe('AgentProbabilityCard', () => {
  it('renders the waiting state when there is no agent decision', () => {
    render(<AgentProbabilityCard agentDecision={null} />);
    expect(screen.getByText(/Waiting for probability engine/i)).toBeInTheDocument();
  });

  it('renders direction, probability, and timing/size from the decision', () => {
    render(<AgentProbabilityCard agentDecision={decision} isSecondDrive={undefined} />);
    expect(screen.getByText(/BUY \(Initiative Trend\)/i)).toBeInTheDocument();
    expect(screen.getByText('72.0%')).toBeInTheDocument();
    expect(screen.getByText(/ENTER_NOW/i)).toBeInTheDocument();
    expect(screen.getByText('50.0%')).toBeInTheDocument();
  });

  it('renders the second drive indicator when flagged', () => {
    render(<AgentProbabilityCard agentDecision={decision} isSecondDrive />);
    expect(screen.getByText(/SECOND DRIVE/i)).toBeInTheDocument();
    expect(screen.getByText(/High probability re-test/i)).toBeInTheDocument();
  });

  it('renders the first drive indicator when not flagged', () => {
    render(<AgentProbabilityCard agentDecision={decision} isSecondDrive={false} />);
    expect(screen.getByText(/FIRST DRIVE/i)).toBeInTheDocument();
  });

  it('renders regime and sanitized rationale in logic formulas', () => {
    render(<AgentProbabilityCard agentDecision={decision} isSecondDrive={undefined} />);
    expect(screen.getByText(/TRENDING/i)).toBeInTheDocument();
    expect(screen.getByText(/High conviction momentum continuation/)).toBeInTheDocument();
    expect(screen.getByText(/420μs/)).toBeInTheDocument();
  });
});
