import React from 'react';
import { AMTAnalysis } from '../../types';

interface GammaExposureCardProps {
    amtResult: AMTAnalysis | null;
    currentLtp: number;
}

/** 03g. Dealer Gamma Exposure (GEX) — Net GEX, Regime, Zero-Gamma Flip & Strike Walls. */
const GammaExposureCard = React.memo<GammaExposureCardProps>(({ amtResult, currentLtp }) => {
    const gex = amtResult?.gex;
    if (!gex || (!gex.netGexCrores && !gex.zeroFlipLevel && !gex.callWallStrike)) {
        return null;
    }

    const isPositive = gex.regime === 'POSITIVE_GAMMA';
    const isNegative = gex.regime === 'NEGATIVE_GAMMA';

    const regimeLabel = isPositive
        ? 'POSITIVE GAMMA — Mean Reversion / Low Vol'
        : isNegative
        ? 'NEGATIVE GAMMA — Vol Acceleration / Breakout'
        : 'TRANSITION / NEUTRAL GAMMA';

    const regimeBg = isPositive
        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
        : isNegative
        ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
        : 'bg-amber-500/10 text-amber-400 border-amber-500/20';

    const effectiveSpot =
        currentLtp > 500
            ? currentLtp
            : amtResult?.poc && amtResult.poc > 0
            ? amtResult.poc
            : 0;

    const flipDistancePct =
        effectiveSpot > 0 && gex.zeroFlipLevel > 0
            ? ((effectiveSpot - gex.zeroFlipLevel) / gex.zeroFlipLevel) * 100
            : 0;

    const displayStrikes = React.useMemo(() => {
        if (!gex.strikeGex || gex.strikeGex.length === 0) return [];
        if (gex.strikeGex.length <= 5) return gex.strikeGex;
        const target = effectiveSpot > 0 ? effectiveSpot : gex.zeroFlipLevel || gex.gammaPinStrike;
        return [...gex.strikeGex]
            .sort((a, b) => Math.abs(a.strike - target) - Math.abs(b.strike - target))
            .slice(0, 5)
            .sort((a, b) => a.strike - b.strike);
    }, [gex.strikeGex, effectiveSpot, gex.zeroFlipLevel, gex.gammaPinStrike]);

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>03g. Dealer Gamma Exposure (GEX)</span>
                <span className="font-mono text-[9px] text-white/60">
                    {gex.netGexCrores >= 0 ? `+₹${gex.netGexCrores.toFixed(1)} Cr` : `-₹${Math.abs(gex.netGexCrores).toFixed(1)} Cr`}
                </span>
            </div>
            <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2 text-[9px]">
                {/* Regime Badge */}
                <div className={`text-center py-1.5 px-2 font-bold text-[9px] rounded border ${regimeBg}`}>
                    {regimeLabel}
                </div>

                {/* Key GEX Levels */}
                <div className="grid grid-cols-2 gap-2 pt-1 border-t border-white/5">
                    <div className="flex flex-col">
                        <span className="text-white/40">Zero-Gamma Flip</span>
                        <div className="flex items-baseline gap-1.5 font-mono">
                            <span className="text-amber-300 font-bold">{gex.zeroFlipLevel.toFixed(1)}</span>
                            {effectiveSpot > 0 && (
                                <span className={`text-[8px] ${flipDistancePct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {flipDistancePct >= 0 ? '+' : ''}{flipDistancePct.toFixed(2)}%
                                </span>
                            )}
                        </div>
                    </div>
                    <div className="flex flex-col">
                        <span className="text-white/40">Gamma Pin Strike</span>
                        <span className="font-mono text-cyan-300 font-bold">{gex.gammaPinStrike.toFixed(1)}</span>
                    </div>
                </div>

                {/* Institutional Strike Walls */}
                <div className="grid grid-cols-2 gap-2 pt-1.5 border-t border-white/5">
                    <div className="flex justify-between items-center p-1.5 rounded bg-rose-500/5 border border-rose-500/15">
                        <span className="text-rose-400 font-bold">Call Wall (Res)</span>
                        <span className="font-mono text-rose-300 font-bold">{gex.callWallStrike.toFixed(0)}</span>
                    </div>
                    <div className="flex justify-between items-center p-1.5 rounded bg-emerald-500/5 border border-emerald-500/15">
                        <span className="text-emerald-400 font-bold">Put Wall (Sup)</span>
                        <span className="font-mono text-emerald-300 font-bold">{gex.putWallStrike.toFixed(0)}</span>
                    </div>
                </div>

                {/* Mini Strike GEX Distribution Bar Chart */}
                {displayStrikes.length > 0 && (
                    <div className="pt-2 border-t border-white/5 space-y-1">
                        <div className="flex justify-between text-[8px] text-white/30 font-mono">
                            <span>Near-ATM Strike</span>
                            <span>Put GEX (Red) | Call GEX (Green)</span>
                        </div>
                        <div className="space-y-1">
                            {displayStrikes.map((sg) => {
                                const maxBar = Math.max(Math.abs(sg.callGex), Math.abs(sg.putGex), 0.1);
                                const callPct = Math.min(100, (Math.abs(sg.callGex) / maxBar) * 50);
                                const putPct = Math.min(100, (Math.abs(sg.putGex) / maxBar) * 50);
                                const isAtm = effectiveSpot > 0 && Math.abs(effectiveSpot - sg.strike) <= (effectiveSpot * 0.01 || 500);

                                return (
                                    <div key={sg.strike} className="flex items-center gap-1.5 text-[8px] font-mono">
                                        <span className={`w-12 text-right ${isAtm ? 'text-cyan-300 font-bold' : 'text-white/50'}`}>
                                            {sg.strike.toFixed(0)}
                                        </span>
                                        <div className="flex-1 h-1.5 flex bg-white/5 rounded overflow-hidden">
                                            <div className="flex-1 flex justify-end">
                                                <div
                                                    className="h-full bg-rose-500/80 rounded-l"
                                                    style={{ width: `${putPct}%` }}
                                                />
                                            </div>
                                            <div className="w-px h-full bg-white/20" />
                                            <div className="flex-1 flex justify-start">
                                                <div
                                                    className="h-full bg-emerald-500/80 rounded-r"
                                                    style={{ width: `${callPct}%` }}
                                                />
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
});

export default GammaExposureCard;
