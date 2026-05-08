import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DecisionTab from '../../../../components/intelligence/tabs/DecisionTab';

describe('DecisionTab', () => {
  const defaultProps = {
    analysis: {
      direction: 'LONG' as const,
      confidence: 'High' as const,
      rationale: 'Strong bullish momentum with volume confirmation',
      rawOutput: 'Full analysis output',
    },
    amtResult: {
      sessionVwap: 50000,
      poc: 50000,
      valueAreaHigh: 50500,
      valueAreaLow: 49500,
      marketState: 'BALANCED',
      amtTimeWindow: { label: 'First Hour' },
    } as any,
    agentDecision: {
      probability: 0.75,
      timing: 'ENTER_NOW',
    },
    symbol: 'NIFTY',
  };

  it('displays Direction header', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.getByText('Direction')).toBeInTheDocument();
  });

  it('displays Confidence header', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.getByText('Confidence')).toBeInTheDocument();
  });

  it('displays LONG direction', () => {
    render(<DecisionTab {...defaultProps} analysis={{ ...defaultProps.analysis!, direction: 'LONG' }} />);
    expect(screen.getByText('LONG')).toBeInTheDocument();
  });

  it('displays SHORT direction', () => {
    render(<DecisionTab {...defaultProps} analysis={{ ...defaultProps.analysis!, direction: 'SHORT' }} />);
    expect(screen.getByText('SHORT')).toBeInTheDocument();
  });

  it('displays FLAT direction', () => {
    render(<DecisionTab {...defaultProps} analysis={{ ...defaultProps.analysis!, direction: 'FLAT' }} />);
    expect(screen.getByText('FLAT')).toBeInTheDocument();
  });

  it('displays High confidence as 75%', () => {
    render(<DecisionTab {...defaultProps} analysis={{ ...defaultProps.analysis!, confidence: 'High' }} />);
    expect(screen.getByText('75.0%')).toBeInTheDocument();
  });

  it('displays Medium confidence as 50%', () => {
    render(<DecisionTab {...defaultProps} analysis={{ ...defaultProps.analysis!, confidence: 'Medium' }} />);
    expect(screen.getByText('50.0%')).toBeInTheDocument();
  });

  it('displays Low confidence as 25%', () => {
    render(<DecisionTab {...defaultProps} analysis={{ ...defaultProps.analysis!, confidence: 'Low' }} />);
    expect(screen.getByText('25.0%')).toBeInTheDocument();
  });

  it('displays LLM rationale', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.getByText(/Strong bullish momentum/)).toBeInTheDocument();
  });

  it('shows Decision Validation Rules expandable section', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.getByText('Decision Validation Rules')).toBeInTheDocument();
    expect(screen.getByText('Expand')).toBeInTheDocument();
  });

  it('shows Price Context validation', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.getByText('Price Context')).toBeInTheDocument();
  });

  it('shows At POC when LTP near POC', () => {
    render(<DecisionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, sessionVwap: 50000, poc: 50000 }} />);
    expect(screen.getByText(/At POC/)).toBeInTheDocument();
  });

  it('shows Above VAH when LTP > VAH', () => {
    render(<DecisionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, sessionVwap: 51000, valueAreaHigh: 50500 }} />);
    expect(screen.getByText(/Above VAH/)).toBeInTheDocument();
  });

  it('shows Below VAL when LTP < VAL', () => {
    render(<DecisionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, sessionVwap: 49000, valueAreaLow: 49500 }} />);
    expect(screen.getByText(/Below VAL/)).toBeInTheDocument();
  });

  it('shows Volume Alive validation', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.getByText('Volume Alive')).toBeInTheDocument();
  });

  it('shows ACTIVE when market not DEAD', () => {
    render(<DecisionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, marketState: 'BALANCED' }} />);
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
  });

  it('shows DEAD when market is DEAD', () => {
    render(<DecisionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, marketState: 'DEAD' }} />);
    expect(screen.getByText('DEAD')).toBeInTheDocument();
  });

  it('shows Timing validation', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.getByText('Timing')).toBeInTheDocument();
  });

  it('shows ENTER_NOW timing', () => {
    render(<DecisionTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, timing: 'ENTER_NOW' }} />);
    expect(screen.getByText('ENTER_NOW')).toBeInTheDocument();
  });

  it('shows SKIP timing', () => {
    render(<DecisionTab {...defaultProps} agentDecision={{ ...defaultProps.agentDecision!, timing: 'SKIP' }} />);
    expect(screen.getByText('SKIP')).toBeInTheDocument();
  });

  it('shows time window label', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.getByText('First Hour')).toBeInTheDocument();
  });

  it('shows LLM Timeout warning when no analysis', () => {
    render(<DecisionTab {...defaultProps} analysis={null} />);
    expect(screen.getByText(/LLM Timeout/)).toBeInTheDocument();
  });

  it('shows Running on Quant Only warning', () => {
    render(<DecisionTab {...defaultProps} analysis={null} />);
    expect(screen.getByText(/Running on Quant Logic Only/)).toBeInTheDocument();
  });

  it('does not show timeout warning when analysis present', () => {
    render(<DecisionTab {...defaultProps} />);
    expect(screen.queryByText(/LLM Timeout/)).not.toBeInTheDocument();
  });

  it('sanitizes think tags from rationale', () => {
    const analysisWithThink = {
      ...defaultProps.analysis!,
      rationale: '<think>thinking</think>Rational here',
    };
    render(<DecisionTab {...defaultProps} analysis={analysisWithThink} />);
    expect(screen.queryByText('<think>')).not.toBeInTheDocument();
    expect(screen.getByText(/Rational here/)).toBeInTheDocument();
  });

  it('sanitizes INST tags from rationale', () => {
    const analysisWithInst = {
      ...defaultProps.analysis!,
      rationale: '[INST]instruction[/INST]Rational here',
    };
    render(<DecisionTab {...defaultProps} analysis={analysisWithInst} />);
    expect(screen.queryByText('[INST]')).not.toBeInTheDocument();
  });

  it('handles null analysis with fallback', () => {
    render(<DecisionTab {...defaultProps} analysis={null} />);
    expect(screen.getByText('FLAT')).toBeInTheDocument();
    expect(screen.getByText('25.0%')).toBeInTheDocument();
  });

  it('uses rawOutput when rationale is empty', () => {
    render(<DecisionTab {...defaultProps} analysis={{ ...defaultProps.analysis!, rationale: '', rawOutput: 'Raw output here' }} />);
    expect(screen.getByText(/Raw output here/)).toBeInTheDocument();
  });

  it('handles null amtResult gracefully', () => {
    render(<DecisionTab {...defaultProps} amtResult={null} />);
    // Should not crash
    expect(screen.getByText('Direction')).toBeInTheDocument();
  });

  it('handles null agentDecision gracefully', () => {
    render(<DecisionTab {...defaultProps} agentDecision={null} />);
    // Should show SKIP as default
    expect(screen.getByText('Timing')).toBeInTheDocument();
  });

  it('shows prior day levels when available', () => {
    const amtWithPrior = {
      ...defaultProps.amtResult,
      priorVah: 50600,
      priorVal: 49400,
      priorPoc: 50000,
    };
    render(<DecisionTab {...defaultProps} amtResult={amtWithPrior} />);
    expect(screen.getByText(/P-VAH:/)).toBeInTheDocument();
    expect(screen.getByText(/P-VAL:/)).toBeInTheDocument();
    expect(screen.getByText(/P-POC:/)).toBeInTheDocument();
  });

  it('does not show prior levels when not available', () => {
    render(<DecisionTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, priorVah: undefined, priorVal: undefined, priorPoc: undefined }} />);
    expect(screen.queryByText(/P-VAH:/)).not.toBeInTheDocument();
  });
});
