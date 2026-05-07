
import React, { useState, useCallback, useMemo } from 'react';
import GlassPanel from './GlassPanel';
import { InstrumentState } from '../types';
import { TrendingUp, TrendingDown, Search, BarChart3, History, Radio, Filter } from 'lucide-react';

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

/** Extract a short display name from Dhan symbol like "NIFTY 27 FEB 25500 CALL" -> "NIFTY 25500 CE" */
function shortSymbol(sym: string): { name: string; tag: string } {
    const parts = sym.split(' ');
    // Options: "NIFTY 27 FEB 25500 CALL" or "CRUDEOIL 17 MAR 5900 PUT"
    if (parts.length >= 4) {
        const underlying = parts[0];
        const strike = parts[parts.length - 2];
        const optType = parts[parts.length - 1];
        const tag = optType === 'CALL' ? 'CE' : optType === 'PUT' ? 'PE' : optType;
        return { name: `${underlying} ${strike}`, tag };
    }
    // Fallback
    return { name: sym.replace('USDT', ''), tag: '' };
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
    const unsafeToTrade = Boolean(inst.runtimeSafety?.unsafeToTrade);
    const prob = inst.agentDecision?.probability || 0;
    const timing = inst.agentDecision?.timing || 'SKIP';
    const mode = inst.amtAnalysis?.marketState || 'BALANCED';
    const modeAbbr = (mode || 'BAL').substring(0, 3).toUpperCase();
    const actionLabel =
        unsafeToTrade ? 'UNSAFE' :
        timing === 'ENTER_NOW' ? 'ENTER' : timing === 'MONITOR' ? 'WAIT' : timing === 'SKIP' ? 'SKIP' : (timing || '—').slice(0, 6);

    return (
        <button
            onClick={() => onSelect(sym)}
            className={`
                w-full px-2 py-1.5 rounded-sm flex items-center gap-0 group transition-all duration-200 text-left border-l-2
                ${hasOpenPosition
                    ? isActive
                        ? 'bg-glassy-bull-primary/10 border-l-glassy-bull-primary'
                        : 'bg-glassy-bull-primary/5 border-l-glassy-bull-primary/50 hover:bg-glassy-bull-primary/10'
                    : isActive
                        ? 'bg-glassy-bg-active border-l-glassy-ai-primary'
                        : 'bg-transparent hover:bg-glassy-bg-hover border-l-transparent'}
                ${isDead ? 'opacity-40 saturate-0' : ''}
                border-b border-glassy-border-subtle
            `}
        >
            {/* Symbol & Tag (24%) */}
            <div className="flex flex-col w-[24%] overflow-hidden pr-2">
                <div className="flex items-center gap-1.5 min-h-[14px]">
                    {hasOpenPosition ? (
                        <span className="text-[9px] font-bold text-glassy-bull-primary animate-pulse">●</span>
                    ) : hasData ? (
                        <Radio size={8} className="text-glassy-bull-primary" />
                    ) : (
                        <span className="w-2 h-2 rounded-full bg-glassy-text-disabled/30 animate-pulse shrink-0" />
                    )}
                    {!hasData && !hasOpenPosition ? (
                        <span className="h-2.5 flex-1 max-w-[80%] rounded bg-glassy-text-disabled/20 animate-pulse" />
                    ) : (
                        <span className="font-bold text-[10px] text-glassy-text-primary truncate">
                            {name}
                        </span>
                    )}
                </div>
                <span className="text-[8px] text-glassy-text-tertiary font-mono ml-3">{hasData || hasOpenPosition ? tag : '\u00A0'}</span>
            </div>

            {/* Mode + action merged (28%) */}
            <div className="w-[28%] min-w-0 flex items-center">
                {hasOpenPosition ? (
                    <span className="text-[9px] font-bold text-glassy-bull-primary font-mono truncate">
                        OPEN · {totalSize.toFixed(0)}L
                    </span>
                ) : !hasData ? (
                    <span className="h-4 w-full max-w-[5.5rem] rounded bg-glassy-text-disabled/20 animate-pulse" />
                ) : (
                    <span
                        className={`inline-flex items-center gap-1 text-[8px] font-mono px-1 py-0.5 rounded-sm border max-w-full ${
                            mode === 'BALANCED' ? 'text-glassy-neutral-warm bg-glassy-neutral-warm/10 border-glassy-neutral-warm/20' :
                            mode === 'PROBING' ? 'text-glassy-neutral-cool bg-glassy-neutral-cool/10 border-glassy-neutral-cool/20' :
                            mode === 'TRENDING' ? 'text-glassy-bull-primary bg-glassy-bull-primary/10 border-glassy-bull-primary/20' :
                            mode === 'BREAKING' ? 'text-glassy-bear-primary bg-glassy-bear-primary/10 border-glassy-bear-primary/20' :
                            'text-glassy-text-disabled bg-glassy-bg-elevated border-glassy-border-subtle'
                        }`}
                    >
                        <span className="shrink-0">{modeAbbr}</span>
                        <span className="text-glassy-text-tertiary">·</span>
                        <span className={`shrink-0 inline-flex items-center gap-0.5 font-bold ${
                            unsafeToTrade ? 'text-glassy-bear-primary' : timing === 'ENTER_NOW' ? 'text-glassy-bull-primary' : timing === 'SKIP' ? 'text-glassy-bear-primary' : 'text-glassy-warning'
                        }`}>
                            <span className={`w-1 h-1 rounded-full shrink-0 ${unsafeToTrade ? 'bg-glassy-bear-primary animate-pulse' : timing === 'ENTER_NOW' ? 'bg-glassy-bull-primary animate-pulse' : timing === 'SKIP' ? 'bg-glassy-bear-primary' : 'bg-glassy-warning'}`} />
                            {actionLabel}
                        </span>
                    </span>
                )}
            </div>

            {/* Probability & Bar (20%) */}
            <div className="w-[20%] flex flex-col gap-0.5 pr-2">
                {hasOpenPosition ? (
                    <span className={`text-[10px] font-mono font-bold ${totalPnl >= 0 ? 'text-glassy-bull-primary' : 'text-glassy-bear-primary'}`}>
                        {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(0)}
                    </span>
                ) : !hasData ? (
                    <>
                        <span className="h-2 w-8 rounded bg-glassy-text-disabled/20 animate-pulse" />
                        <div className="w-full h-0.5 bg-glassy-text-disabled/20 rounded-full overflow-hidden">
                            <div className="h-full w-1/3 bg-glassy-text-disabled/20 animate-pulse" />
                        </div>
                    </>
                ) : (
                    <>
                        <span className={`text-[9px] font-mono font-bold ${prob >= 0.6 ? 'text-glassy-bull-primary' : prob >= 0.5 ? 'text-glassy-warning' : 'text-glassy-bear-primary'}`}>
                            {Math.round(prob * 100)}%
                        </span>
                        <div className="w-full h-0.5 bg-glassy-text-disabled/20 rounded-full overflow-hidden">
                            <div className="h-full transition-all duration-500" style={{ width: `${prob * 100}%`, backgroundColor: prob >= 0.6 ? '#00c896' : prob >= 0.5 ? '#ffa94d' : '#ff4757' }} />
                        </div>
                    </>
                )}
            </div>

            {/* LTP / DEAD (16%) */}
            <div className="w-[16%] flex flex-col items-end pr-2">
                {isDead ? (
                    <span className="text-[7px] font-mono font-bold text-glassy-bear-primary/70 border border-glassy-bear-primary/20 px-1 rounded-sm animate-pulse">
                        DEAD
                    </span>
                ) : !hasData && !hasOpenPosition ? (
                    <span className="h-2.5 w-10 rounded bg-glassy-text-disabled/20 animate-pulse" />
                ) : (
                    <span className="font-mono text-[10px] text-glassy-text-secondary font-bold">
                        {price > 0 ? price.toFixed(1) : '—'}
                    </span>
                )}
            </div>

            {/* Change% or Live PnL indicator (12%) */}
            <div className="w-[12%] text-right">
                {hasOpenPosition ? (
                    <span className={`text-[8px] font-mono ${totalPnl >= 0 ? 'text-glassy-bull-primary/80' : 'text-glassy-bear-primary/80'}`}>
                        {totalPnl >= 0 ? '▲' : '▼'}
                    </span>
                ) : !hasData ? (
                    <span className="inline-block h-2 w-8 rounded bg-glassy-text-disabled/20 animate-pulse ml-auto" />
                ) : (
                    <span className={`text-[9px] font-mono whitespace-nowrap ${isUp ? 'text-glassy-bull-primary/80' : 'text-glassy-bear-primary/80'}`}>
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

    const symbols = Object.keys(instruments);
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

            // 0. Dead markets always at the bottom
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
        <GlassPanel className="h-full w-[360px] flex flex-col border-r border-glassy-border-default rounded-none rounded-r-md bg-glassy-bg-secondary shadow-xl z-50">

            {/* --- MARKET SCANNER (Top Section) --- */}
            <div className="flex-1 flex flex-col min-h-0">
                {/* Custom Sticky Header */}
                <div className="p-3 border-b border-glassy-border-default bg-glassy-bg-secondary sticky top-0 z-10 shrink-0">
                    <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                            <BarChart3 className="text-glassy-ai-primary" size={18} />
                            <h2 className="font-bold text-[11px] tracking-wider text-glassy-text-primary uppercase">Market Scanner</h2>
                        </div>
                        <span className="text-[9px] text-glassy-text-tertiary bg-glassy-bg-elevated px-2 py-0.5 rounded-sm font-mono flex items-center gap-1">
                            <span className="w-1 h-1 rounded-full bg-glassy-text-tertiary/50"></span> {filtered.length} of {symbols.length}
                        </span>
                    </div>

                    <div className="flex flex-col gap-2">
                        {/* Text Search */}
                        <div className="relative">
                            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-glassy-text-tertiary" size={14} />
                            <input
                                type="text"
                                placeholder="Filter symbols..."
                                value={filter}
                                onChange={e => setFilter(e.target.value)}
                                className="w-full bg-glassy-bg-elevated border border-glassy-border-default rounded-sm py-1.5 pl-8 pr-3 text-xs text-glassy-text-primary placeholder-glassy-text-disabled focus:outline-none focus:border-glassy-border-focus"
                            />
                        </div>
                        
                        {/* Dropdown Filters */}
                        <div className="flex gap-2">
                            <div className="relative flex-1">
                                <Filter className="absolute left-2 top-1/2 -translate-y-1/2 text-glassy-text-tertiary" size={10} />
                                <select 
                                    value={modeFilter} onChange={e => setModeFilter(e.target.value)}
                                    className="w-full bg-glassy-bg-elevated border border-glassy-border-default rounded-sm py-1 pl-6 pr-2 text-[10px] text-glassy-text-primary appearance-none outline-none focus:border-glassy-border-prominent cursor-pointer"
                                >
                                    <option value="ALL">All Modes</option>
                                    <option value="BALANCED">Balanced</option>
                                    <option value="IMBALANCED">Imbalanced</option>
                                    <option value="DEAD">Dead Market</option>
                                </select>
                            </div>
                            <div className="relative flex-1">
                                <Filter className="absolute left-2 top-1/2 -translate-y-1/2 text-glassy-text-tertiary" size={10} />
                                <select 
                                    value={actionFilter} onChange={e => setActionFilter(e.target.value)}
                                    className="w-full bg-glassy-bg-elevated border border-glassy-border-default rounded-sm py-1 pl-6 pr-2 text-[10px] text-glassy-text-primary appearance-none outline-none focus:border-glassy-border-prominent cursor-pointer"
                                >
                                    <option value="ALL">All Actions</option>
                                    <option value="ENTER_NOW">Enter Now</option>
                                    <option value="SKIP">Skip</option>
                                    <option value="MONITOR">Monitor/Wait</option>
                                </select>
                            </div>
                        </div>
                        
                        {/* Column Header */}
                        <div className="flex w-full text-[9px] text-glassy-text-disabled font-mono mt-3 px-2 pb-1 border-b border-glassy-border-subtle uppercase tracking-tighter">
                            <div className="w-[24%]">Symbol</div>
                            <div className="w-[28%] cursor-pointer hover:text-glassy-text-tertiary" onClick={() => setSortBy('ACTION')} title="Sort by action priority">
                                Status {sortBy === 'ACTION' ? '↓' : '↕'}
                            </div>
                            <div className="w-[20%] cursor-pointer hover:text-glassy-text-tertiary" onClick={() => setSortBy('PROB')} title="Sort by probability">
                                Prob% {sortBy === 'PROB' ? '↓' : '↕'}
                            </div>
                            <div className="w-[16%] text-right pr-2">LTP</div>
                            <div className="w-[12%] text-right">Chg</div>
                        </div>
                    </div>
                </div>

                {/* Symbol List */}
                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {filtered.length === 0 && (
                        <div className="text-center text-[9px] text-glassy-text-disabled py-8">
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
            <div className="h-[250px] border-t border-glassy-border-default flex flex-col bg-glassy-bg-primary/30 shrink-0">
                <div className="p-3 border-b border-glassy-border-subtle flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <History className="text-glassy-neutral-cool" size={16} />
                        <h3 className="font-bold text-xs tracking-wider text-glassy-text-secondary uppercase">
                            {activeSymbol ? `${shortSymbol(activeSymbol).name} Trades` : 'Recent Trades'}
                        </h3>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {recentTrades.length === 0 ? (
                        <div className="h-full flex flex-col items-center justify-center text-glassy-text-disabled">
                            <History size={24} className="mb-2 opacity-50" />
                            <span className="text-[9px] italic">No closed trades for {shortSymbol(activeSymbol).name}</span>
                        </div>
                    ) : (
                        recentTrades.map(trade => (
                            <div key={trade.id} className="p-2 rounded-sm bg-glassy-bg-elevated/50 border border-glassy-border-subtle text-xs hover:bg-glassy-bg-hover transition-colors space-y-1">
                                <div className="flex justify-between items-center">
                                    <div className="flex items-center gap-1.5">
                                        <span className="font-bold text-glassy-text-primary">{shortSymbol(trade.symbol).name}</span>
                                        <span className={`text-[9px] px-1 rounded-sm ${trade.side === 'LONG' ? 'bg-glassy-bull-primary/20 text-glassy-bull-primary' : 'bg-glassy-bear-primary/20 text-glassy-bear-primary'}`}>
                                            {trade.side}
                                        </span>
                                        {trade.size > 0 && <span className="text-[9px] text-glassy-text-tertiary">x{(trade.originalSize ?? trade.size).toFixed(0)}</span>}
                                    </div>
                                    <div className={`font-mono font-bold ${trade.pnl >= 0 ? 'text-glassy-bull-primary' : 'text-glassy-bear-primary'}`}>
                                        {trade.pnl >= 0 ? '+' : ''}{trade.pnl.toFixed(2)}
                                    </div>
                                </div>
                                <div className="flex justify-between text-[9px] text-glassy-text-tertiary font-mono">
                                    <span>Entry: {trade.entryPrice?.toFixed(2)}</span>
                                    <span>Exit: {trade.exitPrice?.toFixed(2) || '—'}</span>
                                </div>
                                <div className="flex justify-between text-[8px] text-glassy-text-disabled">
                                    <span>{new Date(trade.entryTime || '').toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' })} → {new Date(trade.exitTime || '').toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' })}</span>
                                </div>
                                <div className="flex justify-between text-[8px]">
                                    <span className="text-glassy-text-disabled">{trade.source}</span>
                                    {trade.closeReason && <span className="text-glassy-warning/70">{trade.closeReason}</span>}
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Footer Status */}
            <div className="p-3 border-t border-glassy-border-default bg-glassy-bg-elevated/50 text-[9px] text-glassy-text-tertiary flex justify-between items-center shrink-0">
                <div className="flex items-center gap-1.5">
                    <div className="w-1.5 h-1.5 rounded-full bg-glassy-bull-primary animate-pulse" />
                    <span>Live Feed</span>
                </div>
                <span>{filtered.length} Visible</span>
            </div>
        </GlassPanel>
    );
};

export default MarketSidebar;
