import React from 'react';
import { AMTAnalysis } from '../../types';

interface AbsorptionCardProps {
    amtResult: AMTAnalysis | null;
}

/** 03d. ABSORPTION & LARGE PRINTS — absorption detection, institutional prints, swing delta. */
const AbsorptionCard = React.memo<AbsorptionCardProps>(({ amtResult }) => {
    const absorptionSide = amtResult?.absorptionSide;
    const absorptionRangeRatio = amtResult?.absorptionRangeRatio ?? 0;
    const absorptionVolRatio = amtResult?.absorptionVolRatio ?? 0;
    const aggressivePrints = amtResult?.aggressivePrints ?? [];
    const swingDelta = amtResult?.swingDelta ?? 0;

    // Check if we have any absorption or large prints to show
    const hasAbsorption = absorptionSide && absorptionRangeRatio > 0;
    const hasLargePrints = aggressivePrints.length > 0;

    if (!hasAbsorption && !hasLargePrints && Math.abs(swingDelta) < 100) return null;

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>03d. Absorption & Large Prints</span>
            </div>
            <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                {/* Absorption Detection */}
                {hasAbsorption && (
                    <div className={`px-2 py-1.5 rounded border ${
                        absorptionSide === 'BUY'
                            ? 'bg-green-500/10 border-green-500/30'
                            : 'bg-red-500/10 border-red-500/30'
                    }`}>
                        <div className="flex items-center justify-between">
                            <span className={`text-[9px] font-bold ${
                                absorptionSide === 'BUY' ? 'text-green-400' : 'text-red-400'
                            }`}>
                                {absorptionSide === 'BUY' ? '🟢 BUY' : '🔴 SELL'} ABSORPTION
                            </span>
                            <span className="text-[8px] font-mono text-white/50">
                                Range: {absorptionRangeRatio.toFixed(2)}x | Vol: {absorptionVolRatio.toFixed(1)}x
                            </span>
                        </div>
                        <div className="text-[8px] text-white/40 mt-1">
                            Price stalled despite {absorptionSide === 'BUY' ? 'selling pressure' : 'buying pressure'} — limit orders absorbing market
                        </div>
                    </div>
                )}

                {/* Large Institutional Prints */}
                {hasLargePrints && (
                    <div className="space-y-1">
                        <div className="text-[9px] text-white/40 font-bold">LARGE PRINTS ({aggressivePrints.length})</div>
                        <div className="flex flex-wrap gap-1">
                            {aggressivePrints.slice(-5).map((print, idx) => (
                                <span
                                    key={idx}
                                    className={`px-1.5 py-0.5 rounded text-[8px] font-mono font-bold ${
                                        print.side === 'BUY'
                                            ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                                            : 'bg-red-500/20 text-red-400 border border-red-500/30'
                                    }`}
                                >
                                    {print.side === 'BUY' ? 'B' : 'S'} {print.volume > 1000 ? `${(print.volume / 1000).toFixed(1)}K` : print.volume}
                                </span>
                            ))}
                        </div>
                    </div>
                )}

                {/* Swing Delta (Initiative vs Responsive) */}
                {Math.abs(swingDelta) >= 100 && (
                    <div className="flex justify-between items-center px-1 py-0.5 bg-white/5 rounded border border-white/10">
                        <span className="text-[8px] text-white/40">Swing Delta</span>
                        <span className={`text-[8px] font-mono font-bold ${
                            swingDelta > 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                            {swingDelta > 0 ? '+' : ''}{swingDelta > 1000 ? `${(swingDelta / 1000).toFixed(1)}K` : swingDelta.toFixed(0)}
                            {swingDelta > 500 ? ' (INITIATIVE)' : swingDelta < -500 ? ' (RESPONSIVE)' : ''}
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
});

AbsorptionCard.displayName = 'AbsorptionCard';

export default AbsorptionCard;
