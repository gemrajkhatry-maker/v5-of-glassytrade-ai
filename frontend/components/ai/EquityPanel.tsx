import React from 'react';
import { Portfolio } from '../../types';
import { EQUITY_PANEL } from '../../config';
import { Wallet, TrendingUp, ShieldAlert, Target } from 'lucide-react';

interface EquityPanelProps {
    portfolio: Portfolio;
    openPnl: number;
    riskState?: { dailyPnl?: number; tradesToday?: number; halted?: boolean; equity?: number } | null;
}

const fmt = (n: number) => n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
const fmtDecimal = (n: number) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Compact equity strip — capital, open P&L, session progress bar. */
const EquityPanel = React.memo<EquityPanelProps>(({ portfolio, openPnl, riskState }) => {
    const totalPartialPnl = portfolio.positions.reduce((acc, p) => acc + (p.partialRealizedPnl || 0), 0);
    const closedTradesSum = portfolio.closedTrades.reduce((sum, t) => sum + (t.pnl || 0), 0);
    const sessionPnl = (riskState?.dailyPnl !== undefined && riskState?.dailyPnl !== 0)
        ? riskState.dailyPnl
        : closedTradesSum;
    const closedCount = (riskState?.tradesToday !== undefined && riskState?.tradesToday > 0)
        ? riskState.tradesToday
        : portfolio.closedTrades.length;
    const currentEquity = (riskState?.equity !== undefined && riskState?.equity > 0)
        ? riskState.equity
        : portfolio.equity;

    const target = EQUITY_PANEL.dailyTarget;
    const cb     = EQUITY_PANEL.circuitBreaker;
    const range  = target - cb;
    const clamped = Math.max(cb, Math.min(target, sessionPnl));
    const progressPct = ((clamped - cb) / range) * 100;
    const zeroLinePct = (Math.abs(cb) / range) * 100;

    const pnlColor = (v: number) =>
        v > 0 ? 'text-emerald-400' : v < 0 ? 'text-rose-400' : 'text-slate-400';

    return (
        <div className="space-y-2">
            {/* ── Capital + Open P&L in a single compact row ── */}
            <div className="flex items-center gap-2">
                {/* Capital */}
                <div className="flex-1 flex items-center gap-2 px-2.5 py-2 rounded-lg bg-white/4 border border-white/6">
                    <Wallet className="w-3 h-3 text-slate-500 shrink-0" />
                    <div className="min-w-0">
                        <div className="text-[7.5px] uppercase tracking-widest text-slate-500">Capital</div>
                        <div className="text-[11px] font-black font-mono text-slate-100 leading-none">
                            ₹{fmtDecimal(currentEquity)}
                        </div>
                    </div>
                </div>

                {/* Open P&L */}
                <div className={`flex-1 flex items-center gap-2 px-2.5 py-2 rounded-lg border transition-colors ${
                    openPnl > 0 ? 'bg-emerald-950/30 border-emerald-500/25' :
                    openPnl < 0 ? 'bg-rose-950/30 border-rose-500/25' :
                    'bg-white/4 border-white/6'
                }`}>
                    <TrendingUp className={`w-3 h-3 shrink-0 ${pnlColor(openPnl)}`} />
                    <div className="min-w-0">
                        <div className="flex items-center gap-1">
                            <span className="text-[7.5px] uppercase tracking-widest text-slate-500">Open P&L</span>
                            {portfolio.positions.length > 0 && (
                                <span className="text-[7px] font-mono font-bold text-emerald-400 bg-emerald-500/10 px-1 rounded">
                                    {portfolio.positions.length}×
                                </span>
                            )}
                        </div>
                        <div className={`text-[11px] font-black font-mono leading-none ${pnlColor(openPnl)}`}>
                            {openPnl > 0 ? '+' : ''}₹{fmtDecimal(openPnl)}
                        </div>
                    </div>
                </div>
            </div>

            {/* ── Session P&L progress bar ── */}
            <div className="px-2.5 py-2 rounded-lg bg-black/30 border border-white/5 space-y-1.5">
                <div className="flex items-center justify-between text-[8px] font-mono">
                    <span className="flex items-center gap-1 text-rose-400/70">
                        <ShieldAlert className="w-2.5 h-2.5" />
                        CB ₹{fmt(cb)}
                    </span>
                    <span className={`font-bold text-[9px] ${pnlColor(sessionPnl)}`}>
                        {sessionPnl > 0 ? '+' : ''}₹{fmt(sessionPnl)}
                        <span className="text-slate-600 font-normal ml-1 text-[7.5px]">session</span>
                    </span>
                    <span className="flex items-center gap-1 text-amber-400/70">
                        <Target className="w-2.5 h-2.5" />
                        ₹{fmt(target)}
                    </span>
                </div>

                {/* Range meter */}
                <div className="relative h-1 bg-white/6 rounded-full overflow-hidden">
                    <div
                        className={`h-full rounded-full transition-all duration-500 ${
                            sessionPnl < 0 ? 'bg-rose-500' : sessionPnl > 0 ? 'bg-emerald-400' : 'bg-slate-600'
                        }`}
                        style={{ width: `${Math.max(0, Math.min(100, progressPct))}%` }}
                    />
                    <div
                        className="absolute top-0 bottom-0 w-px bg-white/30"
                        style={{ left: `${zeroLinePct}%` }}
                        title="Breakeven (₹0)"
                    />
                </div>

                <div className="flex items-center justify-between text-[7px] font-mono text-slate-600">
                    <span>−2% CB</span>
                    <span>{closedCount} closed</span>
                    <span>+2% goal</span>
                </div>
            </div>

            {/* Partial TP toast */}
            {totalPartialPnl !== 0 && (
                <div className="px-2.5 py-1.5 rounded-lg bg-amber-500/8 border border-amber-500/20 flex items-center justify-between">
                    <span className="text-[8px] uppercase tracking-wider text-amber-300/80 font-semibold">Partial TP booked</span>
                    <span className="text-[9px] font-mono font-bold text-amber-400">
                        +₹{fmtDecimal(totalPartialPnl)}
                    </span>
                </div>
            )}
        </div>
    );
});

EquityPanel.displayName = 'EquityPanel';
export default EquityPanel;
