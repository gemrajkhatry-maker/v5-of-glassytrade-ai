import React, { useState, useCallback, useMemo } from 'react';
import GlassPanel from './GlassPanel';
import { InstrumentState } from '../types';
import { TrendingUp, TrendingDown, Search, BarChart3, History, Radio, Filter } from 'lucide-react';
import { shortSymbol } from '../utils/symbol';

interface MarketSidebarProps {
    instruments: Record<string, InstrumentState>;
    activeSymbol: string;
    onSelect: (symbol: string) => void;
}

/** Sort key: higher = more urgent for entries */
function timingRank(timing: string | undefined): number {
    if (timing === 'ENTER_NOW') return 3;
    if (timing === 'MONITOR' || timing === 'WAIT') return 2;
    if (timing === 'SKIP') return 1;
    return 0;
}

/** Memoized symbol card to avoid re-rendering all cards when only one changes. */
interface SymbolCardProps {
    sym: string;
    inst: InstrumentState;
    isActive: boolean;
    onSelect: (symbol: string) => void;
}

const SymbolCard = React.memo<SymbolCardProps>(({ sym, inst, isActive, onSelect }) => {
    const lastCandle = inst.data[inst.data.length - 1];
    const prevCandle = inst.data[inst.data.length - 2];

    const price = inst.ltp ?? (lastCandle?.close || 0);
    const prevPrice = prevCandle?.close || price;
    const percentChange = price > 0 ? ((price - prevPrice) / prevPrice) * 100 : 0;
    const isUp = percentChange >= 0;
    const hasData = inst.data.length > 0;
    const { name, tag } = shortSymbol(sym);

    // --- Live PnL from open positions ---
    const openPositions = inst.portfolio?.positions?.filter(p => p.status === 'OPEN') || [];
    const hasOpenPosition = openPositions.length > 0;
    const totalPnl = openPositions.reduce((sum, p) => sum + (p.pnl || 0), 0);
    const totalSize = openPositions.reduce((sum, p) => sum + (p.size || 0), 0);

    const isDead = inst.genAIAnalysis?.rationale?.includes('DEAD') || inst.genAIAnalysis?.rawOutput?.includes('QUANT_DEAD_MARKET');
    const hasAnalysis = inst.agentDecision !== null && inst.amtAnalysis !== null;
    const prob = inst.agentDecision?.probability ?? 0;
    const timing = inst.agentDecision?.timing ?? 'SKIP';
    const mode = inst.amtAnalysis?.marketState ?? 'BALANCED';
    const modeAbbr = (mode || 'BAL').substring(0, 3).toUpperCase();
    const actionLabel = hasAnalysis
        ? (timing === 'ENTER_NOW' ? 'ENTER' : timing === 'MONITOR' ? 'WAIT' : timing === 'SKIP' ? 'SKIP' : (timing || '—').slice(0, 6))
        : '...';

    return (
        <button
            role="listitem"
            aria-selected={isActive}
            onClick={() => onSelect(sym)}
            className={`
                w-full px-2 py-1.5 rounded flex items-center gap-0 group transition-all duration-200 text-left border-l-2
                ${hasOpenPosition
                    ? isActive
                        ? 'bg-green-500/10 border-l-emerald-500 bg-gradient-to-r from-green-500/5 to-transparent'
                        : 'bg-green-500/5 border-l-emerald-500/50 hover:bg-green-500/10'
                    : isActive
                        ? 'bg-purple-500/10 border-l-purple-500 bg-gradient-to-r from-purple-500/5 to-transparent'
                        : 'bg-white/[0.02] hover:bg-white/[0.05] border-l-transparent'}
                ${isDead ? 'opacity-40 saturate-0' : ''}
                border-b border-white/[0.03]
            `}
        >
            {/* Symbol & Tag (24%) */}
            <div className="flex flex-col w-[24%] overflow-hidden pr-2">
                <div className="flex items-center gap-1.5 min-h-[14px]">
                    {hasOpenPosition ? (
                        <span className="text-[9px] font-bold text-emerald-400 animate-pulse">●</span>
                    ) : hasData ? (
                        <Radio size={8} className="text-emerald-400" />
                    ) : (
                        <span className="w-2 h-2 rounded-full bg-white/15 animate-pulse shrink-0" />
                    )}
                    {!hasData && !hasOpenPosition ? (
                        <span className="h-2.5 flex-1 max-w-[80%] rounded bg-white/10 animate-pulse" />
                    ) : (
                        <span className="font-bold text-[10px] text-white/90 truncate">
                            {name}
                        </span>
                    )}
                </div>
                <span className="text-[8px] text-white/30 font-mono ml-3">{hasData || hasOpenPosition ? tag : '\u00A0'}</span>
            </div>

            {/* Mode + action merged (28%) */}
            <div className="w-[28%] min-w-0 flex items-center">
                {hasOpenPosition ? (
                    <span className="text-[9px] font-bold text-emerald-400 font-mono truncate">
                        OPEN · {totalSize.toFixed(0)}L
                    </span>
                ) : !hasData ? (
                    <span className="h-4 w-full max-w-[5.5rem] rounded bg-white/10 animate-pulse" />
                ) : (
                    <span
                        className={`inline-flex items-center gap-1 text-[8px] font-mono px-1 py-0.5 rounded border max-w-full ${
                            mode === 'BALANCED' ? 'text-amber-500 bg-amber-500/10 border-amber-500/20' :
                            mode === 'PROBING' ? 'text-blue-400 bg-blue-500/10 border-blue-500/20' :
                            mode === 'TRENDING' ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' :
                            mode === 'BREAKING' ? 'text-red-400 bg-red-500/10 border-red-500/20' :
                            'text-white/40 bg-white/5 border-white/10'
                        }`}
                    >
                        <span className="shrink-0">{modeAbbr}</span>
                        <span className="text-white/25">·</span>
                        <span className={`shrink-0 inline-flex items-center gap-0.5 font-bold ${
                            timing === 'ENTER_NOW' ? 'text-emerald-400' : timing === 'SKIP' ? 'text-red-400' : 'text-yellow-400'
                        }`}>
                            <span className={`w-1 h-1 rounded-full shrink-0 ${timing === 'ENTER_NOW' ? 'bg-emerald-400 animate-pulse' : timing === 'SKIP' ? 'bg-red-400' : 'bg-yellow-400'}`} />
                            {actionLabel}
                        </span>
                    </span>
                )}
            </div>

            {/* Probability & Bar (20%) */}
            <div className="w-[20%] flex flex-col gap-0.5 pr-2">
                {hasOpenPosition ? (
                    <span className={`text-[10px] font-mono font-bold ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(0)}
                    </span>
                ) : !hasData ? (
                    <>
                        <span className="h-2 w-8 rounded bg-white/10 animate-pulse" />
                        <div className="w-full h-0.5 bg-white/10 rounded-full overflow-hidden">
                            <div className="h-full w-1/3 bg-white/10 animate-pulse" />
                        </div>
                    </>
                ) : inst.agentDecision?.probability !== undefined ? (
                    <>
                        <span className={`text-[9px] font-mono font-bold ${inst.agentDecision.probability >= 0.6 ? 'text-emerald-400' : inst.agentDecision.probability >= 0.5 ? 'text-amber-400' : 'text-red-400'}`}>
                            {Math.round(inst.agentDecision.probability * 100)}%
                        </span>
                        <div className="w-full h-0.5 bg-white/10 rounded-full overflow-hidden">
                            <div className="h-full transition-all duration-500" style={{ width: `${inst.agentDecision.probability * 100}%`, backgroundColor: inst.agentDecision.probability >= 0.6 ? '#34d399' : inst.agentDecision.probability >= 0.5 ? '#fbbf24' : '#f87171' }} />
                        </div>
                    </>
                ) : (
                    <>
                        <span className="h-2 w-8 rounded bg-white/10 animate-pulse" />
                        <div className="w-full h-0.5 bg-white/10 rounded-full overflow-hidden">
                            <div className="h-full w-1/3 bg-white/10 animate-pulse" />
                        </div>
                    </>
                )}
            </div>

            {/* LTP / DEAD (16%) */}
            <div className="w-[16%] flex flex-col items-end pr-2">
                {isDead ? (
                    <span className="text-[7px] font-mono font-bold text-red-400/70 border border-red-500/20 px-1 rounded animate-pulse">
                        DEAD
                    </span>
                ) : !hasData && !hasOpenPosition ? (
                    <span className="h-2.5 w-10 rounded bg-white/10 animate-pulse" />
                ) : (
                    <span className="font-mono text-[10px] text-white/70 font-bold">
                        {price > 0 ? price.toFixed(1) : '—'}
                    </span>
                )}
            </div>

            {/* Change% or Live PnL indicator (12%) */}
            <div className="w-[12%] text-right">
                {hasOpenPosition ? (
                    <span className={`text-[8px] font-mono ${totalPnl >= 0 ? 'text-emerald-400/80' : 'text-red-400/80'}`}>
                        {totalPnl >= 0 ? '▲' : '▼'}
                    </span>
                ) : !hasData ? (
                    <span className="inline-block h-2 w-8 rounded bg-white/10 animate-pulse ml-auto" />
                ) : (
                    <span className={`text-[9px] font-mono whitespace-nowrap ${isUp ? 'text-emerald-400/80' : 'text-red-400/80'}`}>
                        {isUp ? '+' : ''}{percentChange.toFixed(1)}%
                    </span>
                )}
            </div>
        </button>
    );
});

SymbolCard.displayName = 'SymbolCard';

const MarketSidebar: React.FC<MarketSidebarProps> = ({ instruments, activeSymbol, onSelect }) => {
    const [filter, setFilter] = useState('');
    const [modeFilter, setModeFilter] = useState('ALL');
    const [actionFilter, setActionFilter] = useState('ALL');
    const [sortBy, setSortBy] = useState<'ACTION' | 'PROB'>('PROB');

    const symbols = useMemo(() => Object.keys(instruments).sort(), [instruments]);
    const filtered = useMemo(() => {
        let f = symbols;
        
        // Apply text filter
        if (filter) f = f.filter(s => s.toLowerCase().includes(filter.toLowerCase()));
        
        // Apply Mode filter
        if (modeFilter !== 'ALL') f = f.filter(s => instruments[s].amtAnalysis?.marketState?.includes(modeFilter) || (modeFilter === 'DEAD' && instruments[s].genAIAnalysis?.rationale?.includes('DEAD')));
        
        // Apply Action filter
        if (actionFilter !== 'ALL') f = f.filter(s => instruments[s].agentDecision?.timing === actionFilter);

        // Sort: Default to "Opportunity First" (ENTER_NOW > MONITOR > SKIP > DEAD)
        return f.sort((a, b) => {
            const instA = instruments[a];
            const instB = instruments[b];
            
            const isDeadA = instA.genAIAnalysis?.rationale?.includes('DEAD') || instA.genAIAnalysis?.rawOutput?.includes('QUANT_DEAD_MARKET');
            const isDeadB = instB.genAIAnalysis?.rationale?.includes('DEAD') || instB.genAIAnalysis?.rawOutput?.includes('QUANT_DEAD_MARKET');

            // 0. Dead or no-analysis symbols always at the bottom
            const noAnalysisA = !instA.agentDecision || !instA.amtAnalysis;
            const noAnalysisB = !instB.agentDecision || !instB.amtAnalysis;
            if (noAnalysisA !== noAnalysisB) return noAnalysisA ? 1 : -1;
            if (isDeadA !== isDeadB) return isDeadA ? 1 : -1;

            const pA = instA.agentDecision?.probability || 0;
            const pB = instB.agentDecision?.probability || 0;
            
            if (sortBy === 'ACTION') {
                const rankA = timingRank(instA.agentDecision?.timing);
                const rankB = timingRank(instB.agentDecision?.timing);
                if (rankA !== rankB) return rankB - rankA;
                return pB - pA;
            }
            // Prob primary; full timing rank as tie-breaker
            if (Math.abs(pA - pB) > 0.01) return pB - pA;
            return timingRank(instB.agentDecision?.timing) - timingRank(instA.agentDecision?.timing);
        });
    }, [symbols, filter, modeFilter, actionFilter, instruments, sortBy]);

    // Filter trades for the ACTIVE symbol only
    const recentTrades = React.useMemo(() => {
        const activeInstrument = instruments[activeSymbol];
        if (!activeInstrument) return [];

        return [...activeInstrument.portfolio.closedTrades]
            .sort((a, b) => new Date(b.exitTime || 0).getTime() - new Date(a.exitTime || 0).getTime());
    }, [instruments, activeSymbol]);

    return (
        <GlassPanel className="h-full w-[360px] flex flex-col border-r border-white/10 rounded-none rounded-r-2xl bg-[#0f172a] shadow-2xl z-50">

            {/* --- MARKET SCANNER (Top Section) --- */}
            <div className="flex-1 flex flex-col min-h-0">
                {/* Custom Sticky Header */}
                <div className="p-3 border-b border-white/10 bg-[#0f172a] sticky top-0 z-10 shrink-0">
                    <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                            <BarChart3 className="text-purple-400" size={18} />
                            <h2 className="font-bold text-[13px] tracking-widest text-white/90">MARKET SCANNER</h2>
                        </div>
                        <span className="text-[10px] text-white/30 bg-black/20 px-2 py-0.5 rounded-full font-mono flex items-center gap-1">
                            <span className="w-1 h-1 rounded-full bg-white/30"></span> {filtered.length} of {symbols.length}
                        </span>
                    </div>

                    <div className="flex flex-col gap-2">
                        {/* Text Search */}
                        <div className="relative">
                            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30" size={14} aria-hidden="true" />
                            <input
                                type="text"
                                placeholder="Filter symbols..."
                                value={filter}
                                onChange={e => setFilter(e.target.value)}
                                aria-label="Filter symbols by name"
                                className="w-full bg-black/30 border border-white/10 rounded py-1.5 pl-8 pr-3 text-xs text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50"
                            />
                        </div>
                        
                        {/* Dropdown Filters */}
                        <div className="flex gap-2">
                            <div className="relative flex-1">
                                <Filter className="absolute left-2 top-1/2 -translate-y-1/2 text-white/30" size={10} aria-hidden="true" />
                                <select 
                                    value={modeFilter} onChange={e => setModeFilter(e.target.value)}
                                    aria-label="Filter by market mode"
                                    className="w-full bg-black/30 border border-white/10 rounded py-1 pl-6 pr-2 text-[10px] text-white/70 appearance-none outline-none focus:border-white/20 cursor-pointer"
                                >
                                    <option value="ALL">All Modes</option>
                                    <option value="BALANCED">Balanced</option>
                                    <option value="IMBALANCED">Imbalanced</option>
                                    <option value="DEAD">Dead Market</option>
                                </select>
                            </div>
                            <div className="relative flex-1">
                                <Filter className="absolute left-2 top-1/2 -translate-y-1/2 text-white/30" size={10} aria-hidden="true" />
                                <select 
                                    value={actionFilter} onChange={e => setActionFilter(e.target.value)}
                                    aria-label="Filter by action type"
                                    className="w-full bg-black/30 border border-white/10 rounded py-1 pl-6 pr-2 text-[10px] text-white/70 appearance-none outline-none focus:border-white/20 cursor-pointer"
                                >
                                    <option value="ALL">All Actions</option>
                                    <option value="ENTER_NOW">Enter Now</option>
                                    <option value="SKIP">Skip</option>
                                    <option value="MONITOR">Monitor/Wait</option>
                                </select>
                            </div>
                        </div>
                        
                        {/* Column Header */}
                        <div className="flex w-full text-[9px] text-white/30 font-mono mt-3 px-2 pb-1 border-b border-white/5 uppercase tracking-tighter" role="row">
                            <div className="w-[24%]">Symbol</div>
                            <button
                                className="w-[28%] text-left hover:text-white/60 focus:outline-none focus:text-white/60"
                                onClick={() => setSortBy('ACTION')}
                                aria-label="Sort by action priority"
                                title="Sort by action priority"
                            >
                                Status {sortBy === 'ACTION' ? '↓' : '↕'}
                            </button>
                            <button
                                className="w-[20%] text-left hover:text-white/60 focus:outline-none focus:text-white/60"
                                onClick={() => setSortBy('PROB')}
                                aria-label="Sort by probability"
                                title="Sort by probability"
                            >
                                Prob% {sortBy === 'PROB' ? '↓' : '↕'}
                            </button>
                            <div className="w-[16%] text-right pr-2">LTP</div>
                            <div className="w-[12%] text-right">Chg</div>
                        </div>
                    </div>
                </div>

                {/* Symbol List */}
                <div className="flex-1 overflow-y-auto p-2 space-y-1" role="list" aria-label="Market scanner symbols" aria-live="polite">
                    {filtered.length === 0 && (
                        <div className="text-center text-[10px] text-white/20 py-8">
                            {filter ? 'No matching symbols' : 'Waiting for scanner...'}
                        </div>
                    )}
                    {filtered.map(sym => (
                        <SymbolCard
                            key={sym}
                            sym={sym}
                            inst={instruments[sym]}
                            isActive={sym === activeSymbol}
                            onSelect={onSelect}
                        />
                    ))}
                </div>
            </div>

            {/* --- TRADE HISTORY (Bottom Section) --- */}
            <div className="h-[250px] border-t border-white/10 flex flex-col bg-black/20 shrink-0">
                <div className="p-3 border-b border-white/5 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <History className="text-blue-400" size={16} />
                        <h3 className="font-bold text-xs tracking-widest text-white/80">
                            {activeSymbol ? `${shortSymbol(activeSymbol).name} TRADES` : 'RECENT TRADES'}
                        </h3>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {recentTrades.length === 0 ? (
                        <div className="h-full flex flex-col items-center justify-center text-white/20">
                            <History size={24} className="mb-2 opacity-50" />
                            <span className="text-[10px] italic">No closed trades for {shortSymbol(activeSymbol).name}</span>
                        </div>
                    ) : (
                        recentTrades.map(trade => (
                            <div key={trade.id} className="p-2 rounded-lg bg-white/5 border border-white/5 text-xs hover:bg-white/10 transition-colors space-y-1">
                                <div className="flex justify-between items-center">
                                    <div className="flex items-center gap-1.5">
                                        <span className="font-bold text-white/90">{shortSymbol(trade.symbol).name}</span>
                                        <span className={`text-[9px] px-1 rounded ${trade.side === 'LONG' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                                            {trade.side}
                                        </span>
                                        {trade.size > 0 && <span className="text-[9px] text-white/40">x{(trade.originalSize ?? trade.size).toFixed(0)}</span>}
                                    </div>
                                    <div className={`font-mono font-bold ${trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                        {trade.pnl >= 0 ? '+' : ''}{trade.pnl.toFixed(2)}
                                    </div>
                                </div>
                                <div className="flex justify-between text-[9px] text-white/40 font-mono">
                                    <span>Entry: {trade.entryPrice?.toFixed(2)}</span>
                                    <span>Exit: {trade.exitPrice?.toFixed(2) || '—'}</span>
                                </div>
                                <div className="flex justify-between text-[9px] text-white/30">
                                    <span>{new Date(trade.entryTime || '').toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' })} → {new Date(trade.exitTime || '').toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' })}</span>
                                </div>
                                <div className="flex justify-between text-[9px]">
                                    <span className="text-white/30">{trade.source}</span>
                                    {trade.closeReason && <span className="text-amber-400/70">{trade.closeReason}</span>}
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Footer Status */}
            <div className="p-3 border-t border-white/10 bg-black/40 text-[10px] text-white/30 flex justify-between items-center shrink-0">
                <div className="flex items-center gap-1.5">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    <span>LIVE FEED</span>
                </div>
                <span>{filtered.length} VISIBLE</span>
            </div>
        </GlassPanel>
    );
};

export default MarketSidebar;
