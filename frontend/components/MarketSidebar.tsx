
import React, { useState, useCallback } from 'react';
import GlassPanel from './GlassPanel';
import { InstrumentState } from '../types';
import { TrendingUp, TrendingDown, Search, BarChart3, History, Radio } from 'lucide-react';

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

    // Position status & unrealized PnL
    const openPos = inst.portfolio.positions.filter(p => p.status === 'OPEN');
    const unrealizedPnl = openPos.reduce((sum, p) => {
        const multiplier = p.side === 'LONG' ? 1 : -1;
        return sum + (price - p.entryPrice) * multiplier * p.size;
    }, 0);

    return (
        <button
            onClick={() => onSelect(sym)}
            className={`
                w-full p-3 rounded-xl flex items-center justify-between group transition-all duration-200
                ${openPos.length > 0
                    ? unrealizedPnl >= 0
                        ? 'bg-emerald-500/10 border border-emerald-500/20'
                        : 'bg-red-500/10 border border-red-500/20'
                    : isActive
                        ? 'bg-purple-500/20 border border-purple-500/30 shadow-[0_0_15px_rgba(168,85,247,0.15)]'
                        : 'hover:bg-white/5 border border-transparent hover:border-white/5'}
            `}
        >
            <div className="flex flex-col items-start gap-0.5">
                <div className="flex items-center gap-1.5">
                    <Radio size={8} className={hasData ? 'text-emerald-400' : 'text-white/20'} />
                    <span className={`font-bold text-xs ${isActive ? 'text-white' : 'text-white/70 group-hover:text-white'}`}>
                        {name}
                    </span>
                    {tag && (
                        <span className={`text-[9px] px-1 rounded font-medium ${tag === 'CE' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                            }`}>
                            {tag}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2 ml-3.5">
                    {openPos.length > 0 && (
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold font-mono ${unrealizedPnl >= 0 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                            }`}>
                            {unrealizedPnl >= 0 ? '+' : ''}{unrealizedPnl.toFixed(1)} ({openPos.length})
                        </span>
                    )}
                    {inst.amtAnalysis?.marketState && (
                        <span className="text-[8px] text-white/25">
                            {inst.amtAnalysis.marketState}
                        </span>
                    )}
                </div>
            </div>

            <div className="flex flex-col items-end">
                {price > 0 ? (
                    <>
                        <span className="font-mono text-xs text-white/90">
                            {price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <div className={`flex items-center gap-1 text-[10px] ${isUp ? 'text-emerald-400' : 'text-red-400'}`}>
                            {isUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                            <span>{Math.abs(percentChange).toFixed(2)}%</span>
                        </div>
                    </>
                ) : (
                    <span className="text-[10px] text-white/20">Loading...</span>
                )}
            </div>
        </button>
    );
});

SymbolCard.displayName = 'SymbolCard';

const MarketSidebar: React.FC<MarketSidebarProps> = ({ instruments, activeSymbol, onSelect }) => {
    const [filter, setFilter] = useState('');
    const symbols = Object.keys(instruments);
    const filtered = filter
        ? symbols.filter(s => s.toLowerCase().includes(filter.toLowerCase()))
        : symbols;

    // Filter trades for the ACTIVE symbol only
    const recentTrades = React.useMemo(() => {
        const activeInstrument = instruments[activeSymbol];
        if (!activeInstrument) return [];

        return [...activeInstrument.portfolio.closedTrades]
            .sort((a, b) => new Date(b.exitTime || 0).getTime() - new Date(a.exitTime || 0).getTime());
    }, [instruments[activeSymbol]?.portfolio?.closedTrades, activeSymbol]);

    return (
        <GlassPanel className="h-full w-64 flex flex-col border-r border-white/10 rounded-none rounded-r-2xl bg-slate-900/50">

            {/* --- MARKET SCANNER (Top Section) --- */}
            <div className="flex-1 flex flex-col min-h-0">
                {/* Header */}
                <div className="p-4 border-b border-white/10 shrink-0">
                    <div className="flex items-center gap-2 mb-4">
                        <BarChart3 className="text-purple-400" size={20} />
                        <h2 className="font-bold text-sm tracking-widest text-white/90">MARKET SCANNER</h2>
                        <span className="ml-auto text-[10px] text-white/30 bg-white/5 px-1.5 py-0.5 rounded">{symbols.length}</span>
                    </div>

                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" size={14} />
                        <input
                            type="text"
                            placeholder="Filter symbols..."
                            value={filter}
                            onChange={e => setFilter(e.target.value)}
                            className="w-full bg-black/20 border border-white/10 rounded-lg py-2 pl-9 pr-3 text-xs text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50"
                        />
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
