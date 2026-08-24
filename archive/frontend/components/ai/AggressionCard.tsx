import React from 'react';
import { Activity } from 'lucide-react';

interface AggressionCardProps {
    deltaScore: number;
    aggScore: number;
}

/** 03. VOLUME AGGRESSION — normalized delta score + visual bar. */
const AggressionCard = React.memo<AggressionCardProps>(({ deltaScore, aggScore }) => {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-glassy-text-tertiary uppercase tracking-widest">
                <span>03. Volume Aggression</span>
                <Activity className="w-3 h-3 hover:text-glassy-text-secondary transition-colors" />
            </div>
            <div className="p-3 rounded-md bg-glassy-bg-elevated/50 border border-glassy-border-subtle">
                <div className="flex justify-between items-end mb-2">
                    <div className="flex flex-col">
                        <span className="text-[10px] text-glassy-text-secondary mb-0.5">Delta Score <span className="text-[8px] text-glassy-text-disabled">(norm)</span></span>
                        <span className={`text-[9px] font-bold tracking-wider ${Math.abs(deltaScore) > 0.05 && aggScore > 0.1 ? (deltaScore > 0 ? 'text-glassy-bull-primary' : 'text-glassy-bear-primary') : 'text-glassy-text-disabled'}`}>
                            {Math.abs(deltaScore) > 0.05 && aggScore > 0.1 ? (deltaScore > 0 ? '[BULLS IN CONTROL]' : '[BEARS IN CONTROL]') : '[DELTA NEUTRAL / NEGLIGIBLE]'}
                        </span>
                    </div>
                    <div className="flex flex-col items-end gap-0.5">
                        <span className={`text-xs font-mono font-bold tabular-nums ${deltaScore > 0 ? 'text-glassy-bull-primary' : deltaScore < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                            {deltaScore > 0 ? '+' : ''}{deltaScore.toFixed(2)}
                        </span>
                    </div>
                </div>
                {/* Progress Bar */}
                <div className="h-1 bg-glassy-text-disabled/20 rounded-full overflow-hidden flex relative">
                    <div className="absolute top-0 left-1/2 w-px h-full bg-glassy-text-disabled/30 z-10" />
                    {/* Visual bar moving left or right based on score */}
                    <div className={`h-full absolute transition-all duration-500 rounded-full`} style={{
                        width: `${Math.min(Math.abs(deltaScore) * 50, 50)}%`,
                        left: deltaScore > 0 ? '50%' : `${50 - Math.min(Math.abs(deltaScore) * 50, 50)}%`,
                        backgroundColor: deltaScore > 0 ? '#00c896' : '#ff4757'
                    }}></div>
                </div>
                {/* Aggression indicator */}
                <div className="flex justify-between text-[9px] mt-1.5 pt-1 border-t border-glassy-border-subtle">
                    <span className="text-glassy-text-tertiary">Aggression</span>
                    <span className={`font-mono font-bold tabular-nums ${aggScore > 0 ? 'text-glassy-bull-primary' : aggScore < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                        {aggScore.toFixed(2)}{deltaScore < -0.05 ? ' (Bearish)' : deltaScore > 0.05 ? ' (Bullish)' : ''}
                    </span>
                </div>
            </div>
        </div>
    );
});

AggressionCard.displayName = 'AggressionCard';

export default AggressionCard;
