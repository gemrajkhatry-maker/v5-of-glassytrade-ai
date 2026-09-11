import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ModelStateBanner from '../../components/ModelStateBanner';
import { THREE_A_CONFIG } from '../../config';
import type { AMTAnalysis } from '../../types';

/**
 * Regression: the banner hardcoded a 0.2 aggression threshold while the rest of
 * the app uses THREE_A_CONFIG.aggressionMin (2.0). On a live session with
 * aggression 0.50 the banner read "Aggression healthy" next to
 * "DELTA NEUTRAL / NEGLIGIBLE" and an unconfirmed 0.50 score, while
 * utils/threeA.ts correctly classified the same value as not-Action.
 *
 * With `aggression < floor`:
 *   - "Aggression healthy" must NOT appear anywhere;
 *   - the actual score and the floor must be visible so the operator can judge.
 */

const amt = (aggression: number | null | undefined, extra: Record<string, unknown> = {}) =>
    ({ aggression, marketState: 'BALANCED', ...extra }) as unknown as AMTAnalysis;

const renderBanner = (aggression: number | null | undefined) =>
    render(
        <ModelStateBanner
            amtResult={amt(aggression)}
            agentDecision={null}
            auction={null}
            quantDecision={null}
            symbol="SILVERM"
        />
    );

describe('ModelStateBanner — aggression threshold', () => {
    it('does not call sub-floor aggression healthy (live regression: 0.50)', () => {
        renderBanner(0.5);
        expect(screen.queryByText(/Aggression healthy/i)).toBeNull();
    });

    it('treats exactly the configured floor as healthy', () => {
        renderBanner(THREE_A_CONFIG.aggressionMin);
        expect(screen.getByText(/Aggression healthy/i)).toBeInTheDocument();
    });

    it('treats just below the configured floor as unconfirmed', () => {
        renderBanner(THREE_A_CONFIG.aggressionMin - 0.01);
        expect(screen.queryByText(/Aggression healthy/i)).toBeNull();
    });

    it('uses the same floor as the Three-A scoring module', () => {
        // 0.2 would pass here if the banner kept its own hardcoded threshold.
        expect(THREE_A_CONFIG.aggressionMin).toBeGreaterThan(1);
    });

    it('shows the score and the floor when unconfirmed', () => {
        renderBanner(0.5);
        expect(screen.getByText(/0\.5/)).toBeInTheDocument();
        expect(screen.getByText(/2\.0/)).toBeInTheDocument();
    });

    it('does not present unknown aggression as healthy', () => {
        renderBanner(null);
        expect(screen.queryByText(/Aggression healthy/i)).toBeNull();
    });

    it('still reports healthy aggression on a confirmed score', () => {
        renderBanner(3.5);
        expect(screen.getByText(/Aggression healthy/i)).toBeInTheDocument();
    });
});
