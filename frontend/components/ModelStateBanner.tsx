import React, { useMemo } from 'react';
import { Brain } from 'lucide-react';
import type { GenAIAnalysis, AMTAnalysis, AgentDecision } from '../types';

export interface ModelStateBannerProps {
    genAI: GenAIAnalysis | null | undefined;
    amtResult: AMTAnalysis | null | undefined;
    agentDecision: AgentDecision | null | undefined;
    symbol: string;
}

/**
 * Single primary status strip for the active symbol: monitoring, dead, advisory entry, or armed (ENTER_NOW).
 */
const ModelStateBanner = React.memo<ModelStateBannerProps>(({ genAI, amtResult, agentDecision, symbol }) => {
    const { title, subtitle, barClass, accentClass } = useMemo(() => {
        const isDead =
            genAI?.rationale?.includes('DEAD') ||
            genAI?.rawOutput?.includes('QUANT_DEAD_MARKET') ||
            amtResult?.marketState === 'DEAD';
        const volLow = amtResult?.aggression != null && amtResult.aggression < 0.2;
        const volMsg = volLow ? 'Vol below prior session avg — edge may be thin' : 'Vol healthy vs prior session avg';
        const armed = agentDecision?.timing === 'ENTER_NOW';
        const dir = genAI?.direction;
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
            const p = agentDecision?.probability != null ? Math.round(agentDecision.probability * 100) : null;
            return {
                title: `ARMED — ENTER NOW (${d})`,
                subtitle: p != null ? `${symbol} · Quant timing +${p}% prob · ${volMsg}` : `${symbol} · ${volMsg}`,
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
    }, [genAI, amtResult, agentDecision, symbol]);

    return (
        <div
            className={`w-full rounded-lg border px-4 py-2.5 shadow-lg backdrop-blur-md ${barClass}`}
            role="status"
            aria-live="polite"
        >
            <div className="flex flex-wrap items-center gap-2 min-w-0">
                <Brain className={`w-4 h-4 shrink-0 ${accentClass} opacity-90`} />
                <div className="min-w-0 flex-1">
                    <div className={`text-sm font-bold tracking-wide uppercase ${accentClass}`}>{title}</div>
                    <div className="text-[10px] text-white/55 font-mono truncate mt-0.5">{subtitle}</div>
                </div>
                <div className="hidden sm:flex items-center gap-2 shrink-0 text-[9px] font-mono text-white/40 uppercase">
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
