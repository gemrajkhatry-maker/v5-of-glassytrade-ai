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
            <div className="w-80 bg-glassy-bg-tertiary/90 backdrop-blur-xl border border-glassy-border-default rounded-md p-4 shadow-xl relative">
                <button onClick={onClose} className="absolute top-2 right-2 p-1 text-glassy-text-tertiary hover:text-glassy-text-primary rounded-sm hover:bg-glassy-bg-hover transition-colors">
                    <X size={14} />
                </button>
                <div className="flex items-center gap-2 text-glassy-text-secondary mb-3">
                    <Zap className="w-4 h-4" />
                    <span className="text-xs font-bold tracking-wider uppercase">Live Opportunity</span>
                </div>
                <div className="h-24 flex flex-col items-center justify-center text-center">
                    <span className="text-2xl mb-2">🔭</span>
                    <span className="text-xs text-glassy-text-tertiary uppercase tracking-wider">Scanning Markets</span>
                    <span className="text-[9px] text-glassy-text-disabled mt-1">No actionable 'ENTER_NOW' signals</span>
                </div>
            </div>
        );
    }

    const isLong = agentDecision.direction === 'LONG';
    const prob = (agentDecision.probability * 100).toFixed(1);

    // Estimate SL/TP from AMT analysis (not in AgentDecision type)
    const hasStructuralStop = false; // Would need amtAnalysis data
    const structuralStop = undefined;
    const estTP = isLong ? ltp * 1.002 : ltp * 0.998;

    return (
        <div className="w-80 bg-glassy-bg-tertiary/90 backdrop-blur-xl border border-glassy-ai-primary/30 rounded-md p-4 shadow-xl relative overflow-hidden">
            {/* Left accent bar */}
            <div className="absolute top-0 left-0 w-0.5 bg-gradient-to-b from-glassy-ai-primary to-transparent h-full"></div>
            
            <button onClick={onClose} className="absolute top-2 right-2 p-1 text-glassy-text-tertiary hover:text-glassy-text-primary rounded-sm hover:bg-glassy-bg-hover transition-colors z-10">
                <X size={14} />
            </button>

            <div className="flex items-center justify-between mb-3 pr-6">
                <div className="flex items-center gap-2">
                    <Zap className="w-4 h-4 text-glassy-ai-primary animate-pulse" />
                    <span className="text-xs font-bold text-glassy-text-primary tracking-wider uppercase">Target Locked</span>
                </div>
            </div>

            <div className="bg-glassy-bg-elevated/50 rounded-sm p-3 border border-glassy-border-subtle mb-3">
                <div className="flex justify-between items-end mb-2">
                    <span className="text-lg font-bold text-glassy-text-primary">{symbol}</span>
                    <span className="text-xs font-mono text-glassy-text-secondary">LTP: {ltp.toFixed(2)}</span>
                </div>
                <div className="flex items-center justify-between">
                    <div className={`px-2 py-1 rounded-sm text-xs font-bold ${isLong ? 'bg-glassy-bull-primary/20 text-glassy-bull-primary' : 'bg-glassy-bear-primary/20 text-glassy-bear-primary'}`}>
                        {agentDecision.direction} ↑
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-[9px] text-glassy-text-tertiary">Prob</span>
                        <span className={`text-sm font-bold font-mono ${agentDecision.probability >= 0.6 ? 'text-glassy-bull-primary' : 'text-glassy-warning'}`}>
                            {prob}%
                        </span>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-2 mb-3">
                <div className="bg-glassy-bg-elevated/50 rounded-sm p-2 text-center border border-glassy-border-subtle">
                    <span className="block text-[8px] text-glassy-text-tertiary uppercase mb-0.5">Structural Stop</span>
                    <span className="text-xs font-mono font-bold text-glassy-bear-primary/80">
                        {hasStructuralStop ? structuralStop.toFixed(2) : '-'}
                    </span>
                </div>
                <div className="bg-glassy-bg-elevated/50 rounded-sm p-2 text-center border border-glassy-border-subtle">
                    <span className="block text-[8px] text-glassy-text-tertiary uppercase mb-0.5">Est. TP</span>
                    <span className="text-xs font-mono font-bold text-glassy-bull-primary/80">{estTP.toFixed(2)}</span>
                </div>
            </div>

            <button 
                onClick={() => onSelect(symbol)}
                className="w-full py-2 bg-glassy-ai-primary hover:bg-glassy-ai-secondary rounded-sm text-xs font-bold text-glassy-bg-primary transition-all flex items-center justify-center gap-2"
            >
                View Chart <ArrowRight size={14} />
            </button>
        </div>
    );
};
