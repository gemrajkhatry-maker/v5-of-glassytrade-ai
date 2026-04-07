import React from 'react';
import { Portfolio } from '../../types';

interface EquityPanelProps {
    portfolio: Portfolio;
    openPnl: number;
}

/** Displays equity, open PnL, session P&L, and partial TP info. */
const EquityPanel = React.memo<EquityPanelProps>(({ portfolio, openPnl }) => {
    const totalPartialPnl = portfolio.positions.reduce((acc, p) => acc + (p.partialRealizedPnl || 0), 0);
    const sessionRealizedPnl = portfolio.closedTrades.reduce(
        (sum, t) => sum + (t.pnl || 0), 0
    );

    return (
        <div className="pb-4 border-b border-white/5 space-y-2">
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <div className="text-[10px] uppercase tracking-widest text-white/40 mb-1">Equity</div>
                    <div className="text-sm font-bold font-mono text-white">
                        {'\u20B9'}{portfolio.equity.toLocaleString('en-IN')}
                    </div>
                </div>
                <div className="text-right">
                    <div className="text-[10px] uppercase tracking-widest text-white/40 mb-1">Open PNL</div>
                    <div className={`text-sm font-bold font-mono ${openPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {openPnl >= 0 ? '+' : ''}{'\u20B9'}{openPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </div>
                </div>
            </div>
            {/* Session P&L breakdown / Progress Bar */}
            <div className="flex flex-col gap-1.5 mt-2">
                <div className="flex justify-between items-end text-[9px] px-1">
                    <span className="text-white/40">Daily Target: <span className="text-yellow-500/80 font-mono">₹20,000</span></span>
                    <span className="text-white/40">Circuit Breaker: <span className="text-red-500/80 font-mono">-₹10,000</span></span>
                </div>
                {(() => {
                    const target = 20000;
                    const cb = -10000;
                    const range = target - cb;
                    const current = Math.max(cb, Math.min(target, sessionRealizedPnl));
                    const percentage = ((current - cb) / range) * 100;
                    const isNearCb = sessionRealizedPnl < (cb * 0.8); // 80% to CB
                    const isNearTarget = sessionRealizedPnl > (target * 0.8); // 80% to Target
                    const barColor = isNearCb ? 'bg-red-500' : isNearTarget ? 'bg-yellow-400' : 'bg-blue-400';
                    return (
                        <div className="h-1.5 bg-white/10 rounded-full relative overflow-hidden">
                            {/* Zero line marker */}
                            <div className="absolute top-0 bottom-0 w-px bg-white/30 z-10" style={{ left: `${(Math.abs(cb) / range) * 100}%` }}></div>
                            <div className={`h-full ${barColor} transition-all duration-500`} style={{ width: `${percentage}%` }}></div>
                        </div>
                    );
                })()}
                <div className="flex justify-between text-[9px] px-1 mt-0.5">
                    <span className="text-white/30">Session P&L: <span className={`font-mono font-bold ${sessionRealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {sessionRealizedPnl >= 0 ? '+' : ''}{'\u20B9'}{sessionRealizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </span></span>
                    <span className="text-white/30">Closed: <span className="text-white/60 font-mono">{portfolio.closedTrades.length}</span></span>
                </div>
            </div>
            {/* Partial exit info for open positions */}
            {totalPartialPnl !== 0 && (
                <div className="px-2 py-1.5 rounded bg-orange-500/10 border border-orange-500/20 flex items-center justify-between">
                    <span className="text-[9px] text-orange-300/80 uppercase tracking-wider">Partial TP Booked</span>
                    <span className={`text-[10px] font-mono font-bold ${totalPartialPnl >= 0 ? 'text-orange-400' : 'text-red-400'}`}>
                        +{'\u20B9'}{totalPartialPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </span>
                </div>
            )}
        </div>
    );
});

EquityPanel.displayName = 'EquityPanel';

export default EquityPanel;
