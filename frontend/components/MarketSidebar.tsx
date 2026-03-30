
import React, { useState, useCallback, useMemo } from 'react';
import GlassPanel from './GlassPanel';
import { InstrumentState } from '../types';
import { TrendingUp, TrendingDown, Search, BarChart3, History, Radio, Filter } from 'lucide-react';

interface MarketSidebarProps {
    instruments: Record<string, InstrumentState>;
    activeSymbol: string;
    onSelect: (symbol: string) => void;
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

    const isDead = inst.genAIAnalysis?.rationale?.includes('DEAD') || inst.genAIAnalysis?.rawOutput?.includes('QUANT_DEAD_MARKET');
    const prob = inst.agentDecision?.probability || 0;
    const timing = inst.agentDecision?.timing || 'SKIP';
    const direction = inst.agentDecision?.direction || 'FLAT';
    const mode = inst.amtAnalysis?.marketState || 'BALANCED';

    return (
        <button
            onClick={() => onSelect(sym)}
            className={`
                w-full px-2 py-1.5 rounded flex items-center gap-0 group transition-all duration-200 text-left border-l-2
                ${isActive
                    ? 'bg-purple-500/10 border-l-purple-500 bg-gradient-to-r from-purple-500/5 to-transparent'
                    : 'bg-white/[0.02] hover:bg-white/[0.05] border-l-transparent'}
                ${isDead ? 'opacity-40 saturate-0' : ''}
                border-b border-white/[0.03]
            `}
        >
            {/* Symbol & Tag (25%) */}
            <div className="flex flex-col w-[25%] overflow-hidden pr-2">
                <div className="flex items-center gap-1.5">
                    <Radio size={8} className={hasData ? 'text-emerald-400' : 'text-white/20'} />
                    <span className="font-bold text-[10px] text-white/90 truncate">
                        {name}
                    </span>
                </div>
                <span className="text-[8px] text-white/30 font-mono ml-3">{tag}</span>
            </div>

            {/* Mode (15%) */}
            <div className="w-[15%]">
                <span className={`text-[8px] font-mono px-1 py-0.5 rounded ${
                    mode === 'BALANCED' ? 'text-amber-500 bg-amber-500/10' :
                    mode === 'PROBING' ? 'text-blue-400 bg-blue-500/10' :
                    mode === 'TRENDING' ? 'text-emerald-400 bg-emerald-500/10' :
                    mode === 'BREAKING' ? 'text-red-400 bg-red-500/10' :
                    'text-white/40 bg-white/5'
                }`}>
                    {mode?.substring(0, 4)}
                </span>
            </div>

            {/* Action (15%) */}
            <div className="w-[15%] flex items-center gap-1">
                <div className={`w-1 h-1 rounded-full ${timing === 'ENTER_NOW' ? 'bg-emerald-400 animate-pulse' : timing === 'SKIP' ? 'bg-red-400' : 'bg-yellow-400'}`} />
                <span className={`text-[9px] font-mono font-bold ${timing === 'ENTER_NOW' ? 'text-emerald-400' : timing === 'SKIP' ? 'text-red-400' : 'text-yellow-400'}`}>
                    {timing === 'ENTER_NOW' ? 'ENTER' : timing === 'MONITOR' ? 'WAIT' : timing}
                </span>
            </div>

            {/* Probability & Bar (20%) */}
            <div className="w-[20%] flex flex-col gap-0.5 pr-2">
                <span className={`text-[9px] font-mono font-bold ${prob >= 0.6 ? 'text-emerald-400' : prob >= 0.5 ? 'text-amber-400' : 'text-red-400'}`}>
                    {Math.round(prob * 100)}%
                </span>
                <div className="w-full h-0.5 bg-white/10 rounded-full overflow-hidden">
                    <div className="h-full transition-all duration-500" style={{ width: `${prob * 100}%`, backgroundColor: prob >= 0.6 ? '#34d399' : prob >= 0.5 ? '#fbbf24' : '#f87171' }} />
                </div>
            </div>

            {/* LTP / DEAD (15%) */}
            <div className="w-[15%] flex flex-col items-end pr-2">
                {isDead ? (
                    <span className="text-[7px] font-mono font-bold text-red-400/70 border border-red-500/20 px-1 rounded animate-pulse">
                        🔴 DEAD
                    </span>
                ) : (
                    <span className="font-mono text-[10px] text-white/70 font-bold">
                        {price > 0 ? price.toFixed(1) : '—'}
                    </span>
                )}
            </div>

            {/* Change (10%) */}
            <div className="w-[10%] text-right">
                <span className={`text-[9px] font-mono ${isUp ? 'text-emerald-400/80' : 'text-red-400/80'}`}>
                    {isUp ? '+' : ''}{percentChange.toFixed(1)}%
                </span>
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
                const getRank = (sym: string) => {
                    const t = instruments[sym].agentDecision?.timing;
                    if (t === 'ENTER_NOW') return 3;
                    if (t === 'MONITOR' || t === 'WAIT') return 2; 
                    if (t === 'SKIP') return 1;
                    return 0;
                };
                const rankA = getRank(a);
                const rankB = getRank(b);
                if (rankA !== rankB) return rankB - rankA;
                return pB - pA; // secondary sort by probability
            } else {
                // Primary sort by probability
                if (Math.abs(pA - pB) > 0.01) return pB - pA;
                // Secondary sort by timing
                const tA = instA.agentDecision?.timing === 'ENTER_NOW' ? 1 : 0;
                const tB = instB.agentDecision?.timing === 'ENTER_NOW' ? 1 : 0;
                return tB - tA;
            }
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
                            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30" size={14} />
                            <input
                                type="text"
                                placeholder="Filter symbols..."
                                value={filter}
                                onChange={e => setFilter(e.target.value)}
                                className="w-full bg-black/30 border border-white/10 rounded py-1.5 pl-8 pr-3 text-xs text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50"
                            />
                        </div>
                        
