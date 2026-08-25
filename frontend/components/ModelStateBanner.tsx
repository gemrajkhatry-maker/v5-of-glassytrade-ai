import React, { useMemo } from 'react';
import { Brain } from 'lucide-react';
import type { AMTAnalysis, AgentDecision, AuctionAnalysis, QuantDecisionAnalysis } from '../types';

export interface ModelStateBannerProps {
    amtResult: AMTAnalysis | null | undefined;
    agentDecision: AgentDecision | null | undefined;
    auction: AuctionAnalysis | null | undefined;
    quantDecision: QuantDecisionAnalysis | null | undefined;
    symbol: string;
}

/**
 * Single primary status strip for the active symbol: monitoring, dead, advisory entry, or armed (ENTER_NOW).
 */
const ModelStateBanner = React.memo<ModelStateBannerProps>(({ amtResult, agentDecision, auction, quantDecision, symbol }) => {
    const { title, subtitle, barClass, accentClass } = useMemo(() => {
        const isDead = amtResult?.marketState === 'DEAD';
        const volLow = amtResult?.aggression != null && amtResult.aggression < 0.2;
        const volMsg = volLow ? 'Low aggression — edge may be thin' : 'Aggression healthy';
        const armed = agentDecision?.timing === 'ENTER_NOW';
        const dir = agentDecision?.direction;
        const hasEntry = dir && dir !== 'FLAT';

        // IB break state — setup in progress
        const ibBreak = amtResult?.breakDirection;
        const ibComplete = amtResult?.ibComplete;
        const isIBBreak = ibComplete && (ibBreak === 'UP' || ibBreak === 'DOWN');

        if (isDead) {
            return {
                title: 'SLEEPING — Dead or no-trade session',
                subtitle: `${symbol} · Scan paused for this context · ${volMsg}`,
                barClass: 'bg-red-950/90 border-red-500/40',
                accentClass: 'text-red-200',
            };
        }
        if (armed) {
            const d = agentDecision?.direction && agentDecision.direction !== 'FLAT' ? agentDecision.direction : dir || 'FLAT';
            const label = agentDecision?.modelLabel || '';
            return {
                title: `ARMED — ENTER NOW (${d})`,
                subtitle: label ? `${symbol} · ${label} · ${volMsg}` : `${symbol} · ${volMsg}`,
                barClass: 'bg-emerald-950/90 border-emerald-400/50',
                accentClass: 'text-emerald-100',
            };
        }
        if (isIBBreak) {
            const breakLabel = ibBreak === 'UP' ? 'IB BREAK ↑' : 'IB BREAK ↓';
            const setupLabel = hasEntry ? 'SETUP ACTIVE' : 'SETUP IN PROGRESS';
            const breakDesc = ibBreak === 'UP' ? 'Initiative upside break' : 'Initiative downside break';
            return {
                title: `${breakLabel} — ${setupLabel}`,
                subtitle: `${symbol} · ${breakDesc} · ${volMsg}`,
                barClass: ibBreak === 'UP' ? 'bg-emerald-950/90 border-emerald-400/50' : 'bg-red-950/90 border-red-400/50',
                accentClass: ibBreak === 'UP' ? 'text-emerald-100' : 'text-red-100',
            };
        }
        if (hasEntry) {
            return {
                title: `ADVISORY — Model favors ${dir}`,
                subtitle: `${symbol} · Await timing gate · ${volMsg}`,
                barClass: 'bg-amber-950/80 border-amber-500/35',
                accentClass: 'text-amber-100',
            };
        }
        return {
            title: 'MONITORING — No setup',
            subtitle: `${symbol} · Live book & AMT · ${volMsg}`,
            barClass: 'bg-slate-900/95 border-white/15',
            accentClass: 'text-slate-100',
        };
    }, [amtResult, agentDecision, symbol]);

    return (
        <div
            className={`w-fit max-w-xl rounded-lg border px-3 py-1.5 shadow-lg backdrop-blur-md ${barClass}`}
            role="status"
            aria-live="polite"
        >
            <div className="flex items-center gap-2.5 min-w-0">
                <Brain className={`w-3.5 h-3.5 shrink-0 ${accentClass} opacity-90`} />
                <div className="min-w-0">
                    <div className={`text-xs font-bold tracking-wide uppercase leading-tight ${accentClass}`}>{title}</div>
                    <div className="text-[9.5px] text-white/60 font-mono truncate mt-0.5">{subtitle}</div>
                </div>
                <div className="hidden sm:flex items-center gap-2 shrink-0 text-[8.5px] font-mono text-white/40 uppercase pl-2 border-l border-white/10">
                    {auction?.tripleASignal && (
                        <span className={`px-1.5 py-0.5 rounded-sm border ${auction.tripleASignal === 'LONG' ? 'border-emerald-500/40 text-emerald-300' : 'border-rose-500/40 text-rose-300'}`}>
                            TRIPLE-A {auction.tripleASignal} ({auction.tripleAPhase})
                        </span>
                    )}
                    {auction?.absorption && (
                        <span className="px-1.5 py-0.5 rounded-sm border border-amber-500/40 text-amber-300">
                            {auction.absorption.side} ABSORPTION
                        </span>
                    )}
                    {quantDecision?.approved && quantDecision.signal && (
                        <span className={`px-1.5 py-0.5 rounded-sm border ${quantDecision.signal.type === 'LONG' ? 'border-emerald-500/40 text-emerald-300' : 'border-rose-500/40 text-rose-300'} font-bold`}>
                            DECISION {quantDecision.signal.type} @{quantDecision.signal.entry.toFixed(2)} (RR {quantDecision.signal.rr.toFixed(1)})
                        </span>
                    )}
                    <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        Live
                    </span>
                </div>
            </div>
        </div>
    );
});

ModelStateBanner.displayName = 'ModelStateBanner';

export default ModelStateBanner;
