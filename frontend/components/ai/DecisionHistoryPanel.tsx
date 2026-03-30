import React from 'react';
import { LLMHistoryEntry } from '../../types';
import { Clock } from 'lucide-react';
import { sanitizeRationale } from '../../utils/textSanitizer';

interface DecisionHistoryPanelProps {
    llmHistory: LLMHistoryEntry[];
}

/** Expandable list of past LLM entry/exit decisions with prompt and output details. */
const DecisionHistoryPanel = React.memo<DecisionHistoryPanelProps>(({ llmHistory }) => {
    if (llmHistory.length === 0) return null;

    // Check for 3+ consecutive errors in the most recent history
    const recentErrorsCount = [...llmHistory].filter(h => h.rationale?.includes('404') || h.rationale?.includes('Error') || h.confidence === 'Error').length;
    const isErrorState = recentErrorsCount >= 3;

    return (
        <div className="flex flex-col gap-2 pt-2 border-t border-white/5 relative">
            {isErrorState && (
                <div className="absolute -top-10 left-0 right-0 bg-red-500/20 border border-red-500/50 text-red-200 text-[10px] font-bold py-1 px-2 rounded-lg text-center backdrop-blur-md z-10 animate-pulse">
                    ⚠️ AI Engine fallback failing — decisions may be stale
                </div>
            )}
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest mt-2">
                <div className="flex items-center gap-2">
                    <span>06. Decision History</span>
                    <span className="bg-white/10 px-1.5 py-0.5 rounded text-white/60">{llmHistory.length}</span>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-blue-300/80 hover:text-blue-300 cursor-pointer flex items-center gap-1 transition-colors">
                        Export CSV
                    </span>
                    <Clock className="w-3 h-3" />
                </div>
            </div>
            <div className="relative pl-3 space-y-3 max-h-[300px] overflow-y-auto overflow-x-hidden pr-1 before:absolute before:inset-y-0 before:left-[3px] before:w-px before:bg-white/10 mt-2">
                {[...llmHistory].reverse().map((entry, i) => {
                    const isError = entry.rationale?.includes('404') || entry.rationale?.includes('Error') || entry.confidence === 'Error';
                    const dirColor = isError ? 'text-red-500' : entry.direction === 'LONG' ? 'text-green-400' : entry.direction === 'SHORT' ? 'text-red-400' : 'text-blue-400';
                    const bgClass = isError ? 'bg-red-500/10 border-red-500/30' : entry.direction === 'LONG' ? 'bg-green-500/5 border-green-500/10' : entry.direction === 'SHORT' ? 'bg-red-500/5 border-red-500/10' : 'bg-blue-500/5 border-blue-500/10';
                    const timeStr = new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    return (
                        <div key={i} className="relative">
                            {/* Timeline dot */}
                            <div className={`absolute -left-[14px] top-[14px] w-1.5 h-1.5 rounded-full ${isError ? 'bg-red-500' : entry.direction === 'LONG' ? 'bg-green-400' : entry.direction === 'SHORT' ? 'bg-red-400' : 'bg-blue-400'} shadow-[0_0_5px_currentColor]`}></div>
                            
                            <div className={`p-2.5 rounded-lg border ${bgClass}`}>
                                <div className="flex justify-between items-center mb-1 text-[10px]">
                                    <div className="flex items-center gap-2">
                                        {isError ? (
                                            <span className="badge badge-error bg-red-500/20 text-red-400 px-1 rounded border border-red-500/30 font-bold text-[9px]">⚠️ API ERROR</span>
                                        ) : (
                                            <>
                                                <span className={`font-bold ${dirColor}`}>{entry.direction}</span>
                                                <span className="text-white/60 text-[9px] truncate max-w-[150px] font-mono bg-white/5 px-1 rounded">
                                                    {(() => {
                                                        let text = entry.rationale || entry.rawOutput || "";
                                                        try {
                                                            const match = text.match(/\{[\s\S]*\}/);
                                                            if (match) {
                                                                const p = JSON.parse(match[0]);
                                                                text = p.quant_reason || p.rationale || p.reason || p.direction || text;
                                                            }
                                                        } catch (e) {}
                                                        // Extract uppercase quant code
                                                        const match = text.match(/[A-Z_]{5,}/);
                                                        return match ? match[0] : text.split(' ')[0];
                                                    })()}
                                                </span>
                                            </>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-2">
                                        {isError ? null : entry.confidence === 'Overseer' ? (
                                            <span className="px-1.5 py-0.5 text-[8px] uppercase tracking-wider bg-blue-500/20 text-blue-300 rounded border border-blue-500/30">Overseer</span>
                                        ) : (
                                            <span className="text-white/40">Conf: <span className="text-white/70 font-bold">{entry.confidence}</span></span>
                                        )}
                                        <span className="text-white/30 font-mono text-[9px]">{timeStr}</span>
                                    </div>
                                </div>
                                <div className={`text-[9px] ${isError ? 'text-red-300' : 'text-white/50'} leading-relaxed mt-1 font-mono`}>
                                    {sanitizeRationale(entry.rationale) || 'No rationale available.'}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
});

DecisionHistoryPanel.displayName = 'DecisionHistoryPanel';

export default DecisionHistoryPanel;
