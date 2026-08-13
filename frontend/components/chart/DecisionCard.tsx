import React, { useState } from 'react';
import { Cpu, ChevronDown, ChevronUp } from 'lucide-react';
import { sanitizeRationale } from '../../utils/textSanitizer';

interface DecisionCardProps {
  direction: string;
  regime: string;
  rationale: string;
}

/**
 * DecisionCard displays the current deterministic trading decision with
 * expandable rationale. Extracted from ChartScene for better maintainability.
 * Props mirror the backend's real `agentDecision` contract.
 */
const DecisionCard: React.FC<DecisionCardProps> = ({ 
  direction, 
  regime, 
  rationale 
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  
  const isLong = direction === 'LONG';
  const isShort = direction === 'SHORT';
  const isFlat = direction === 'FLAT';
  
  const directionColor = isLong ? 'text-emerald-400' : isShort ? 'text-red-400' : 'text-slate-400';
  const directionBg = isLong ? 'bg-emerald-500/20 border-emerald-500/30' : isShort ? 'bg-red-500/20 border-red-500/30' : 'bg-slate-500/20 border-slate-500/30';
  const directionIcon = isLong ? '▲' : isShort ? '▼' : '—';

  return (
    <div className="flex flex-col bg-slate-900/80 backdrop-blur-md border border-white/10 rounded-xl shadow-2xl overflow-hidden font-sans">
      {/* Header */}
      <div className={`px-3 py-2 border-b border-white/5 flex items-center justify-between ${directionBg}`}>
        <div className="flex items-center gap-2">
          <Cpu className={`w-4 h-4 ${directionColor}`} />
          <span className="text-[10px] font-bold text-white/80 uppercase tracking-widest">Current Decision</span>
        </div>
        <button 
          onClick={() => setIsExpanded(!isExpanded)}
          className="p-1 hover:bg-white/10 rounded-md transition-colors"
        >
          {isExpanded ? <ChevronDown className="w-3 h-3 text-white/50" /> : <ChevronUp className="w-3 h-3 text-white/50" />}
        </button>
      </div>

      {/* Body */}
      <div className={`transition-all duration-300 ease-in-out ${isExpanded ? 'max-h-96' : 'max-h-0'} overflow-y-auto custom-scrollbar`}>
        <div className="p-3 text-[11px] leading-relaxed text-slate-300 whitespace-pre-wrap font-mono italic opacity-90 border-b border-white/5 bg-black/20">
          {sanitizeRationale(rationale)}
        </div>
      </div>

      {/* Decision Footer */}
      <div className="p-3 flex items-center bg-black/40">
        <div className="flex flex-col">
          <span className="text-[9px] text-white/30 uppercase font-bold tracking-tighter italic">Decision</span>
          <span className={`text-xs font-black uppercase tracking-wider ${directionColor}`}>
            {directionIcon} {direction}{regime && direction !== 'FLAT' ? ` (${regime === 'TRENDING' ? 'Trend' : regime === 'BALANCED' ? 'Reversion' : regime})` : ''}
          </span>
        </div>
      </div>
    </div>
  );
};

export default DecisionCard;
