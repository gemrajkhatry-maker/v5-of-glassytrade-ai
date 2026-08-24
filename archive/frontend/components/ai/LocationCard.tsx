import React from 'react';
import { AMTAnalysis } from '../../types';

interface LocationCardProps {
    currentLtp: number;
    amtResult: AMTAnalysis | null;
    poc: string;
}

/** 02. LOCATION — volume-profile bar with VAH/VAL/POC markers and LTP position. */
const LocationCard = React.memo<LocationCardProps>(({ currentLtp, amtResult, poc }) => {
    return (
        <div className="flex flex-col gap-2">
            <div className="p-3 rounded-md bg-glassy-bg-elevated/50 border border-glassy-border-default relative">
                <span className="absolute -top-2 left-2 px-1 bg-glassy-bg-tertiary text-[10px] text-glassy-text-tertiary uppercase tracking-widest font-bold">Location</span>

                {currentLtp > 0 && (amtResult?.poc !== undefined && amtResult?.poc !== null) ? (
                    <>
                    <div className="mt-3 relative h-16 flex items-center justify-center">
                        {(() => {
                            const min = Math.min(amtResult.valueAreaLow || currentLtp, amtResult.dailyVal || currentLtp, amtResult.legVal || currentLtp, currentLtp) * 0.999;
                            const max = Math.max(amtResult.valueAreaHigh || currentLtp, amtResult.dailyVah || currentLtp, amtResult.legVah || currentLtp, currentLtp) * 1.001;
                            const range = max - min || 1;
                            const getPos = (val: number) => `${Math.max(5, Math.min(95, ((val - min) / range) * 100))}%`;

                            return (
                                <div className="w-full relative h-1">
                                    {/* Base Track */}
                                    <div className="absolute top-0 left-0 w-full h-full bg-glassy-text-disabled/20 rounded-full"></div>

                                    {/* VA Fill (Session) */}
                                    {amtResult.valueAreaHigh > 0 && (
                                        <div className="absolute top-0 h-full bg-glassy-ai-primary/20" style={{ left: getPos(amtResult.valueAreaLow), width: `${((amtResult.valueAreaHigh - amtResult.valueAreaLow) / range) * 100}%` }}></div>
                                    )}

                                    {/* VAH Marker */}
                                    {amtResult.valueAreaHigh > 0 && (
                                        <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: getPos(amtResult.valueAreaHigh) }}>
                                            <div className="w-0.5 h-3 bg-glassy-ai-primary"></div>
                                            <span className="text-[8px] text-glassy-ai-primary mt-1 absolute top-3 whitespace-nowrap tabular-nums">VAH {amtResult.valueAreaHigh?.toFixed(1)}</span>
                                        </div>
                                    )}
                                    {/* VAL Marker */}
                                    {amtResult.valueAreaLow > 0 && (
                                        <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: getPos(amtResult.valueAreaLow) }}>
                                            <div className="w-0.5 h-3 bg-glassy-ai-primary"></div>
                                            <span className="text-[8px] text-glassy-ai-primary mt-1 absolute top-3 whitespace-nowrap tabular-nums">VAL {amtResult.valueAreaLow?.toFixed(1)}</span>
                                        </div>
                                    )}

                                    {/* Hourly POC (AI Purple Dot) */}
                                    {amtResult.hourlyPoc > 0 && (
                                        <div className="absolute top-1/2 -translate-y-[150%] flex flex-col items-center z-5" style={{ left: getPos(amtResult.hourlyPoc) }}>
                                            <div className="w-1.5 h-1.5 rounded-full bg-glassy-ai-primary/60 border border-glassy-ai-primary"></div>
                                            <span className="text-[7px] text-glassy-ai-primary mb-1 absolute bottom-1 whitespace-nowrap">HPOC</span>
                                        </div>
                                    )}

                                    {/* Daily POC (Purple Dot) */}
                                    {amtResult.dailyPoc > 0 && (
                                        <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center z-5" style={{ left: getPos(amtResult.dailyPoc) }}>
                                            <div className="w-2 h-2 rounded-full bg-purple-500/80 border border-purple-400"></div>
                                            <span className="text-[8px] font-bold text-purple-400 mt-1 absolute top-2 whitespace-nowrap">DPOC</span>
                                        </div>
                                    )}

                                    {/* Session POC Marker (Yellow) */}
                                    <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center z-10" style={{ left: getPos(amtResult.poc) }}>
                                        <div className="w-2 h-2 rounded-full bg-yellow-400 shadow-[0_0_8px_rgba(250,204,21,0.5)]"></div>
                                        <span className="text-[9px] font-bold text-yellow-400 mt-1 absolute top-2 flex flex-col items-center">
                                            <span>POC</span>
                                            <span className="font-mono">{poc}</span>
                                        </span>
                                    </div>

                                    {/* Leg POC Marker (Orange) */}
                                    {amtResult.legPoc > 0 && Math.abs(amtResult.legPoc - amtResult.poc) > 0.5 && (
                                        <div className="absolute top-1/2 translate-y-[50%] flex flex-col items-center z-10" style={{ left: getPos(amtResult.legPoc) }}>
                                            <div className="w-1.5 h-1.5 rounded-full bg-orange-500 shadow-[0_0_4px_rgba(249,115,22,0.5)]"></div>
                                            <span className="text-[8px] font-bold text-orange-400 mt-0.5 absolute top-1.5 whitespace-nowrap">LEG {amtResult.legPoc.toFixed(1)}</span>
                                        </div>
                                    )}

                                    {/* LTP Marker */}
                                    <div className="absolute top-1/2 -translate-y-[140%] flex flex-col items-center z-20" style={{ left: getPos(currentLtp) }}>
                                        <div className="px-1.5 py-0.5 bg-white text-black text-[9px] font-bold font-mono rounded shadow-lg flex items-center gap-1 mb-1">
                                            {currentLtp.toFixed(1)} <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
                                        </div>
                                        <div className="w-px h-3 bg-white"></div>
                                    </div>
                                </div>
                            );
                        })()}
                    </div>
                    {/* Overflow indicators when LTP is outside VA */}
                    {(() => {
                        // Use leg VAH/VAL when PROBING/IMBALANCED for relevant distance display
                        const isLegActive = amtResult.legPoc > 0 && (amtResult.marketState === 'PROBING' || amtResult.marketState === 'IMBALANCED');
                        const refVah = isLegActive && amtResult.legVah > 0 ? amtResult.legVah : amtResult.valueAreaHigh;
                        const refVal = isLegActive && amtResult.legVal > 0 ? amtResult.legVal : amtResult.valueAreaLow;
                        const vahLabel = isLegActive && amtResult.legVah > 0 ? 'Leg VAH' : 'Session VAH';
                        const valLabel = isLegActive && amtResult.legVal > 0 ? 'Leg VAL' : 'Session VAL';
                        return <>
                            {refVah > 0 && currentLtp > refVah && (
                                <div className="text-[9px] text-amber-400 font-mono mt-2 text-center">
                                    ↑ ABOVE {vahLabel} by {(currentLtp - refVah).toFixed(2)} pts
                                </div>
                            )}
                            {refVal > 0 && currentLtp < refVal && (
                                <div className="text-[9px] text-amber-400 font-mono mt-2 text-center">
                                    ↓ BELOW {valLabel} by {(refVal - currentLtp).toFixed(2)} pts
                                </div>
                            )}
                        </>;
                    })()}
                </>
                ) : (
                    <div className="text-center text-[10px] text-glassy-text-disabled py-4 font-mono">Building Volume Profile...</div>
                )}
                </div>
            </div>
    );
});

LocationCard.displayName = 'LocationCard';

export default LocationCard;
