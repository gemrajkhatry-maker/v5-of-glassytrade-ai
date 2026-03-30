import React from 'react';
import { GenAIAnalysis } from '../../types';
import { sanitizeLlmText } from '../../utils/textSanitizer';

interface ModelIOPanelProps {
    displayAnalysis: GenAIAnalysis;
}

/** Shows the raw LLM prompt input and model output for debugging. */
const ModelIOPanel = React.memo<ModelIOPanelProps>(({ displayAnalysis }) => (
    <div className="flex flex-col gap-2 pt-2 border-t border-white/5">
        <div className="text-[10px] text-white/40 uppercase tracking-widest">05. Model I/O</div>
        <div className="p-2 rounded-lg bg-black/30 border border-white/5 space-y-2 max-h-[200px] overflow-y-auto">
            <div>
                <div className="text-[9px] text-cyan-400/60 uppercase font-bold mb-1">Prompt &rarr; Model</div>
                <div className="text-[9px] font-mono text-white/50 leading-relaxed whitespace-pre-wrap break-words">
                    {displayAnalysis.inputPrompt || "Waiting for first LLM call..."}
                </div>
            </div>
            <div className="border-t border-white/5 pt-2">
                <div className="text-[9px] text-amber-400/60 uppercase font-bold mb-1">Model &rarr; Output</div>
                <div className="text-[9px] font-mono text-white/50 leading-relaxed whitespace-pre-wrap break-words">
                    {(() => {
                        let text = sanitizeLlmText(displayAnalysis.rawOutput) || "No output yet.";
                        return text;
                    })()}
                </div>
            </div>
        </div>
    </div>
));

ModelIOPanel.displayName = 'ModelIOPanel';

export default ModelIOPanel;
