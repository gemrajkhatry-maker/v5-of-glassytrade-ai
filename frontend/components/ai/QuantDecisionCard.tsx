import React from 'react';
import { Zap } from 'lucide-react';
import { QuantDecisionAnalysis } from '../../types';

interface QuantDecisionCardProps {
    quantDecision: QuantDecisionAnalysis | null;
}

/** PRIMARY decision card — renders the quant decision when present. */
const QuantDecisionCard = React.memo<QuantDecisionCardProps>(({ quantDecision }) => {
    if (!quantDecision) return null;

    return (
        <div className={`p-3 rounded-md border ${quantDecision.approved ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-glassy-border-default bg-glassy-bg-elevated/30'}`}>
            <div className="flex items-center justify-between">
                <span className="text-[9px] font-bold uppercase tracking-widest text-glassy-text-secondary flex items-center gap-1.5">
                    <Zap className="w-3.5 h-3.5 text-glassy-ai-primary" /> Quant Decision
                </span>
                <span className={`px-1.5 py-0.5 rounded-sm text-[8px] font-bold tracking-widest uppercase ${quantDecision.approved ? 'bg-emerald-500/20 text-emerald-400' : 'bg-white/10 text-white/50'}`}>
                    {quantDecision.approved ? 'Approved' : 'Standing By'}
                </span>
            </div>
            {quantDecision.signal ? (
                <div className="mt-2">
                    <div className={`text-sm font-bold ${quantDecision.signal.type === 'LONG' ? 'text-glassy-bull-primary' : quantDecision.signal.type === 'SHORT' ? 'text-glassy-bear-primary' : 'text-glassy-text-primary'}`}>
                        {quantDecision.signal.type} @ {quantDecision.signal.entry.toFixed(2)}
                        <span className="text-[10px] font-mono text-glassy-text-tertiary ml-2">RR {quantDecision.signal.rr.toFixed(1)}</span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 mt-2 text-[9px] font-mono">
                        <div><div className="text-glassy-text-tertiary">SL</div><div className="font-bold text-glassy-bear-primary">{quantDecision.signal.sl.toFixed(2)}</div></div>
                        <div><div className="text-glassy-text-tertiary">TP</div><div className="font-bold text-glassy-bull-primary">{quantDecision.signal.tp.toFixed(2)}</div></div>
                        <div><div className="text-glassy-text-tertiary">Confidence</div><div className="font-bold text-glassy-text-primary">{(quantDecision.signal.confidence * 100).toFixed(0)}%</div></div>
                    </div>
                </div>
            ) : (
                <div className="mt-2 text-[10px] font-mono text-glassy-text-tertiary">
                    {quantDecision.reason || quantDecision.phase || 'No active signal'}
                </div>
            )}
            {quantDecision.phase && (
                <div className="mt-2 text-[9px] text-glassy-text-tertiary">
                    <span className="uppercase tracking-widest">Phase: {quantDecision.phase}</span>
                    {quantDecision.reason && !quantDecision.signal && <span className="ml-2">{quantDecision.reason}</span>}
                </div>
            )}
            {quantDecision.gateResults && quantDecision.gateResults.length > 0 && (
                <div className="mt-2.5">
                    <div className="text-[9px] uppercase tracking-widest text-glassy-text-tertiary mb-1.5">Triple-A Gates</div>
                    <div className="grid grid-cols-5 gap-1">
                        {quantDecision.gateResults.map(g => (
                            <div
                                key={g.gate}
                                title={`Gate ${g.gate}${g.name ? ` (${g.name})` : ''}: ${g.reason || (g.passed ? 'passed' : 'blocked')}`}
                                className={`rounded-sm border px-1 py-1 text-center ${g.passed ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' : 'border-rose-500/40 bg-rose-500/10 text-rose-400'}`}
                            >
                                <div className="text-[7px] font-bold leading-none">{g.name ?? `G${g.gate}`}</div>
                                <div className="text-[9px] font-bold leading-tight mt-0.5">{g.passed ? 'PASS' : 'BLOCK'}</div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
});

QuantDecisionCard.displayName = 'QuantDecisionCard';

export default QuantDecisionCard;
