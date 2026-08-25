import React from 'react';
import { Brain, Sparkles, ShieldCheck, HelpCircle } from 'lucide-react';
import { AgentDecision, QuantDecisionAnalysis } from '../../types';

interface AIAdvisorCardProps {
    agentDecision?: AgentDecision | null;
    quantDecision?: QuantDecisionAnalysis | null;
}

export const AIAdvisorCard: React.FC<AIAdvisorCardProps> = React.memo(({ agentDecision, quantDecision }) => {
    if (!agentDecision && !quantDecision) return null;

    const rawDecision: any = agentDecision || {};
    const direction = (rawDecision.direction || 'FLAT').toUpperCase();
    const action = rawDecision.action || (direction !== 'FLAT' ? `ENTER_${direction}` : 'FLAT');
    const setup = rawDecision.setup || 'AMT_AUCTION';
    const confidence = rawDecision.confidence || (direction !== 'FLAT' ? 'High' : 'Low');
    const rationale = rawDecision.rationale || rawDecision.reason || 'Analyzing volume profile and order flow...';
    const source = rawDecision.source || 'MLX_LOCAL';
    const latencyMs = rawDecision.latencyMs;

    // Check agreement with deterministic quant decision
    const quantApproved = quantDecision?.approved && !!quantDecision?.signal;
    const quantDir = quantDecision?.signal?.type || 'FLAT';
    const isAligned = direction === quantDir;

    const dirColor = direction === 'LONG'
        ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
        : direction === 'SHORT'
        ? 'text-rose-400 border-rose-500/30 bg-rose-500/10'
        : 'text-slate-400 border-white/10 bg-white/5';

    const confColor = confidence === 'High'
        ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/15'
        : confidence === 'Medium'
        ? 'text-amber-300 border-amber-500/30 bg-amber-500/15'
        : 'text-slate-400 border-white/10 bg-slate-800/40';

    return (
        <div className="p-3.5 rounded-xl border border-purple-500/20 bg-purple-950/10 backdrop-blur-md shadow-[0_0_16px_rgba(168,85,247,0.06)] space-y-2.5">
            {/* Header */}
            <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-widest text-purple-300 flex items-center gap-1.5">
                    <Brain className="w-3.5 h-3.5 text-purple-400" />
                    AI Market Thesis
                </span>
                <div className="flex items-center gap-1.5">
                    {latencyMs && (
                        <span className="text-[8px] font-mono text-slate-500">
                            {latencyMs}ms
                        </span>
                    )}
                    <span className="px-1.5 py-0.5 rounded text-[8px] font-mono font-bold uppercase tracking-wider bg-purple-500/15 text-purple-300 border border-purple-500/25">
                        {source}
                    </span>
                </div>
            </div>

            {/* Badges: Direction + Setup + Confidence */}
            <div className="flex items-center gap-2 flex-wrap">
                <span className={`px-2 py-0.5 rounded text-[9px] font-mono font-black border uppercase tracking-wider ${dirColor}`}>
                    {direction}
                </span>
                <span className="px-2 py-0.5 rounded text-[8px] font-mono font-bold bg-white/5 text-slate-300 border border-white/10 uppercase">
                    {setup}
                </span>
                <span className={`px-1.5 py-0.5 rounded text-[8px] font-mono font-semibold border ${confColor}`}>
                    {confidence} Conviction
                </span>
            </div>

            {/* Narrative Reasoning */}
            <div className="p-2.5 rounded-lg bg-black/30 border border-white/5 text-[10px] text-slate-200 leading-relaxed font-sans">
                <div className="flex items-start gap-1.5">
                    <Sparkles className="w-3 h-3 text-purple-400 shrink-0 mt-0.5" />
                    <p className="min-w-0">{rationale}</p>
                </div>
            </div>

            {/* Alignment status with Quantitative Gate Engine */}
            <div className="flex items-center justify-between text-[8.5px] font-mono pt-1 border-t border-white/5 text-slate-400">
                <span className="text-slate-500 uppercase tracking-wider">Quant Engine Alignment:</span>
                <span className={`font-semibold flex items-center gap-1 ${isAligned ? 'text-emerald-400' : 'text-amber-300'}`}>
                    {isAligned ? (
                        <>
                            <ShieldCheck className="w-2.5 h-2.5" />
                            Aligned ({direction})
                        </>
                    ) : (
                        <>
                            <HelpCircle className="w-2.5 h-2.5" />
                            {quantApproved ? `Quant: ${quantDir}` : 'Quant: Standing By'}
                        </>
                    )}
                </span>
            </div>
        </div>
    );
});

AIAdvisorCard.displayName = 'AIAdvisorCard';
export default AIAdvisorCard;
