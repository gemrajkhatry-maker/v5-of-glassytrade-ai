import React from 'react';
import { AMTAnalysis } from '../../types';
import { computeThreeA, ThreeAScore } from '../../utils/threeA';

type Verdict = 'ENTER' | 'MONITOR' | 'SKIP';

interface ThreeAIndicatorProps {
    amt: AMTAnalysis | null;
    /** quantDecision.approved from the backend — the single source of truth for ENTER. */
    approved: boolean;
}

const VERDICT_STYLE: Record<Verdict, string> = {
    ENTER: 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10',
    MONITOR: 'text-amber-300 border-amber-500/40 bg-amber-500/10',
    SKIP: 'text-rose-400 border-rose-500/40 bg-rose-500/10',
};

/**
 * Compact 3A traffic-light: Auction (market state), Area (value level),
 * Action (order-flow aggression). One glance at the scanner row tells which
 * of the three Valentini rules blocks a trade.
 *
 * IMPORTANT: the three lights and score are informational only (computeThreeA
 * is a pure re-derivation from streamed AMT fields, not a trading decision).
 * The ENTER/MONITOR/SKIP verdict is derived from `approved`
 * (quantDecision.approved, the engine's real decision) — never from the 3A
 * score alone. A 3/3 score with `approved=false` must render MONITOR, not
 * ENTER, or the UI would show a trade signal the engine never produced.
 */
export const ThreeAIndicator: React.FC<ThreeAIndicatorProps> = React.memo(({ amt, approved }) => {
    const s = computeThreeA(amt);
    const lights = [
        { label: 'Auction', on: s.auction },
        { label: 'Area', on: s.area },
        { label: 'Action', on: s.action },
    ];

    const verdict: Verdict = approved ? 'ENTER' : s.score >= 2 ? 'MONITOR' : 'SKIP';
    const verdictStyle = VERDICT_STYLE[verdict];

    return (
        <span className="inline-flex items-center gap-1.5 p-1 rounded-md bg-black/25 border border-white/5" title={`3A: Auction ${s.auction ? '✓' : '✗'} · Area ${s.area ? '✓' : '✗'} · Action ${s.action ? '✓' : '✗'}`}>
            <span className="inline-flex items-center gap-1">
                {lights.map((l) => (
                    <span
                        key={l.label}
                        data-3a-light
                        data-3a-label={l.label}
                        title={`${l.label}: ${l.on ? 'Pass' : 'Block'}`}
                        className={`w-2 h-2 rounded-full transition-all ${
                            l.on
                                ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.9)]'
                                : 'bg-slate-700 border border-slate-600'
                        }`}
                    />
                ))}
            </span>
            <span
                data-3a-score
                className={`px-1.5 py-0.5 rounded text-[8px] font-black font-mono leading-none border uppercase tracking-wider ${verdictStyle}`}
            >
                {s.score}/3 {verdict}
            </span>
        </span>
    );
});

ThreeAIndicator.displayName = 'ThreeAIndicator';

export default ThreeAIndicator;


