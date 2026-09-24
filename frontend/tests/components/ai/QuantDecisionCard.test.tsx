import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import QuantDecisionCard from '../../../components/ai/QuantDecisionCard';
import { QuantDecisionAnalysis } from '../../../types';

const haltedRisk = {
  halted: true,
  haltReason: 'Daily loss limit reached',
  consecutiveLosses: 3,
  dailyPnl: -20000,
  baseRiskPct: 0.0025,
  effectiveBaseRiskPct: 0.0025,
  riskPerTradePct: 0.0025,
  maxDailyLossPct: 0.02,
  maxConsecutiveLosses: 3,
  effectiveHmpTier: 'CONSERVATIVE',
};

const haltedDecision: QuantDecisionAnalysis = {
  approved: false,
  reason: 'HALTED',
  phase: '',
  blockReasons: ['Risk: daily loss limit'],
  signal: null,
};

const approved: QuantDecisionAnalysis = {
  approved: true,
  reason: 'Triple-A',
  phase: 'AGGRESSION',
  signal: { type: 'LONG', entry: 104.0, sl: 99.54, tp: 112.92, rr: 2.0, modelLabel: 'Triple-A' },
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

  it('renders the approved signal with SL/TP/modelLabel', () => {
    const approvedWithModel: QuantDecisionAnalysis = {
      ...approved,
      modelLabel: 'Triple-A',
      signal: { ...approved.signal!, modelLabel: 'Triple-A' },
    };
    render(<QuantDecisionCard quantDecision={approvedWithModel} />);
    expect(screen.getByText(/Quant Decision/i)).toBeInTheDocument();
    expect(screen.getByText(/Approved/i)).toBeInTheDocument();
    expect(screen.getByText(/LONG @ 104.00/i)).toBeInTheDocument();
    expect(screen.getByText(/RR 2.0/i)).toBeInTheDocument();
    expect(screen.getByText('99.54')).toBeInTheDocument();
    expect(screen.getByText('112.92')).toBeInTheDocument();
    expect(screen.getByText('Triple-A')).toBeInTheDocument();
    expect(screen.getByText(/Phase: AGGRESSION/i)).toBeInTheDocument();
  });

  it('does not show stale HALTED after live risk is cleared', () => {
    const halted: QuantDecisionAnalysis = {
      approved: false,
      reason: 'HALTED',
      phase: '',
      blockReasons: ['Risk: external/emergency: SIGTERM shutdown'],
      signal: null,
    };
    render(<QuantDecisionCard quantDecision={halted} riskState={{
      halted: false,
      haltReason: '',
      consecutiveLosses: 0,
      dailyPnl: 0,
      baseRiskPct: 0.0025,
      effectiveBaseRiskPct: 0.0025,
      riskPerTradePct: 0.0025,
      maxDailyLossPct: 0.02,
      maxConsecutiveLosses: 3,
      effectiveHmpTier: 'CONSERVATIVE',
    }} />);
    expect(screen.queryByText(/HALTED:/i)).toBeNull();
    expect(screen.queryByText(/SIGTERM shutdown/i)).toBeNull();
    expect(screen.getByText(/Standing By/i)).toBeInTheDocument();
  });

  it('renders Standing By state and reason when there is no signal', () => {
    render(<QuantDecisionCard quantDecision={rejected} />);
    expect(screen.getByText(/Standing By/i)).toBeInTheDocument();
    expect(screen.queryByText(/LONG @/i)).toBeNull();
    expect(screen.queryByText(/SHORT @/i)).toBeNull();
  });

  it('renders 7-gate pass/block grid when gateResults are provided', () => {
    const with7Gates: QuantDecisionAnalysis = {
      approved: true,
      reason: 'All gates passed',
      phase: 'EXECUTION',
      gateResults: [
        { gate: 1, name: 'G1_Structure', passed: true, reason: 'Trend intact' },
        { gate: 2, name: 'G2_Location', passed: true, reason: 'At LVN edge' },
        { gate: 3, name: 'G3_Aggression', passed: true, reason: 'Delta spike' },
        { gate: 4, name: 'G4_Absorption', passed: true, reason: 'Passive buyers present' },
        { gate: 5, name: 'G5_Freeze', passed: true, reason: 'VA expanding' },
        { gate: 6, name: 'G6_RiskReward', passed: true, reason: 'RR > 1.5' },
        { gate: 7, name: 'G7_Timing', passed: true, reason: 'Initiative tick confirmed' },
      ],
      signal: { type: 'LONG', entry: 104.0, sl: 99.54, tp: 112.92, rr: 2.0, modelLabel: 'Triple-A' },
    };

    render(<QuantDecisionCard quantDecision={with7Gates} />);
    expect(screen.getByText(/Triple-A Gates/i)).toBeInTheDocument();
    expect(screen.getByText('G1_Structure')).toBeInTheDocument();
    expect(screen.getByText('G7_Timing')).toBeInTheDocument();
    const passElements = screen.getAllByText('PASS');
    expect(passElements.length).toBe(7);
  });

  describe('risk reset control', () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('does not call the endpoint when the operator cancels confirmation', async () => {
      const fetchMock = vi.spyOn(globalThis, 'fetch');
      vi.spyOn(window, 'confirm').mockReturnValue(false);
      const user = userEvent.setup();
      render(<QuantDecisionCard quantDecision={haltedDecision} riskState={haltedRisk} />);
      await user.click(screen.getByRole('button', { name: /reset risk/i }));
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('shows operator-authorization feedback when the server rejects the reset', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('forbidden', { status: 403 }),
      );
      const user = userEvent.setup();
      render(<QuantDecisionCard quantDecision={haltedDecision} riskState={haltedRisk} />);
      await user.click(screen.getByRole('button', { name: /reset risk/i }));
      await waitFor(() =>
        expect(screen.getByRole('status')).toHaveTextContent(/operator authorization required/i),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/trading/risk/reset',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    it('sends the bearer token and reports success when the server accepts', async () => {
      localStorage.setItem('glassytrade.operator-token', 'tok-123');
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
      );
      const user = userEvent.setup();
      render(<QuantDecisionCard quantDecision={haltedDecision} riskState={haltedRisk} />);
      await user.click(screen.getByRole('button', { name: /reset risk/i }));
      await waitFor(() =>
        expect(screen.getByRole('status')).toHaveTextContent(/risk reset requested/i),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/trading/risk/reset',
        expect.objectContaining({
          method: 'POST',
          headers: { Authorization: 'Bearer tok-123' },
        }),
      );
      localStorage.removeItem('glassytrade.operator-token');
    });
  });
});

