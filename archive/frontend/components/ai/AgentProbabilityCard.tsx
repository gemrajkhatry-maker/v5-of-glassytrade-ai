import React from 'react';
import { Brain } from 'lucide-react';
import { AgentDecision } from '../../types';
import { sanitizeRationale } from '../../utils/textSanitizer';

interface AgentProbabilityCardProps {
    agentDecision: AgentDecision | null;
    isSecondDrive?: boolean;
}

/** 04. PROBABILITY ENGINE — direction, P(target), timing/size, drive cycle, formulas. */
const AgentProbabilityCard = React.memo<AgentProbabilityCardProps>(({ agentDecision, isSecondDrive }) => {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>04. Probability</span>
                <Brain className="w-3 h-3 hover:text-white/80 transition-colors" />
            </div>
            <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2 relative overflow-hidden">
                {agentDecision ? (
                    <>
                        <div className={`absolute top-0 left-0 w-1 h-full ${agentDecision.timing === 'ENTER_NOW' ? 'bg-emerald-500' : 'bg-yellow-500/50'}`} />
                        <div className="flex justify-between items-center pl-2">
                            <span className="text-[10px] text-white/40">Direction</span>
                            <span className={`text-xs font-bold ${agentDecision.direction === 'LONG' ? 'text-emerald-400' : agentDecision.direction === 'SHORT' ? 'text-red-400' : 'text-blue-300'}`}>
                                {(() => {
                                    const dir = agentDecision?.direction || 'FLAT';
                                    const regime = agentDecision?.regime || '';

                                    if (dir === 'FLAT') return 'FLAT';

                                    // Map direction to option action
                                    const action = dir === 'LONG' ? 'BUY' : 'SELL';

                                    // AMT playbook terminology
                                    const playbookLabel = regime === 'TRENDING' ? 'Initiative Trend' :
                                                          regime === 'BALANCED' ? 'Responsive Fade' :
                                                          regime === 'PROBING' ? 'Breakout Test' :
                                                          regime === 'DEAD' ? 'Failed Auction' : regime;

                                    return `${action} (${playbookLabel})`;
                                })()}
                            </span>
                        </div>
                        <div className="flex justify-between items-center pl-2">
                            <span className="text-[10px] text-white/40">P(target)</span>
                            <span className={`text-xs font-mono font-bold ${agentDecision.probability >= 0.6 ? 'text-emerald-400' : agentDecision.probability > 0.45 ? 'text-yellow-400' : agentDecision.probability > 0 ? 'text-red-400' : 'text-white/30'}`}>
                                {(agentDecision.probability * 100).toFixed(1)}%
                            </span>
                        </div>
                        {/* Probability bar */}
                        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden ml-2">
                            <div className="h-full rounded-full transition-all duration-500" style={{
                                width: `${Math.min(agentDecision.probability * 100, 100)}%`,
                                backgroundColor: agentDecision.probability >= 0.6 ? '#4ade80' : agentDecision.probability > 0.45 ? '#facc15' : agentDecision.probability > 0 ? '#f87171' : '#334155',
                            }} />
                        </div>
                        <div className="flex justify-between items-center pl-2 pt-1">
                            <span className="text-[10px] text-white/40">Timing / Size</span>
                            <div className="flex items-center gap-2">
                                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-bold tracking-wider ${agentDecision.timing === 'ENTER_NOW' ? 'bg-emerald-500/20 text-emerald-400' : agentDecision.timing === 'SKIP' ? 'bg-white/10 text-white/30' : 'bg-yellow-500/20 text-yellow-400'}`}>
                                    {agentDecision.timing}
                                </span>
                                <span className="text-[10px] font-mono font-bold text-white/80">{(agentDecision.sizeFraction * 100).toFixed(1)}%</span>
                            </div>
                        </div>

                        {/* Fabio Playbook: Second Drive Indicator */}
                        {isSecondDrive !== undefined && (
                            <div className="flex justify-between items-center pl-2 pt-1">
                                <span className="text-[10px] text-white/40">Drive Cycle</span>
                                {isSecondDrive ? (
                                    <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                        <span>✅ SECOND DRIVE</span>
                                        <span className="text-[8px] font-normal text-white/50">High probability re-test</span>
                                    </div>
                                ) : (
                                    <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
                                        <span>⚠️ FIRST DRIVE</span>
                                        <span className="text-[8px] font-normal text-white/50">Wait for re-test if possible</span>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Logic Formulas */}
                        <details className="group mt-2 pt-2 border-t border-white/5 pl-2 cursor-pointer">
                            <summary className="list-none flex justify-between items-center text-[9px] text-white/40 uppercase tracking-widest font-bold">
                                <span>Logic Formulas</span>
                                <span className="group-open:hidden">Expand</span>
                                <span className="hidden group-open:block">Collapse</span>
                            </summary>
                            <div className="mt-2 space-y-1">
                                <div className="flex justify-between items-center">
                                    <span className="text-[9px] text-white/40">Regime</span>
                                    <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${agentDecision.regime === 'TRENDING' ? 'bg-purple-500/20 text-purple-400' :
                                        agentDecision.regime === 'BALANCED' ? 'bg-blue-500/20 text-blue-400' :
                                            agentDecision.regime === 'VOLATILE' ? 'bg-orange-500/20 text-orange-400' :
                                                'bg-white/10 text-white/40'
                                        }`}>{agentDecision.regime}</span>
                                </div>
                                <div className="text-[9px] text-white/30 font-mono mt-1 bg-black/20 p-1.5 rounded">
                                    {sanitizeRationale(agentDecision.rationale)} <span className="text-white/20">({agentDecision.latencyUs}μs)</span>
                                </div>
                            </div>
                        </details>
                    </>
                ) : (
                    <div className="text-[10px] text-white/30 text-center py-2">Waiting for probability engine...</div>
                )}
            </div>
        </div>
    );
});

AgentProbabilityCard.displayName = 'AgentProbabilityCard';

export default AgentProbabilityCard;
