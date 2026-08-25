import React from 'react';
import { Crosshair, Navigation } from 'lucide-react';
import { AMTAnalysis } from '../../types';

interface InitialBalanceCardProps {
    amtResult: AMTAnalysis | null;
    currentLtp: number;
}

/** 03d. IB + BREAKS — initial balance range, size class, extension targets, breaks. */
const InitialBalanceCard = React.memo<InitialBalanceCardProps>(({ amtResult, currentLtp }) => {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>03d. IB + Breaks</span>
                <Crosshair className="w-3 h-3 hover:text-white/80 transition-colors" />
            </div>
            <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                {/* Initial Balance Range Band */}
                <div className="flex justify-between items-center">
                    <span className="text-[10px] text-white/40">IB Range</span>
                    <span className="flex items-center gap-2">
                        {amtResult?.ibHigh && amtResult?.ibLow ? (
                            <span className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-[10px] font-mono text-white/70">
                                {amtResult.ibLow.toFixed(2)} <span className="text-white/20 mx-1">──</span> {amtResult.ibHigh.toFixed(2)}
                            </span>
                        ) : (
                            <span className="text-[10px] font-mono text-white/40">Building...</span>
                        )}

                        {amtResult?.ibComplete && (
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wider ${amtResult?.breakDirection ? 'bg-orange-500/20 text-orange-400' : 'bg-emerald-500/20 text-emerald-400'}`}>
                                {amtResult?.breakDirection ? `BROKEN ${amtResult.breakDirection === 'UP' ? '↑' : '↓'}` : '✅ INTACT'}
                            </span>
                        )}
                    </span>
                </div>
                {/* Item 4.9: IB Size Classification */}
                {amtResult?.ibHigh && amtResult?.ibLow && amtResult.ibHigh > 0 && amtResult.ibLow > 0 && (() => {
                    const ibSize = amtResult.ibHigh - amtResult.ibLow;
                    const ibMid = (amtResult.ibHigh + amtResult.ibLow) / 2;
                    // Classification based on IB size relative to mid price (percentage)
                    const ibPct = (ibSize / ibMid) * 100;
                    let sizeClass = 'NORMAL';
                    let sizeColor = 'text-white/60';
                    let sizeBg = 'bg-white/5';

                    if (ibPct < 0.5) {
                        sizeClass = 'NARROW';
                        sizeColor = 'text-yellow-400';
                        sizeBg = 'bg-yellow-500/10';
                    } else if (ibPct > 1.5) {
                        sizeClass = 'WIDE';
                        sizeColor = 'text-red-400';
                        sizeBg = 'bg-red-500/10';
                    }

                    return (
                        <div className="flex justify-between items-center pt-1 border-t border-white/5">
                            <span className="text-[10px] text-white/40">IB Size</span>
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold ${sizeColor} ${sizeBg}`}>
                                {ibSize.toFixed(2)} pts — {sizeClass} ({ibPct.toFixed(2)}%)
                            </span>
                        </div>
                    );
                })()}
                {/* Proximity Warning */}
                {(() => {
                    if (currentLtp > 0 && amtResult?.ibHigh && amtResult?.ibLow && amtResult?.ibComplete && !amtResult?.breakDirection) {
                        const ibRange = amtResult.ibHigh - amtResult.ibLow;
                        const threshold = ibRange * 0.1;
                        if (Math.abs(currentLtp - amtResult.ibHigh) <= threshold) {
                            return <div className="text-[9px] font-mono font-bold text-yellow-400 bg-yellow-500/10 px-1.5 py-0.5 rounded mt-1 mb-2 inline-block">Proximity to IB High — Prepare for Bounce/Break</div>;
                        } else if (Math.abs(currentLtp - amtResult.ibLow) <= threshold) {
                            return <div className="text-[9px] font-mono font-bold text-yellow-400 bg-yellow-500/10 px-1.5 py-0.5 rounded mt-1 mb-2 inline-block">Proximity to IB Low — Prepare for Bounce/Break</div>;
                        }
                    }
                    return null;
                })()}
                {/* Break Detection */}
                {amtResult?.breakDirection ? (
                    <div className={`px-2 py-1.5 rounded border flex items-center justify-between ${amtResult.breakType === 'INITIATIVE' ? 'bg-orange-500/10 border-orange-500/20' :
                        amtResult.breakType === 'RESPONSIVE' ? 'bg-cyan-500/10 border-cyan-500/20' :
                            'bg-purple-500/10 border-purple-500/20'
                        }`}>
                        <div className="flex items-center gap-1.5">
                            <Navigation className={`w-3 h-3 ${amtResult.breakDirection === 'UP' ? 'text-emerald-400 rotate-0' : 'text-red-400 rotate-180'}`} />
                            <span className={`text-[9px] font-bold uppercase ${amtResult.breakType === 'INITIATIVE' ? 'text-orange-400' :
                                amtResult.breakType === 'RESPONSIVE' ? 'text-cyan-400' :
                                    'text-purple-400'
                                }`}>{amtResult.breakType} BREAK {amtResult.breakDirection}</span>
                        </div>
                        <span className="text-[9px] font-mono text-white/40">@ {amtResult.breakLevel?.toFixed(2)}</span>
                    </div>
                ) : (
                    <div className="text-[9px] text-white/20">No break detected</div>
                )}
                {/* Failed Breakout Detection (MRL-009): IB broke UP but price below VAL, or IB broke DOWN but price above VAH */}
                {(() => {
                    const ibDir = amtResult?.breakDirection ?? '';
                    const val = amtResult?.valueAreaLow ?? 0;
                    const vah = amtResult?.valueAreaHigh ?? 0;
                    if (!ibDir || !currentLtp || val <= 0 || vah <= 0) return null;

                    // Strict failure: price completely outside VA on wrong side
                    const failedUpBreak = ibDir === 'UP' && currentLtp < val;
                    const failedDownBreak = ibDir === 'DOWN' && currentLtp > vah;
                    // Weak failure: price rejected back into value, near opposite boundary
                    const vaRange = vah - val;
                    const threshold = vaRange * 0.05; // 5% of VA range
                    const weakFailedUp = ibDir === 'UP' && currentLtp < (val + threshold) && currentLtp > val;
                    const weakFailedDown = ibDir === 'DOWN' && currentLtp > (vah - threshold) && currentLtp < vah;

                    if (failedUpBreak || weakFailedUp) {
                        return (
                            <div className="mt-1 px-2 py-1 bg-red-500/10 border border-red-500/30 rounded text-[9px] font-bold text-red-400 text-center animate-pulse">
                                ⚠️ FAILED BREAKOUT — REJECTION OF VALUE (IB broke ↑ but rejected)
                            </div>
                        );
                    }
                    if (failedDownBreak || weakFailedDown) {
                        return (
                            <div className="mt-1 px-2 py-1 bg-red-500/10 border border-red-500/30 rounded text-[9px] font-bold text-red-400 text-center animate-pulse">
                                ⚠️ FAILED BREAKOUT — REJECTION OF VALUE (IB broke ↓ but rejected)
                            </div>
                        );
                    }
                    return null;
                })()}
            </div>
        </div>
    );
});

InitialBalanceCard.displayName = 'InitialBalanceCard';

export default InitialBalanceCard;
