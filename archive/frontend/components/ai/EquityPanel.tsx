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

    const target = 20000;
    const cb = -10000;
    const range = target - cb;
    const clamped = Math.max(cb, Math.min(target, sessionRealizedPnl));
    const pctZeroToSpan = ((clamped - cb) / range) * 100;
    const zeroPct = (Math.abs(cb) / range) * 100;

    return (
        <div className="pb-4 border-b border-white/5 space-y-2">
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <div className="text-[10px] uppercase tracking-widest text-white/40 mb-1">Symbol Equity <span className="normal-case tracking-normal opacity-60">(per symbol)</span></div>
                    <div className="text-sm font-bold font-mono text-white">
                        {'\u20B9'}{portfolio.equity.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                </div>
                <div className="text-right">
                    <div className="text-[10px] uppercase tracking-widest text-white/40 mb-1">Open PNL</div>
                    <div className={`text-sm font-bold font-mono ${openPnl > 0 ? 'text-green-400' : openPnl < 0 ? 'text-red-400' : 'text-white/60'}`}>
                        {openPnl > 0 ? '+' : ''}{'\u20B9'}{openPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </div>
                </div>
            </div>

            <div className="flex flex-col gap-1.5 mt-2">
                <div className="flex justify-between items-end text-[9px] px-1">
                    <span className="text-white/40">Circuit <span className="text-red-500/80 font-mono">{'\u20B9'}{cb.toLocaleString('en-IN')}</span></span>
                    <span className="text-white/50 font-mono">Session P&amp;L <span className={sessionRealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {sessionRealizedPnl >= 0 ? '+' : ''}{'\u20B9'}{sessionRealizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 0 })}
                    </span></span>
                    <span className="text-white/40">Target <span className="text-yellow-500/80 font-mono">{'\u20B9'}{target.toLocaleString('en-IN')}</span></span>
                </div>

                <div className="relative h-3 bg-white/10 rounded-full overflow-visible">
                    <div className="absolute inset-0 rounded-full overflow-hidden">
                        <div
                            className={`absolute top-0 bottom-0 left-0 rounded-full transition-all duration-500 ${
                                sessionRealizedPnl < cb * 0.85 ? 'bg-red-500' : sessionRealizedPnl > target * 0.85 ? 'bg-yellow-400' : 'bg-blue-400'
                            }`}
                            style={{ width: `${Math.max(0, Math.min(100, pctZeroToSpan))}%` }}
                        />
                    </div>
                    <div
                        className="absolute top-[-3px] w-0.5 h-[18px] bg-white/70 z-10 rounded-full shadow"
                        style={{ left: `calc(${zeroPct}% - 1px)` }}
                        title="Zero P&L"
                    />
                    <div
                        className="absolute top-0 bottom-0 w-1 z-20 rounded-full bg-white border border-black/40 shadow-md -translate-x-1/2"
                        style={{ left: `${Math.max(1, Math.min(99, pctZeroToSpan))}%` }}
                        title={`Session P&L: ${sessionRealizedPnl}`}
                    />
                </div>

                <div className="flex justify-between text-[8px] px-0.5 text-white/30 font-mono">
                    <span>Loss zone</span>
                    <span>Break-even</span>
                    <span>Profit zone</span>
                </div>

                <div className="flex justify-between text-[9px] px-1 mt-0.5">
                    <span className="text-white/30">Closed: <span className="text-white/60 font-mono">{portfolio.closedTrades.length}</span></span>
                </div>
            </div>

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
