import React, { useState, useCallback } from 'react';
import { DecisionHistoryEntry } from '../../types';
import { Clock } from 'lucide-react';

interface DecisionHistoryPanelProps {
    decisionHistory: DecisionHistoryEntry[];
}

/**
 * Compact timeline of deterministic quant decisions; expand a row for the
 * full rationale and gate block reasons. Backed entirely by the engine's
 * quantDecision stream — no LLM involved.
 */
const DecisionHistoryPanel = React.memo<DecisionHistoryPanelProps>(({ decisionHistory }) => {
    const [expandedRevIdx, setExpandedRevIdx] = useState<number | null>(null);
    const toggle = useCallback((revIdx: number) => {
        setExpandedRevIdx((cur) => (cur === revIdx ? null : revIdx));
    }, []);

    if (decisionHistory.length === 0) return null;

    const reversed = [...decisionHistory].reverse();

    return (
        <div className="flex flex-col gap-2 pt-2 border-t border-white/5 relative">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest mt-2">
                <div className="flex items-center gap-2">
                    <span>06. Decision History</span>
                    <span className="bg-white/10 px-1.5 py-0.5 rounded text-white/60">{decisionHistory.length}</span>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-[8px] text-white/30 font-mono">IST</span>
                    <Clock className="w-3 h-3" />
                </div>
            </div>
            <div className="relative pl-3 space-y-1.5 max-h-[300px] overflow-y-auto overflow-x-hidden pr-1 before:absolute before:inset-y-0 before:left-[3px] before:w-px before:bg-white/10 mt-2">
                {reversed.map((entry, revIdx) => {
                    const i = reversed.length - 1 - revIdx;
                    const dirColor = entry.direction === 'LONG' ? 'text-green-400' : entry.direction === 'SHORT' ? 'text-red-400' : 'text-blue-400';
                    const timeStr = new Date(entry.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                        timeZone: 'Asia/Kolkata'
                    });
                    const expanded = expandedRevIdx === revIdx;
                    const barColor = entry.direction === 'LONG' ? 'bg-emerald-500' : entry.direction === 'SHORT' ? 'bg-red-400' : 'bg-slate-500';

                    return (
                        <div key={`${entry.timestamp}-${i}`} className="relative">
                            <div className={`absolute -left-[14px] top-3 w-1.5 h-1.5 rounded-full ${entry.direction === 'LONG' ? 'bg-green-400' : entry.direction === 'SHORT' ? 'bg-red-400' : 'bg-blue-400'} shadow-[0_0_5px_currentColor]`} />

                            <button
                                type="button"
                                onClick={() => toggle(revIdx)}
                                className={`w-full text-left rounded-lg border transition-colors px-2 py-1.5 ${
                                    expanded ? 'bg-white/10 border-white/20' : 'bg-white/[0.03] border-white/10 hover:bg-white/[0.06]'
                                }`}
                                aria-expanded={expanded}
                            >
                                <div className="flex justify-between items-center gap-2 text-[10px]">
                                    <div className="flex items-center gap-2 min-w-0">
                                        <span className={`font-bold shrink-0 ${dirColor}`}>{entry.direction}</span>
                                        {entry.phase && (
                                            <span className="text-[8px] uppercase tracking-wider px-1 py-0.5 rounded border bg-white/5 text-white/50 border-white/10 shrink-0">
                                                {entry.phase}
                                            </span>
                                        )}
                                        {entry.approved ? (
                                            <span className="text-[8px] uppercase tracking-wider px-1 py-0.5 rounded border bg-emerald-500/15 text-emerald-200/90 border-emerald-500/25 shrink-0">
                                                ENTRY
                                            </span>
                                        ) : (
                                            <span className="text-[8px] uppercase tracking-wider px-1 py-0.5 rounded border bg-amber-500/15 text-amber-200/90 border-amber-500/25 shrink-0">
                                                BLOCKED
                                            </span>
                                        )}
                                        <div className="flex-1 min-w-0 h-1 bg-white/10 rounded-full overflow-hidden max-w-[72px] hidden sm:block">
                                            <div className={`h-full ${barColor}`} style={{ width: `${Math.max(0, Math.min(1, entry.confidence)) * 100}%` }} />
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2 shrink-0">
                                        <span className="text-white/40 text-[8px]">Conf: <span className="text-white/70 font-bold">{entry.confidence.toFixed(2)}</span></span>
                                        <span className="text-white/30 font-mono text-[9px]">{timeStr} IST</span>
                                    </div>
                                </div>
                                {!expanded && (
                                    <div className="text-[9px] text-white/45 font-mono truncate mt-1 pr-6">
                                        {entry.rationale || '—'}
                                    </div>
                                )}
                                {expanded && (
                                    <div className="mt-2 pt-2 border-t border-white/10 space-y-1.5">
                                        <div className="text-[9px] text-white/55 leading-relaxed font-mono">
                                            {entry.rationale || 'No rationale available.'}
                                        </div>
                                        {entry.blockReasons && entry.blockReasons.length > 0 && (
                                            <div className="flex flex-wrap gap-1">
                                                {entry.blockReasons.map((r, idx) => (
                                                    <span key={idx} className="text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded border bg-amber-500/10 text-amber-200/80 border-amber-500/20">
                                                        {r}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </button>
                        </div>
                    );
                })}
            </div>
        </div>
    );
});

DecisionHistoryPanel.displayName = 'DecisionHistoryPanel';

export default DecisionHistoryPanel;
