import React from 'react';
import { GenAIAnalysis } from '../../types';
import { sanitizeLlmText, extractDecisionText } from '../../utils/textSanitizer';

interface ModelIoFooterProps {
    analysis: GenAIAnalysis;
}

/** MODEL I/O footer — direction dot, decision text, raw rationale dump. */
const ModelIoFooter = React.memo<ModelIoFooterProps>(({ analysis }) => {
    return (
        <details className="mt-2 group border-t border-white/5 pt-2 cursor-pointer">
            <summary className="list-none flex items-start gap-2">
                <div className={`mt-1 h-2 w-2 rounded-full ${analysis.direction === 'LONG' ? 'bg-green-500 animate-ping' : analysis.direction === 'SHORT' ? 'bg-red-500 animate-ping' : 'bg-slate-600'}`}></div>
                <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-center mb-1">
                        <div className="font-bold text-white/80 uppercase tracking-wider text-xs">
                            {analysis.direction === 'FLAT' ? "MODEL I/O: MONITORING MARKET" : `MODEL I/O: ENTRY SIGNAL ${analysis.direction}`}
                        </div>
                        <div className="text-[9px] text-white/40 bg-white/5 px-1.5 py-0.5 rounded">Expand</div>
                    </div>
                    <p className={`p-2 rounded font-mono text-[10px] truncate ${analysis.direction === 'LONG' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : analysis.direction === 'SHORT' ? 'bg-red-500/10 text-red-400 border border-red-500/20' : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'}`}>
                        {extractDecisionText(analysis.rationale || analysis.rawOutput, 'QUANT_MONITORING_NO_EDGE')}
                    </p>
                </div>
            </summary>
                <div className="mt-2 pl-4 border-l border-white/10 ml-1 pb-1">
                <div className="text-[9px] text-white/50 font-mono whitespace-pre-wrap">
                    {sanitizeLlmText(analysis.rationale || analysis.rawOutput) || "No detailed output."}
                </div>
            </div>
        </details>
    );
});

ModelIoFooter.displayName = 'ModelIoFooter';

export default ModelIoFooter;
