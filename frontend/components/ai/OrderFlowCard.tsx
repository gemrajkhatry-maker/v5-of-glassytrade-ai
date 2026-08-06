import React from 'react';
import { AMTAnalysis, OrderBook } from '../../types';

interface OrderFlowCardProps {
    amtResult: AMTAnalysis | null;
    symbol?: string;
    orderBook?: OrderBook | null;
}

/** 03B. MARKET METRICS — OFI / CVD slope / divergence / balance / shape / spread. */
const formatCVD = (cvd: number): string => {
    const abs = Math.abs(cvd);
    if (abs >= 1_000_000) return `${(cvd / 1_000_000).toFixed(2)}M lots`;
    if (abs >= 1_000) return `${(cvd / 1_000).toFixed(1)}K lots`;
    return `${cvd.toFixed(1)} lots`;
};

const OrderFlowCard = React.memo<OrderFlowCardProps>(({ amtResult, symbol, orderBook }) => {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-glassy-text-tertiary uppercase tracking-widest">
                <span>03B. Market Metrics</span>
            </div>
            <div className="p-3 rounded-md bg-glassy-bg-elevated/50 border border-glassy-border-subtle space-y-2">
                {/* OFI Bar */}
                <div>
                    <div className="flex justify-between mb-1">
                        <span className="text-[10px] text-glassy-text-tertiary">OFI <span className="text-[8px] text-glassy-text-disabled">(norm)</span></span>
                        <div className="flex items-center gap-1.5">
                            <span className={`text-[10px] ${(amtResult?.ofi ?? 0) > 0 ? 'text-glassy-bull-primary' : (amtResult?.ofi ?? 0) < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                                {(amtResult?.ofi ?? 0) > 0 ? '╱╲↗' : (amtResult?.ofi ?? 0) < 0 ? '╲╱↘' : '—'}
                            </span>
                            <span className={`text-[10px] font-mono font-bold tabular-nums ${(amtResult?.ofi ?? 0) > 0 ? 'text-glassy-bull-primary' : (amtResult?.ofi ?? 0) < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                                {(amtResult?.ofi ?? 0) > 0 ? '+' : ''}{(amtResult?.ofi ?? 0).toFixed(3)}
                            </span>
                        </div>
                    </div>
                    <div className="h-1.5 bg-glassy-text-disabled/20 rounded-full overflow-hidden relative">
                        <div className="absolute top-0 left-1/2 w-px h-full bg-glassy-text-disabled/30" />
                        {(amtResult?.ofi ?? 0) !== 0 && (
                            <div className="absolute top-0 h-full rounded-full transition-all duration-300" style={{
                                left: (amtResult?.ofi ?? 0) > 0 ? '50%' : `${50 + (amtResult?.ofi ?? 0) * 50}%`,
                                width: `${Math.min(Math.abs(amtResult?.ofi ?? 0) * 50, 50)}%`,
                                backgroundColor: (amtResult?.ofi ?? 0) > 0 ? '#00c896' : '#ff4757',
                                opacity: 0.7,
                            }} />
                        )}
                    </div>
                </div>
                {/* CVD Slope Bar */}
                <div>
                    <div className="flex justify-between mb-1">
                        <span className="text-[10px] text-glassy-text-tertiary">CVD Slope</span>
                        <div className="flex items-center gap-1.5">
                            <span className={`text-[10px] ${(amtResult?.cvdSlope ?? 0) > 0 ? 'text-glassy-bull-primary' : (amtResult?.cvdSlope ?? 0) < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                                {(amtResult?.cvdSlope ?? 0) > 0 ? '╱╲↗' : (amtResult?.cvdSlope ?? 0) < 0 ? '╲╱↘' : '—'}
                            </span>
                            <span className={`text-[10px] font-mono font-bold tabular-nums ${(amtResult?.cvdSlope ?? 0) > 0 ? 'text-glassy-bull-primary' : (amtResult?.cvdSlope ?? 0) < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                                {(amtResult?.cvdSlope ?? 0) > 0 ? '+' : ''}{formatCVD(amtResult?.cvdSlope ?? 0)}
                                {amtResult?.cvdDivergence ? ` (${amtResult.cvdDivergence.replace('_DIV', '')})` : ''}
                                {(amtResult?.cvdSlope ?? 0) > 0.01 ? ' BULLISH' : (amtResult?.cvdSlope ?? 0) < -0.01 ? ' BEARISH' : ' FLAT'}
                            </span>
                        </div>
                    </div>
                    <div className="h-1.5 bg-glassy-text-disabled/20 rounded-full overflow-hidden relative">
                        <div className="absolute top-0 left-1/2 w-px h-full bg-glassy-text-disabled/30" />
                        {(() => {
                            const cvd = amtResult?.cvdSlope ?? 0;
                            const norm = Math.min(Math.abs(cvd) / 100, 1);
                            return cvd !== 0 ? (
                                <div className="absolute top-0 h-full rounded-full transition-all duration-300" style={{
                                    left: cvd > 0 ? '50%' : `${50 - norm * 50}%`,
                                    width: `${norm * 50}%`,
                                    backgroundColor: cvd > 0 ? '#4ade80' : '#f87171',
                                    opacity: 0.7,
                                }} />
                            ) : null;
                        })()}
                    </div>
                </div>
                {/* Aggression Divergence Check */}
                {(() => {
                    const delta = amtResult?.deltaNormalizedOption ?? 0;
                    const cvd = amtResult?.cvdSlope ?? 0;
                    const ofi = amtResult?.ofi ?? 0;
                    const ibBreak = amtResult?.breakDirection ?? '';
                    // Lowered delta threshold from 0.1 to 0.02 to catch more divergence cases
                    const bullCount = (delta > 0.02 ? 1 : 0) + (cvd > 0.01 ? 1 : 0) + (ofi > 0.1 ? 1 : 0);
                    const bearCount = (delta < -0.02 ? 1 : 0) + (cvd < -0.01 ? 1 : 0) + (ofi < -0.1 ? 1 : 0);
                    // Also detect CVD vs IB break divergence (e.g. bullish CVD but bearish IB break)
                    const cvdBullish = cvd > 0.01;
                    const cvdBearish = cvd < -0.01;
                    const ibBullish = ibBreak === 'UP';
                    const ibBearish = ibBreak === 'DOWN';
                    const cvdIbDivergence = (cvdBullish && ibBearish) || (cvdBearish && ibBullish);
                    const hasConflict = (bullCount > 0 && bearCount > 0) || cvdIbDivergence;
                    // CE/PE context: interpret option flow direction relative to underlying
                    const isCE = symbol?.toUpperCase().includes(' CE') || symbol?.toUpperCase().endsWith('CE');
                    const isPE = symbol?.toUpperCase().includes(' PE') || symbol?.toUpperCase().endsWith('PE');
                    const cvdDir = cvd > 0.01 ? 'bullish' : cvd < -0.01 ? 'bearish' : 'neutral';
                    const underlyingSignal = isCE
                        ? (cvdDir === 'bullish' ? '↗ Bullish flow on CE → underlying bullish signal' : cvdDir === 'bearish' ? '↘ Bearish flow on CE → underlying bearish signal' : '')
                        : isPE
                        ? (cvdDir === 'bullish' ? '↗ Bullish flow on PE → underlying bearish signal (put accumulation)' : cvdDir === 'bearish' ? '↘ Bearish flow on PE → underlying bullish signal (put unwinding)' : '')
                        : '';
                    return (
                        <>
                            {hasConflict && (
                                <div className="mt-1.5 px-2 py-1 bg-yellow-500/10 border border-yellow-500/30 rounded text-[9px] font-bold text-yellow-400 text-center">
                                    CONFLICTED AGGRESSION — {cvdIbDivergence && !(bullCount > 0 && bearCount > 0)
                                        ? `CVD/IB Divergence — CVD ${cvdBullish ? 'Bullish' : 'Bearish'} vs IB ${ibBullish ? 'UP' : 'DOWN'}`
                                        : 'Delta/CVD/OFI Divergence'}
                                </div>
                            )}
                            {underlyingSignal && (
                                <div className="mt-1 px-2 py-0.5 bg-blue-500/10 border border-blue-500/20 rounded text-[8px] font-medium text-blue-400 text-center">
                                    OPTION CONTEXT: {underlyingSignal}
                                </div>
                            )}
                        </>
                    );
                })()}
                {/* Balance / Price Location */}
                <div>
                    <div className="flex justify-between mb-1">
                        <span className="text-[10px] text-white/40">Balance</span>
                        {(() => {
                            const ltp = amtResult?.sessionVwap ?? 0;
                            const vah = amtResult?.valueAreaHigh ?? 0;
                            const val = amtResult?.valueAreaLow ?? 0;
                            const ratio = (amtResult?.balanceRatio ?? 0) * 100;
                            if (ltp > 0 && vah > 0 && ltp > vah) {
                                return <span className="text-[10px] font-mono font-bold text-orange-400">0% in VA (Above ↑)</span>;
                            } else if (ltp > 0 && val > 0 && ltp < val) {
                                return <span className="text-[10px] font-mono font-bold text-red-400">0% in VA (Below ↓)</span>;
                            } else if (ratio >= 50 && ratio <= 70) {
                                return <span className="text-[10px] font-mono font-bold text-yellow-400">{ratio.toFixed(0)}% in VA (TRANSITIONING)</span>;
                            } else {
                                return <span className="text-[10px] font-mono font-bold text-blue-300">{ratio.toFixed(0)}% in VA</span>;
                            }
                        })()}
                    </div>
                    <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-300" style={{
                            width: `${(amtResult?.balanceRatio ?? 0) * 100}%`,
                            backgroundColor: '#60a5fa',
                            opacity: 0.6,
                        }} />
                    </div>
                </div>
                {/* Profile Shape + Spread + Depth row */}
                <div className="flex justify-between items-center pt-1 border-t border-white/5">
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] text-white/40">Shape</span>
                        <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${amtResult?.profileShape === 'B' ? 'bg-purple-500/20 text-purple-400' :
                            amtResult?.profileShape === 'P' ? 'bg-red-500/20 text-red-400' :
                                amtResult?.profileShape === 'b' ? 'bg-green-500/20 text-green-400' :
                                    'bg-white/10 text-white/40'
                            }`}>
                            {amtResult?.profileShape === 'B' ? 'B Bimodal' :
                                amtResult?.profileShape === 'P' ? 'P Top-heavy' :
                                    amtResult?.profileShape === 'b' ? 'b Bottom-heavy' :
                                        amtResult?.profileShape === 'D' ? 'D Balanced' : '—'}
                        </span>
                        <span className="text-[8px] text-white/30">
                            ({amtResult?.profileType || 'Session'})
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        {(() => {
                            const bestBid = orderBook?.bids?.[0]?.price ?? 0;
                            const bestAsk = orderBook?.asks?.[0]?.price ?? 0;
                            const mid = (bestBid + bestAsk) / 2;
                            const spreadBps = mid > 0 ? ((bestAsk - bestBid) / mid * 10000) : 0;
                            return bestBid > 0 ? (
                                <span className={`text-[10px] font-mono ${spreadBps <= 5 ? 'text-green-400' : spreadBps <= 15 ? 'text-yellow-400' : 'text-red-400'}`}>
                                    {spreadBps.toFixed(1)} bps
                                </span>
                            ) : <span className="text-[10px] text-white/20">—</span>;
                        })()}
                    </div>
                </div>
            </div>
        </div>
    );
});

OrderFlowCard.displayName = 'OrderFlowCard';

export default OrderFlowCard;
