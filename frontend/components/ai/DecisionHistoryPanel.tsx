import React from 'react';
import { LLMHistoryEntry } from '../../types';
import { Clock } from 'lucide-react';

interface DecisionHistoryPanelProps {
    llmHistory: LLMHistoryEntry[];
}

/** Expandable list of past LLM entry/exit decisions with prompt and output details. */
const DecisionHistoryPanel = React.memo<DecisionHistoryPanelProps>(({ llmHistory }) => {
    if (llmHistory.length === 0) return null;

    return (
        <div className="flex flex-col gap-2 pt-2 border-t border-white/5">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>06. Decision History ({llmHistory.length})</span>
                <Clock className="w-3 h-3" />
            </div>
            <div className="space-y-1 max-h-[250px] overflow-y-auto">
                {[...llmHistory].reverse().map((entry, i) => {
                    const dirColor = entry.direction === 'LONG' ? 'text-green-400' : entry.direction === 'SHORT' ? 'text-red-400' : 'text-blue-300';
                    const dirBg = entry.direction === 'LONG' ? 'border-green-500/20' : entry.direction === 'SHORT' ? 'border-red-500/20' : 'border-white/5';
                    const timeStr = new Date(entry.timestamp).toLocaleTimeString();
                    return (
                        <details key={i} className={`p-2 rounded-lg bg-black/20 border ${dirBg} cursor-pointer`}>
                            <summary className="flex justify-between items-center text-[10px]">
                                <div className="flex items-center gap-2">
                                    <span className={`font-bold ${dirColor}`}>{entry.direction}</span>
                                    {entry.confidence === 'Overseer' ? (
                                        <span className="px-1.5 py-0.5 text-[8px] uppercase tracking-wider bg-blue-500/20 text-blue-300 rounded border border-blue-500/30">Overseer</span>
                                    ) : (
                                        <span className="text-white/40 text-[9px]">Conf: <span className="text-white/70">{entry.confidence}</span></span>
                                    )}
                                </div>
                                <span className="text-white/30 font-mono">{timeStr}</span>
                            </summary>
                            <div className="mt-2 space-y-2">
                                <div className="text-[9px] text-white/50 leading-relaxed">
                                    {(() => {
                                        let text = (entry.rationale || '');
                                        // Simple cleanup for structured text
                                        text = text.replace(/Market State:.*?\n/i, '')
                                            .replace(/Logic:\s*/i, '')
                                            .replace(/^[{\s"']+|[}\s"']+$/g, '')
                                            .trim();
                                        return text;
                                    })()}
                                </div>
                                {entry.inputPrompt && (
                                    <div>
                                        <div className="text-[9px] text-cyan-400/60 uppercase font-bold mb-1">Prompt</div>
                                        <div className="text-[9px] font-mono text-white/40 whitespace-pre-wrap break-words max-h-[100px] overflow-y-auto">{entry.inputPrompt}</div>
                                    </div>
                                )}
                                {entry.rawOutput && (
                                    <div>
                                        <div className="text-[9px] text-amber-400/60 uppercase font-bold mb-1">Output</div>
                                        <div className="text-[9px] font-mono text-white/40 whitespace-pre-wrap break-words max-h-[100px] overflow-y-auto">{entry.rawOutput}</div>
                                    </div>
                                )}
                            </div>
                        </details>
                    );
                })}
            </div>
        </div>
    );
});

DecisionHistoryPanel.displayName = 'DecisionHistoryPanel';

export default DecisionHistoryPanel;
