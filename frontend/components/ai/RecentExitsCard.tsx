import React from 'react';
import { TradePosition } from '../../types';

interface RecentExitsCardProps {
    closedTrades: TradePosition[];
}

/** Recent closed trades — last 5 exits with P&L, duration, close reason. */
const RecentExitsCard = React.memo<RecentExitsCardProps>(({ closedTrades }) => {
    if (closedTrades.length === 0) return null;

    return (
        <div className="flex flex-col gap-2">
            <div className="text-[10px] text-white/40 uppercase tracking-widest">
                Recent Exits ({closedTrades.length})
            </div>
            <div className="space-y-1.5 max-h-[180px] overflow-y-auto">
                {[...closedTrades].reverse().slice(0, 5).map((t, i) => {
                    const partialPnl = t.partialRealizedPnl || 0;
                    const totalPnl = t.pnl;
                    const hadPartial = partialPnl > 0;
                    const duration = t.exitTime && t.entryTime
                        ? Math.round((new Date(t.exitTime).getTime() - new Date(t.entryTime).getTime()) / 1000)
                        : 0;
                    const dMins = Math.floor(duration / 60);
                    const dSecs = duration % 60;
                    return (
                        <div key={i} className="px-2 py-1.5 rounded bg-white/5 border border-white/5 space-y-1">
                            <div className="flex justify-between items-center text-[9px]">
                                <span className={`font-bold ${t.side === 'LONG' ? 'text-green-400/80' : 'text-red-400/80'}`}>
                                    {t.side} x{(t.originalSize || t.size).toFixed(0)}
                                </span>
                                <span className={`font-mono font-bold ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {totalPnl >= 0 ? '+' : ''}₹{totalPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </span>
                            </div>
                            <div className="flex justify-between items-center text-[8px]">
                                <span className="text-white/25 font-mono">
                                    {t.entryPrice?.toFixed(2) || '—'} → {t.exitPrice?.toFixed(2) || '—'}
                                </span>
                                <span className="text-white/25 font-mono">{dMins > 0 ? `${dMins}m ${dSecs}s` : `${dSecs}s`}</span>
                            </div>
                            <div className="flex justify-between items-center text-[8px]">
                                {hadPartial ? (
                                    <span className="text-orange-400/70">
                                        Partial +₹{partialPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })} + Runner ₹{(totalPnl - partialPnl).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                                    </span>
                                ) : (
                                    <span className="text-white/20">Full exit</span>
                                )}
                                <span className={`font-mono px-1 py-0.5 rounded text-[7px] ${t.closeReason === 'TAKE_PROFIT' || t.closeReason === 'PARTIAL_TAKE_PROFIT' ? 'bg-green-500/20 text-green-400' :
                                    t.closeReason === 'STOP_LOSS' ? 'bg-red-500/20 text-red-400' :
                                        t.closeReason === 'SCRATCH' ? 'bg-yellow-500/20 text-yellow-400' :
                                            t.closeReason === 'TRAILING_STOP' ? 'bg-blue-500/20 text-blue-400' :
                                                t.closeReason === 'TIME_STOP' ? 'bg-purple-500/20 text-purple-400' :
                                                    'bg-white/10 text-white/40'
                                    }`}>{t.closeReason || '—'}</span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
});

RecentExitsCard.displayName = 'RecentExitsCard';

export default RecentExitsCard;
