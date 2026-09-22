import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import LayaDecisionCard from '../../../components/ai/LayaDecisionCard';
import { LayaDecision, QuantDecisionAnalysis } from '../../../types';

describe('LayaDecisionCard component', () => {
    it('renders neural edge header and latency pill', () => {
        const decision: LayaDecision = {
            action: 'ENTER_LONG',
            setup: 'TRIPLE_A',
            probabilities: { ENTER_LONG: 0.85, ENTER_SHORT: 0.05, FLAT: 0.10 },
            confidence: 0.85,
            trade_permitted_p: 0.90,
            latency_ms: 13.2,
            source: 'LAYA_MLX_MULTILINGUAL',
            model: 'Laya-MLX (322M mmBERT)',
        };

        render(<LayaDecisionCard layaDecision={decision} />);

        expect(screen.getByText(/Laya-MLX Neural Edge/i)).toBeInTheDocument();
        expect(screen.getByText(/Apple MLX Metal/i)).toBeInTheDocument();
        expect(screen.getByText(/13.2ms/i)).toBeInTheDocument();
        expect(screen.getByText(/ENTER LONG/i)).toBeInTheDocument();
        expect(screen.getByText(/TRIPLE_A/i)).toBeInTheDocument();
        expect(screen.getByText(/P\(LONG\): 85%/i)).toBeInTheDocument();
    });

    it('shows execution safety permitted state and conviction score', () => {
        const decision: LayaDecision = {
            action: 'FLAT',
            setup: 'NO_EDGE',
            probabilities: { ENTER_LONG: 0.05, ENTER_SHORT: 0.05, FLAT: 0.90 },
            confidence: 0.60,
            conviction_score: 3.20,
            score_max: 4.0,
            score_percent: 80,
            trade_permitted_p: 0.88,
            latency_ms: 11.5,
        };

        render(<LayaDecisionCard layaDecision={decision} />);

        expect(screen.getByText(/Execution Safety/i)).toBeInTheDocument();
        expect(screen.getByText(/88%/i)).toBeInTheDocument();
        expect(screen.getByText(/Permitted/i)).toBeInTheDocument();
        expect(screen.getByText(/Conviction Score/i)).toBeInTheDocument();
        expect(screen.getByText(/3.20 \/ 4.0/i)).toBeInTheDocument();
        expect(screen.getByText(/Role: Auction Scanner/i)).toBeInTheDocument();
    });

    it('renders Position Manager role with active position metrics', () => {
        const decision: LayaDecision = {
            role: 'POSITION_MANAGEMENT',
            action: 'HOLD',
            setup: 'POSITION_MGMT',
            active_position: {
                side: 'LONG',
                entryPrice: 6200.0,
                currentPrice: 6245.0,
                pnl: 45.0,
                stopLoss: 6215.0,
                takeProfit: 6320.0,
                barsHeld: 5,
                isRiskFree: true,
            },
            probabilities: { HOLD: 0.92, TIGHTEN_SL: 0.04, TAKE_PROFIT: 0.02, EXIT: 0.02 },
            confidence: 0.92,
            conviction_score: 3.65,
            trade_permitted_p: 0.98,
            thesis: 'Laya-MLX Position Manager: [HOLD] recommendation',
        };

        render(<LayaDecisionCard layaDecision={decision} />);

        expect(screen.getByText(/Role: Position Manager/i)).toBeInTheDocument();
        expect(screen.getByText(/HOLD \(TREND INTACT\)/i)).toBeInTheDocument();
        expect(screen.getByText(/Entry: 6200.00/i)).toBeInTheDocument();
        expect(screen.getByText(/\+45.00/i)).toBeInTheDocument();
        expect(screen.getByText(/Risk-Free/i)).toBeInTheDocument();
        expect(screen.getByText(/HOLD: 92%/i)).toBeInTheDocument();
        expect(screen.getByText(/Holding Conviction:/i)).toBeInTheDocument();
    });

    it('overrides stale scanning action (ENTER_LONG) with HOLD when position is open', () => {
        const staleDecision: LayaDecision = {
            role: 'SCANNING',
            action: 'ENTER_LONG',
            setup: 'NO_EDGE',
            probabilities: { HOLD: 0.80, TIGHTEN_SL: 0.10, TAKE_PROFIT: 0.05, EXIT: 0.05 },
            conviction_score: 1.69,
            active_position: {
                side: 'LONG',
                entryPrice: 6.80,
                currentPrice: 6.30,
                pnl: -62.50,
                stopLoss: 5.15,
                takeProfit: 10.10,
                barsHeld: 1,
                isRiskFree: false,
            },
        };

        render(<LayaDecisionCard layaDecision={staleDecision} />);

        expect(screen.getByText(/Role: Position Manager/i)).toBeInTheDocument();
        expect(screen.getByText(/HOLD \(TREND INTACT\)/i)).toBeInTheDocument();
        expect(screen.queryByText(/ENTER LONG/i)).not.toBeInTheDocument();
        expect(screen.getByText(/Entry: 6.80/i)).toBeInTheDocument();
        expect(screen.getByText(/-62.50/i)).toBeInTheDocument();
        expect(screen.getByText(/1.69 \/ 4.0/i)).toBeInTheDocument();
    });
});
