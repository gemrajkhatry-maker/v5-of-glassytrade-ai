import React from 'react';
import { AMTAnalysis } from '../../types';

interface VwapContextCardProps {
    amtResult: AMTAnalysis | null;
    currentLtp: number;
}

/** 03f. VWAP + PRIOR DAY — session VWAP bands, sigma meter, gap / bias / velocity. */
const VwapContextCard = React.memo<VwapContextCardProps>(({ amtResult, currentLtp }) => {
    if ((amtResult?.sessionVwap ?? 0) <= 0) return null;

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>03e. VWAP + Context</span>
            </div>
            <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-1.5 text-[9px]">
                {(() => {
                    const isVwapFlat = amtResult.vwapDeviationSigmas === null || amtResult.vwapDeviationSigmas === undefined;
                    return (
                        <>
                            <div className="flex justify-between">
                                <span className="text-white/40">Session VWAP</span>
                                <span className="font-mono text-cyan-400">{amtResult?.sessionVwap?.toFixed(2)}</span>
                            </div>
                            {isVwapFlat ? (
                                <div className="text-center py-2 text-[9px] font-bold text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded">
                                    FLAT MARKET — Insufficient Price Variance
                                </div>
                            ) : (
                                <>
                                    <div className="flex justify-between">
                                        <span className="text-red-400/80 font-bold">+2σ / +1σ</span>
                                        <span className="font-mono text-red-300">
                                            {amtResult?.vwapUpper2?.toFixed(2)} / {amtResult?.vwapUpper1?.toFixed(2)}
                                        </span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-emerald-400/80 font-bold">-1σ / -2σ</span>
                                        <span className="font-mono text-emerald-300">
                                            {amtResult?.vwapLower1?.toFixed(2)} / {amtResult?.vwapLower2?.toFixed(2)}
                                        </span>
                                    </div>
                                </>
                            )}

                            {/* Inline Deviation Meter (-3σ to +3σ) */}
                            {currentLtp > 0 && amtResult?.sessionVwap && (
                                <div className="pt-3 pb-1 border-t border-white/5">
                                    {!isVwapFlat && (
                                        <>
                                            <div className="flex justify-between text-[8px] font-mono text-white/30 mb-1">
                                                <span className="text-emerald-400">-3σ</span>
                                                <span>VWAP</span>
                                                <span className="text-red-400">+3σ</span>
                                            </div>
                                            <div className="h-1.5 relative bg-white/5 rounded-full">
                                                <div className="absolute top-0 left-1/2 w-0.5 h-full bg-cyan-400"></div>
                                                <div className="absolute top-0 left-[33.3%] w-px h-full bg-emerald-500/30"></div>
                                                <div className="absolute top-0 left-[16.6%] w-px h-full bg-emerald-500/50"></div>
                                                <div className="absolute top-0 right-[33.3%] w-px h-full bg-red-500/30"></div>
                                                <div className="absolute top-0 right-[16.6%] w-px h-full bg-red-500/50"></div>

                                                {(() => {
                                                    if (isVwapFlat) return null;
                                                    const sigma = amtResult.vwapDeviationSigmas;
                                                    if (sigma !== null && sigma !== undefined) {
                                                        // Map -3 to +3 to 0% to 100%
                                                        const percentage = Math.max(0, Math.min(100, ((sigma + 3) / 6) * 100));
                                                        return (
                                                            <div
                                                                className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-white shadow-[0_0_5px_white] z-10"
                                                                style={{ left: `calc(${percentage}% - 4px)` }}
                                                            />
                                                        );
                                                    }
                                                    return null;
                                                })()}
                                            </div>
                                        </>
                                    )}
                                    {isVwapFlat ? (
                                        <div className="mt-2 text-center text-[9px] text-amber-400/60 font-mono">σ N/A — Flat Market</div>
                                    ) : (
                                        (() => {
                                            const sigma = amtResult.vwapDeviationSigmas;
                                            if (sigma !== null && sigma !== undefined) {
                                                // Use the engine's ≥3σ flag (DTO isExtremeDeviation) as the
                                                // single source of truth — a hardcoded 1.8σ threshold here
                                                // once showed "EXTREME DEVIATION" while the engine still
                                                // classified the market BALANCED.
                                                const isExtreme = amtResult.isExtremeDeviation === true;
                                                return (
                                                    <div className={`mt-2 text-center text-[9px] font-mono font-bold flex flex-col items-center gap-1 ${sigma > 1 ? 'text-red-400' : sigma < -1 ? 'text-emerald-400' : 'text-yellow-400'}`}>
                                                        <span>LTP is {sigma > 0 ? '+' : ''}{sigma.toFixed(2)}σ from VWAP</span>
                                                        {isExtreme && (
                                                            <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 border border-red-500/30 rounded text-[8px] animate-pulse">
                                                                EXTREME DEVIATION - FADE ZONES ACTIVE
                                                            </span>
                                                        )}
                                                    </div>
                                                );
                                            }
                                            return <div className="mt-2 text-center text-[9px] text-white/40">Calculating σ...</div>;
                                        })()
                                    )}
                                </div>
                            )}
                        </>
                    );
                })()}
                {amtResult?.gapType && (
                    <div className="flex justify-between">
                        <span className="text-white/40">Gap</span>
                        <span className={`font-mono font-bold ${amtResult.gapType === 'LARGE' ? 'text-red-400' :
                            amtResult.gapType === 'MEDIUM' ? 'text-orange-400' : 'text-white/50'
                            }`}>{amtResult.gapType}</span>
                    </div>
                )}
                {amtResult?.openingBias && (
                    <div className="flex justify-between">
                        <span className="text-white/40">Opening Bias</span>
                        <span className={`font-mono font-bold ${amtResult.openingBias === 'LONG_BIAS' ? 'text-emerald-400' :
                            amtResult.openingBias === 'SHORT_BIAS' ? 'text-red-400' : 'text-white/50'
                            }`}>{amtResult.openingBias.replace('_BIAS', '')}</span>
                    </div>
                )}
                {(amtResult?.priceVelocity ?? 0) > 0 && (
                    <div className="flex justify-between">
                        <span className="text-white/40">Price Velocity</span>
                        <span className="font-mono text-white/50">{amtResult?.priceVelocity?.toFixed(4)}/s</span>
                    </div>
                )}
            </div>
        </div>
    );
});

VwapContextCard.displayName = 'VwapContextCard';

export default VwapContextCard;
