
import React, { useState, useCallback, useMemo } from 'react';
import GlassPanel from './GlassPanel';
import { InstrumentState } from '../types';
import { Search, BarChart3, Radio, Filter } from 'lucide-react';
import { shortSymbol } from '../utils/symbol';
import { ThreeAIndicator } from './ai/ThreeAIndicator';

interface MarketSidebarProps {
    instruments: Record<string, InstrumentState>;
    activeSymbol: string;
    onSelect: (symbol: string) => void;
    isHalted?: boolean;
    haltReason?: string;
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
    const percentChange = price > 0 && prevPrice > 0 ? ((price - prevPrice) / prevPrice) * 100 : 0;
    const isUp = percentChange >= 0;
    const { name, tag } = shortSymbol(sym);

    // --- Live PnL from open positions ---
    const openPositions = inst.portfolio?.positions?.filter(p => p.status === 'OPEN') || [];
    const hasOpenPosition = openPositions.length > 0;
    const firstPos = openPositions[0];
    const posSide = firstPos?.side || (firstPos?.size && firstPos.size > 0 ? 'LONG' : 'SHORT') || 'LONG';
    const totalSize = openPositions.reduce((sum, p) => sum + Math.abs(p.size || 0), 0);
    const totalPnl = openPositions.reduce((sum, p) => {
        if (p.pnl !== undefined && p.pnl !== 0) return sum + p.pnl;
        const curPrice = price > 0 ? price : p.entryPrice;
        return sum + ((curPrice - p.entryPrice) * p.size);
    }, 0);
    const isProfit = totalPnl > 0;
    const isLoss = totalPnl < 0;

    const isDead = inst.amtAnalysis?.marketState === 'DEAD';

    const pnlBadgeColor = isProfit
        ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
        : isLoss
        ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
        : 'bg-blue-500/15 text-blue-400 border-blue-500/30';

    const pnlTextColor = isProfit
        ? 'text-emerald-400 font-bold'
        : isLoss
        ? 'text-rose-400 font-bold'
        : 'text-slate-300 font-normal';

    const formatPnl = (val: number) => {
        const sign = val > 0 ? '+' : val < 0 ? '-' : '';
        const abs = Math.abs(val);
        if (abs >= 100000) return `${sign}₹${(abs / 100000).toFixed(1)}L`;
        if (abs >= 1000) return `${sign}₹${(abs / 1000).toFixed(1)}k`;
        return `${sign}₹${abs.toFixed(0)}`;
    };

