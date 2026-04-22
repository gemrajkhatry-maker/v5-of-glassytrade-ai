import React, { useState, useCallback } from 'react';
import { LLMHistoryEntry } from '../../types';
import { Clock } from 'lucide-react';
import { sanitizeRationale, extractDecisionText } from '../../utils/textSanitizer';

interface DecisionHistoryPanelProps {
    llmHistory: LLMHistoryEntry[];
}

function decisionSourceLabel(entry: LLMHistoryEntry): { label: string; className: string } {
    const raw = entry.rawOutput?.trim() || '';
    const prompt = entry.inputPrompt?.trim() || '';
    if (raw.startsWith('QUANT_') || prompt.startsWith('[SESSION GATE:') || prompt.startsWith('[QUANT GATE:')) {
        return { label: raw || 'GATE', className: 'bg-amber-500/15 text-amber-200/90 border-amber-500/25' };
    }
    if (raw && !raw.startsWith('QUANT_')) {
        return { label: 'LLM', className: 'bg-violet-500/15 text-violet-200/90 border-violet-500/25' };
    }
    return { label: '—', className: 'bg-white/5 text-white/40 border-white/10' };
}

function confWeight(conf: string | undefined): number {
    const c = (conf || '').toLowerCase();
    if (c === 'high') return 1;
    if (c === 'medium') return 0.55;
    if (c === 'low') return 0.25;
    return 0.35;
}

/** Compact timeline of past decisions; expand row for full rationale. */
const DecisionHistoryPanel = React.memo<DecisionHistoryPanelProps>(({ llmHistory }) => {
    const [expandedRevIdx, setExpandedRevIdx] = useState<number | null>(null);
    const toggle = useCallback((revIdx: number) => {
        setExpandedRevIdx((cur) => (cur === revIdx ? null : revIdx));
    }, []);

    if (llmHistory.length === 0) return null;

    const reversed = [...llmHistory].reverse();

    return (
        <div className="flex flex-col gap-2 pt-2 border-t border-white/5 relative">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest mt-2">
                <div className="flex items-center gap-2">
                    <span>06. Decision History</span>
                    <span className="bg-white/10 px-1.5 py-0.5 rounded text-white/60">{llmHistory.length}</span>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-[8px] text-white/30 font-mono">IST</span>
                    <span className="text-blue-300/80 hover:text-blue-300 cursor-pointer flex items-center gap-1 transition-colors">
                        Export CSV
                    </span>
                    <Clock className="w-3 h-3" />
                </div>
            </div>
            <div className="relative pl-3 space-y-1.5 max-h-[300px] overflow-y-auto overflow-x-hidden pr-1 before:absolute before:inset-y-0 before:left-[3px] before:w-px before:bg-white/10 mt-2">
                {reversed.map((entry, revIdx) => {
                    const i = reversed.length - 1 - revIdx;
                    const isError = entry.rationale?.includes('404') || entry.rationale?.includes('Error') || entry.confidence === 'Error';
                    const dirColor = isError ? 'text-red-500' : entry.direction === 'LONG' ? 'text-green-400' : entry.direction === 'SHORT' ? 'text-red-400' : 'text-blue-400';
                    // Convert UTC timestamp to IST (UTC+5:30)
                    const timeStr = new Date(entry.timestamp).toLocaleTimeString([], { 
                        hour: '2-digit', 
                        minute: '2-digit', 
                        second: '2-digit',
                        timeZone: 'Asia/Kolkata'  // IST timezone
                    });
                    const src = decisionSourceLabel(entry);
                    const expanded = expandedRevIdx === revIdx;
                    const w = confWeight(entry.confidence);
                    const barColor = isError ? 'bg-red-500' : entry.direction === 'LONG' ? 'bg-emerald-500' : entry.direction === 'SHORT' ? 'bg-red-400' : 'bg-slate-500';

                    return (
                        <div key={`${entry.timestamp}-${i}`} className="relative">
                            <div className={`absolute -left-[14px] top-3 w-1.5 h-1.5 rounded-full ${isError ? 'bg-red-500' : entry.direction === 'LONG' ? 'bg-green-400' : entry.direction === 'SHORT' ? 'bg-red-400' : 'bg-blue-400'} shadow-[0_0_5px_currentColor]`} />

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
                                        {isError ? (
                                            <span className="badge badge-error bg-red-500/20 text-red-400 px-1 rounded border border-red-500/30 font-bold text-[9px] shrink-0">API ERROR</span>
                                        ) : (
                                            <>
                                                <span className={`font-bold shrink-0 ${dirColor}`}>{entry.direction}</span>
                                                <span
                                                    className={`text-[8px] uppercase tracking-wider px-1 py-0.5 rounded border shrink-0 ${src.className}`}
                                                    title={entry.rawOutput ? `raw: ${entry.rawOutput}` : 'Source'}
                                                >
                                                    {src.label}
                                                </span>
                                            </>
                                        )}
                                        {!isError && (
                                            <div className="flex-1 min-w-0 h-1 bg-white/10 rounded-full overflow-hidden max-w-[72px] hidden sm:block">
                                                <div className={`h-full ${barColor}`} style={{ width: `${w * 100}%` }} />
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-2 shrink-0">
                                        {!isError && entry.confidence !== 'Overseer' && (
                                            <span className="text-white/40 text-[8px]">Conf: <span className="text-white/70 font-bold">{entry.confidence}</span></span>
                                        )}
                                        {entry.confidence === 'Overseer' && (
                                            <span className="px-1.5 py-0.5 text-[8px] uppercase tracking-wider bg-blue-500/20 text-blue-300 rounded border border-blue-500/30">Overseer</span>
                                        )}
                                        <span className="text-white/30 font-mono text-[9px]">{timeStr} IST</span>
                                    </div>
                                </div>
                                {!expanded && !isError && (
                                    <div className="text-[9px] text-white/45 font-mono truncate mt-1 pr-6">
                                        {extractDecisionText(entry.rationale || entry.rawOutput, '').slice(0, 120) || '—'}
                                    </div>
                                )}
                                {expanded && (
                                    <div className="mt-2 pt-2 border-t border-white/10 space-y-1.5">
                                        {entry.rawOutput && src.label !== 'LLM' ? (
                                            <div className="text-[8px] text-amber-200/70 font-mono break-all">{entry.rawOutput}</div>
                                        ) : null}
                                        <div className={`text-[9px] ${isError ? 'text-red-300' : 'text-white/55'} leading-relaxed font-mono`}>
                                            {sanitizeRationale(entry.rationale) || 'No rationale available.'}
                                        </div>
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
