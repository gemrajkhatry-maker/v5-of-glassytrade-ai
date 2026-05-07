import React from 'react';
import { Brain, TrendingUp, TrendingDown, MinusCircle, AlertTriangle, Clock } from 'lucide-react';
import { GenAIAnalysis, AMTAnalysis } from '../../../types';

interface DecisionTabProps {
  analysis: GenAIAnalysis | null;
  amtResult: AMTAnalysis | null;
  agentDecision?: { probability: number; timing?: string } | null;
  symbol?: string;
}

/**
 * DecisionTab - LLM rationale, analysis direction, and decision validation
 * Extracted from AIAnalysisPanel.tsx lines 1650-1813
 */
const DecisionTab: React.FC<DecisionTabProps> = ({
  analysis,
  amtResult,
  agentDecision,
  symbol,
}) => {
  const displayAnalysis = analysis || {
    direction: 'FLAT',
    confidence: 'Low' as const,
    rationale: '',
    rawOutput: '',
  };
  
  // Map confidence enum to probability for display
  const confidenceToProbability = (conf: string) => {
    return conf === 'High' ? 0.75 : conf === 'Medium' ? 0.50 : 0.25;
  };
  const displayProbability = confidenceToProbability(displayAnalysis.confidence);

  const sanitizeRationale = (text: string) => {
    return text
      .replace(/<think>.*?<\/think>/gs, '')
      .replace(/\[INST\].*?\[\/INST\]/gs, '')
      .trim();
  };

  const extractDecisionText = (text: string, fallback: string) => {
    const cleaned = sanitizeRationale(text);
    return cleaned || fallback;
  };

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* AI Analysis Direction & Rationale */}
      <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2 relative overflow-hidden">
        <div className={`absolute top-0 left-0 w-1 h-full ${displayAnalysis.direction === 'LONG' ? 'bg-emerald-500' : displayAnalysis.direction === 'SHORT' ? 'bg-red-500' : 'bg-yellow-500/50'}`} />
        
        <div className="flex justify-between items-center pl-2">
          <span className="text-[10px] text-white/40">Direction</span>
          <span className={`text-xs font-bold ${displayAnalysis.direction === 'LONG' ? 'text-emerald-400' : displayAnalysis.direction === 'SHORT' ? 'text-red-400' : 'text-blue-300'}`}>
            {displayAnalysis.direction}
          </span>
        </div>
        
        <div className="flex justify-between items-center pl-2">
          <span className="text-[10px] text-white/40">Confidence</span>
          <span className={`text-xs font-mono font-bold ${(displayProbability * 100) >= 60 ? 'text-emerald-400' : (displayProbability * 100) > 45 ? 'text-yellow-400' : 'text-red-400'}`}>
            {(displayProbability * 100).toFixed(1)}%
          </span>
        </div>
        
        {/* Confidence bar */}
        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden ml-2">
          <div className="h-full rounded-full transition-all duration-500" style={{
            width: `${Math.min(displayProbability * 100, 100)}%`,
            backgroundColor: (displayProbability * 100) >= 60 ? '#4ade80' : (displayProbability * 100) > 45 ? '#facc15' : '#f87171',
          }} />
        </div>
        
        {/* LLM Rationale */}
        <div className="pl-2 pt-2 border-t border-white/5">
          <div className="text-[9px] text-white/30 font-mono leading-relaxed">
            {sanitizeRationale(displayAnalysis.rationale || displayAnalysis.rawOutput || 'No detailed output.')}
          </div>
        </div>
      </div>

      {/* Decision Validation Rules */}
      {(() => {
        const ltp = amtResult?.sessionVwap || 0;
        const poc = amtResult?.poc || 0;
        const vah = amtResult?.valueAreaHigh || 0;
        const val = amtResult?.valueAreaLow || 0;
        const distThreshold = ltp > 0 ? ltp * 0.002 : 0;

        return (
          <details className="group border-t border-white/5 pt-2 cursor-pointer">
            <summary className="list-none flex justify-between items-center text-[9px] text-white/40 uppercase tracking-widest font-bold">
              <span>Decision Validation Rules</span>
              <span className="group-open:hidden">Expand</span>
              <span className="hidden group-open:block">Collapse</span>
            </summary>
            <div className="mt-2 space-y-2">
              {/* Location-based validation */}
              <div className="flex items-center gap-2 text-[10px]">
                <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${ltp > 0 && poc > 0 ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-white/10 border-white/20 text-white/60'}`}>
                  {ltp > 0 && poc > 0 ? '✓' : '✗'}
                </div>
                <span className="text-white/60 w-24">Price Context</span>
                <span className="text-white/40 font-mono text-[9px]">
                  {(() => {
                    const ltp = amtResult?.sessionVwap || 0;
                    const poc = amtResult?.poc;
                    const vah = amtResult?.valueAreaHigh;
                    const val = amtResult?.valueAreaLow;
                    const distThreshold = ltp > 0 ? ltp * 0.002 : 0;
                    
                    if (ltp && poc && Math.abs(ltp - poc) < distThreshold) {
                      return `At POC (${poc.toFixed(1)}) — Fair value`;
                    }
                    if (ltp && vah && ltp > vah) {
                      return `Above VAH (${vah.toFixed(1)}) — Bullish`;
                    }
                    if (ltp && val && ltp < val) {
                      return `Below VAL (${val.toFixed(1)}) — Bearish`;
                    }
                    return 'Mid-range — No edge';
                  })()}
                </span>
              </div>
              
              {/* Volume alive check */}
              <div className="flex items-center gap-2 text-[10px]">
                <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${amtResult?.marketState !== 'DEAD' ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-red-500/20 border-red-500/50 text-red-400'}`}>
                  {amtResult?.marketState !== 'DEAD' ? '✓' : '✗'}
                </div>
                <span className="text-white/60 w-24">Volume Alive</span>
                <span className="text-white/40 font-mono text-[9px]">{amtResult?.marketState !== 'DEAD' ? 'ACTIVE' : 'DEAD'}</span>
              </div>
              
              {/* Timing check */}
              <div className="flex items-center gap-2 text-[10px]">
                <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${agentDecision?.timing === 'ENTER_NOW' ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-white/10 border-white/20 text-white/60'}`}>
                  {agentDecision?.timing === 'ENTER_NOW' ? '✓' : '⏸'}
                </div>
                <span className="text-white/60 w-24">Timing</span>
                {(() => {
                  const timing = agentDecision?.timing || 'SKIP';
                  const timeWindow = amtResult?.amtTimeWindow;
                  
                  if (!timeWindow) return <span className="text-white/40 font-mono text-[9px]">{timing}</span>;
                  
                  const timingColor = timing === 'ENTER_NOW' ? 'text-emerald-400' : 
                                      timing === 'WAIT' ? 'text-yellow-400' : 'text-white/40';
                  
                  return (
                    <div className="flex flex-col gap-0.5">
                      <span className={`font-mono text-[9px] font-bold ${timingColor}`}>{timing}</span>
                      <span className="text-[8px] text-white/30">{timeWindow.label}</span>
                    </div>
                  );
                })()}
              </div>
              
              {/* Prior day levels */}
              {amtResult && (amtResult.priorVah || amtResult.priorVal || amtResult.priorPoc) && (
                <div className="mt-1 pl-5 flex flex-wrap gap-2 opacity-50">
                  {amtResult.priorVah && <span className="text-[8px] font-mono">P-VAH: {amtResult.priorVah.toFixed(1)}</span>}
                  {amtResult.priorVal && <span className="text-[8px] font-mono">P-VAL: {amtResult.priorVal.toFixed(1)}</span>}
                  {amtResult.priorPoc && <span className="text-[8px] font-mono">P-POC: {amtResult.priorPoc.toFixed(1)}</span>}
                </div>
              )}
            </div>
          </details>
        );
      })()}

      {/* LLM Timeout Warning */}
      {!analysis && amtResult && (
        <div className="px-3 py-1.5 bg-glassy-warning/10 border border-glassy-warning/20 rounded-sm flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-glassy-warning" />
          <span className="text-[9px] font-bold text-glassy-warning uppercase tracking-wider">
            LLM Timeout — Running on Quant Logic Only
          </span>
        </div>
      )}
    </div>
  );
};

export default DecisionTab;