    return (
        <button
            onClick={() => onSelect(sym)}
            className={`
                w-full px-2 py-1.5 rounded-sm flex items-center gap-0 group transition-colors duration-200 text-left border-l-2
                ${hasOpenPosition
                    ? isProfit
                        ? isActive
                            ? 'bg-emerald-500/15 border-l-emerald-400'
                            : 'bg-emerald-500/5 border-l-emerald-500/60 hover:bg-emerald-500/10'
                        : isLoss
                        ? isActive
                            ? 'bg-rose-500/15 border-l-rose-400'
                            : 'bg-rose-500/5 border-l-rose-500/60 hover:bg-rose-500/10'
                        : isActive
                        ? 'bg-blue-500/15 border-l-blue-400'
                        : 'bg-blue-500/5 border-l-blue-500/60 hover:bg-blue-500/10'
                    : isActive
                        ? 'bg-glassy-bg-active border-l-glassy-ai-primary'
                        : 'bg-transparent hover:bg-glassy-bg-hover border-l-transparent'}
                ${isDead ? 'opacity-40 saturate-0' : ''}
                border-b border-glassy-border-subtle
            `}
        >
            {/* Symbol & Tag (38%) */}
            <div className="flex flex-col w-[38%] overflow-hidden pr-2">
                <div className="flex items-center gap-1.5 min-h-[14px]">
                    {hasOpenPosition ? (
                        <span className={`text-[9px] font-bold ${isProfit ? 'text-emerald-400' : isLoss ? 'text-rose-400' : 'text-blue-400'}`}>●</span>
                    ) : (
                        <Radio size={8} className="text-glassy-bull-primary shrink-0" />
                    )}
                    <span className="font-bold text-[10px] text-glassy-text-primary truncate tabular-nums">
                        {name}
                    </span>
                </div>
                <div className="flex items-center gap-1 ml-3 mt-0.5">
                    {tag === 'FUT' ? (
                        <span className="inline-flex items-center px-1 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 text-[7.5px] font-mono font-bold leading-tight tracking-wider">
                            FUT
                        </span>
                    ) : tag === 'CE' ? (
                        <span className="inline-flex items-center px-1 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[7.5px] font-mono font-semibold leading-tight">
                            CE
                        </span>
                    ) : tag === 'PE' ? (
                        <span className="inline-flex items-center px-1 rounded bg-rose-500/15 text-rose-300 border border-rose-500/30 text-[7.5px] font-mono font-semibold leading-tight">
                            PE
                        </span>
                    ) : (
                        <span className="text-[8px] text-glassy-text-tertiary font-mono">{tag || '\u00A0'}</span>
                    )}
                </div>
            </div>

            {/* 3A traffic light (37%) */}
            <div className="w-[37%] min-w-0 flex items-center justify-start">
                {hasOpenPosition ? (
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[7.5px] font-mono font-bold tracking-tight uppercase truncate ${pnlBadgeColor}`}>
                        {posSide} · {totalSize.toFixed(0)}
                    </span>
                ) : isDead ? (
                    <span className="inline-flex text-[8px] font-mono font-bold text-glassy-bear-primary/70 border border-glassy-bear-primary/20 px-1 rounded-sm">
                        DEAD
                    </span>
                ) : inst.riskState?.halted ? (
                    <span
                        className="inline-flex items-center px-1.5 py-0.5 rounded text-[8px] font-black font-mono leading-none border uppercase tracking-wider text-rose-400 border-rose-500/40 bg-rose-500/10"
                        title={`Halted: ${inst.riskState.haltReason || 'Risk limit reached'}`}
                    >
                        HALTED
                    </span>
                ) : (
                    <ThreeAIndicator amt={inst.amtAnalysis} />
                )}
            </div>

            {/* Change% or Live PnL (25%) */}
            <div className="w-[25%] text-right">
                {hasOpenPosition ? (
                    <span className={`text-[9.5px] font-mono tabular-nums whitespace-nowrap ${pnlTextColor}`}>
                        {formatPnl(totalPnl)}
                    </span>
                ) : (
                    <span className={`text-[9px] font-mono tabular-nums whitespace-nowrap ${isUp ? 'text-glassy-bull-primary/80' : 'text-glassy-bear-primary/80'}`}>
                        {isUp ? '+' : ''}{percentChange.toFixed(1)}%
                    </span>
                )}
            </div>
        </button>
    );
});

SymbolCard.displayName = 'SymbolCard';

const MarketSidebar: React.FC<MarketSidebarProps> = ({ instruments, activeSymbol, onSelect, isHalted, haltReason }) => {
    const [filter, setFilter] = useState('');
    const [modeFilter, setModeFilter] = useState('ALL');
    const [actionFilter, setActionFilter] = useState('ALL');
    const [sortBy, setSortBy] = useState<'ACTION' | 'PROB'>('ACTION');

    const symbols = useMemo(() => Object.keys(instruments), [Object.keys(instruments).join(',')]);
    
    const filtered = useMemo(() => {
        let f = symbols;

        // Apply text filter
        if (filter) f = f.filter(s => s.toLowerCase().includes(filter.toLowerCase()));

        // Apply Mode filter
        if (modeFilter !== 'ALL') f = f.filter(s => instruments[s]?.amtAnalysis?.marketState?.includes(modeFilter));

        // Apply Action filter
        if (actionFilter !== 'ALL') f = f.filter(s => instruments[s]?.agentDecision?.timing === actionFilter);

        // Keep stable symbol ordering to avoid DOM reshuffling and card jumping
        return f;
    }, [symbols, filter, modeFilter, actionFilter, instruments]);

    // Filter trades for the ACTIVE symbol only
    // (recent-trades panel removed — closedTrades is canonical in JournalPage)

    return (
        <GlassPanel className="h-full w-[280px] flex flex-col border-r border-glassy-border-default rounded-none rounded-r-md bg-glassy-bg-secondary shadow-xl z-50">

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
                            <div className="w-[40%]">Symbol</div>
                            <div className="w-[30%]" title="3A score: Auction · Area · Action (Valentini rules)">3A</div>
                            <div className="w-[30%] text-right">Chg</div>
                        </div>
                    </div>
                </div>

                {/* Symbol List */}
                <div className="flex-1 overflow-y-auto p-2 space-y-1 relative">
                    {/* HALTED overlay — covers all rows when risk limits are hit */}
                    {isHalted && (
                        <div className="sticky top-0 z-20 mb-2 px-2 py-1.5 rounded border border-rose-500/40 bg-rose-950/70 backdrop-blur-sm flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse shrink-0" />
                            <div className="min-w-0">
                                <div className="text-[9px] font-black text-rose-400 uppercase tracking-wider">TRADING HALTED</div>
                                <div className="text-[8px] text-rose-300/70 truncate">{haltReason || 'Session risk limit reached'}</div>
                            </div>
                        </div>
                    )}
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
