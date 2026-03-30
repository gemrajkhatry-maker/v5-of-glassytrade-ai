import React from 'react';
import { AgentDecision } from '../../types';
import { Target, ArrowRight, Zap, X } from 'lucide-react';

interface LiveOpportunityCardProps {
    symbol: string | null;
    agentDecision: AgentDecision | null;
    ltp: number;
    onSelect: (symbol: string) => void;
    onClose: () => void;
}

export const LiveOpportunityCard: React.FC<LiveOpportunityCardProps> = ({ symbol, agentDecision, ltp, onSelect, onClose }) => {
    if (!symbol || !agentDecision || agentDecision.timing !== 'ENTER_NOW') {
        return (
            <div className="w-80 bg-[#0f172a]/90 backdrop-blur-xl border border-white/5 rounded-xl p-4 shadow-2xl relative">
                <button onClick={onClose} className="absolute top-2 right-2 p-1 text-white/40 hover:text-white rounded-lg hover:bg-white/10 transition-colors">
                    <X size={14} />
                </button>
                <div className="flex items-center gap-2 text-white/50 mb-3">
                    <Zap className="w-4 h-4" />
                    <span className="text-xs font-bold tracking-widest uppercase">Live Opportunity</span>
                </div>
                <div className="h-24 flex flex-col items-center justify-center text-center">
                    <span className="text-2xl mb-2">🔭</span>
                    <span className="text-xs text-white/40 uppercase tracking-widest">Scanning Markets</span>
                    <span className="text-[10px] text-white/20 mt-1">No actionable 'ENTER_NOW' signals</span>
                </div>
            </div>
        );
    }

    const isLong = agentDecision.direction === 'LONG';
    const prob = (agentDecision.probability * 100).toFixed(1);

    // Estimate SL/TP for display based on typical Kelly logic defaults if not provided natively
    // We'll calculate a visual SL/TP based on LTP. For Long: TP = LTP + 2%, SL = LTP - 1%. (Conceptual only).
    const estTP = isLong ? ltp * 1.002 : ltp * 0.998;
    const estSL = isLong ? ltp * 0.999 : ltp * 1.001;

    return (
        <div className="w-80 bg-[#0f172a]/90 backdrop-blur-xl border border-purple-500/30 rounded-xl p-4 shadow-2xl relative overflow-hidden group">
            <div className="absolute top-0 left-0 w-1 bg-gradient-to-b from-purple-500 to-transparent h-full"></div>
            
            <button onClick={onClose} className="absolute top-2 right-2 p-1 text-white/40 hover:text-white rounded-lg hover:bg-white/10 transition-colors z-10">
                <X size={14} />
            </button>

            <div className="flex items-center justify-between mb-3 pr-6">
                <div className="flex items-center gap-2">
                    <Zap className="w-4 h-4 text-purple-400 animate-pulse" />
                    <span className="text-xs font-bold text-white tracking-widest uppercase">Target Locked</span>
                </div>
            </div>

            <div className="bg-white/5 rounded-lg p-3 border border-white/5 mb-3">
                <div className="flex justify-between items-end mb-2">
                    <span className="text-lg font-bold text-white">{symbol}</span>
                    <span className="text-xs font-mono text-white/60">LTP: {ltp.toFixed(2)}</span>
                </div>
                <div className="flex items-center justify-between">
                    <div className={`px-2 py-1 rounded text-xs font-bold ${isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                        {agentDecision.direction} ↑
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] text-white/40">Prob</span>
                        <span className={`text-sm font-bold font-mono ${agentDecision.probability >= 0.6 ? 'text-emerald-400' : 'text-yellow-400'}`}>
                            {prob}%
                        </span>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-2 mb-3">
                <div className="bg-white/5 rounded p-2 text-center border border-white/5">
                    <span className="block text-[9px] text-white/40 uppercase mb-0.5">Est. SL</span>
                    <span className="text-xs font-mono font-bold text-red-300">{estSL.toFixed(2)}</span>
                </div>
                <div className="bg-white/5 rounded p-2 text-center border border-white/5">
                    <span className="block text-[9px] text-white/40 uppercase mb-0.5">Est. TP</span>
                    <span className="text-xs font-mono font-bold text-emerald-300">{estTP.toFixed(2)}</span>
                </div>
            </div>

            <button 
                onClick={() => onSelect(symbol)}
                className="w-full py-2 bg-purple-600 hover:bg-purple-500 rounded-lg text-xs font-bold text-white transition-all flex items-center justify-center gap-2 shadow-lg shadow-purple-500/20"
            >
                View Chart <ArrowRight size={14} />
            </button>
        </div>
    );
};