                        {/* Dropdown Filters */}
                        <div className="flex gap-2">
                            <div className="relative flex-1">
                                <Filter className="absolute left-2 top-1/2 -translate-y-1/2 text-white/30" size={10} />
                                <select 
                                    value={modeFilter} onChange={e => setModeFilter(e.target.value)}
                                    className="w-full bg-black/30 border border-white/10 rounded py-1 pl-6 pr-2 text-[10px] text-white/70 appearance-none outline-none focus:border-white/20 cursor-pointer"
                                >
                                    <option value="ALL">All Modes</option>
                                    <option value="BALANCED">Balanced</option>
                                    <option value="IMBALANCED">Imbalanced</option>
                                    <option value="DEAD">Dead Market</option>
                                </select>
                            </div>
                            <div className="relative flex-1">
                                <Filter className="absolute left-2 top-1/2 -translate-y-1/2 text-white/30" size={10} />
                                <select 
                                    value={actionFilter} onChange={e => setActionFilter(e.target.value)}
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
                        <div className="flex w-full text-[9px] text-white/30 font-mono mt-3 px-2 pb-1 border-b border-white/5 uppercase tracking-tighter">
                            <div className="w-[25%]">Symbol</div>
                            <div className="w-[15%]">Mode</div>
                            <div className="w-[15%] cursor-pointer hover:text-white/60" onClick={() => setSortBy('ACTION')}>
                                Action {sortBy === 'ACTION' ? '↓' : '↕'}
                            </div>
                            <div className="w-[20%] cursor-pointer hover:text-white/60" onClick={() => setSortBy('PROB')}>
                                Prob% {sortBy === 'PROB' ? '↓' : '↕'}
                            </div>
                            <div className="w-[15%] text-right pr-2">LTP</div>
                            <div className="w-[10%] text-right">Chg</div>
                        </div>
                    </div>
                </div>

                {/* Symbol List */}
                <div className="flex-1 overflow-y-auto p-2 space-y-1">
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
                                        {trade.size > 0 && <span className="text-[9px] text-white/40">x{trade.size}</span>}
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
                                    <span>{new Date(trade.entryTime || '').toLocaleTimeString()} → {new Date(trade.exitTime || '').toLocaleTimeString()}</span>
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
                <span>{symbols.length} SCANNING</span>
            </div>
        </GlassPanel>
    );
};

export default MarketSidebar;
