
import React from 'react';
import GlassPanel from './GlassPanel';
import { InstrumentState } from '../types';
import { Activity, TrendingUp, TrendingDown, Search, BarChart3, History } from 'lucide-react';

interface MarketSidebarProps {
  instruments: Record<string, InstrumentState>;
  activeSymbol: string;
  onSelect: (symbol: string) => void;
}

const MarketSidebar: React.FC<MarketSidebarProps> = ({ instruments, activeSymbol, onSelect }) => {
  const symbols = Object.keys(instruments);

  // Filter trades for the ACTIVE symbol only
  // Removed strict dependency on just [instruments, activeSymbol] and added lastUpdate to force refresh
  const recentTrades = React.useMemo(() => {
    const activeInstrument = instruments[activeSymbol];
    if (!activeInstrument) return [];

    return [...activeInstrument.portfolio.closedTrades]
        .sort((a, b) => new Date(b.exitTime || 0).getTime() - new Date(a.exitTime || 0).getTime());
  }, [instruments[activeSymbol], activeSymbol]); // Depend directly on the active instrument object

  return (
    <GlassPanel className="h-full w-64 flex flex-col border-r border-white/10 rounded-none rounded-r-2xl bg-slate-900/50">
      
      {/* --- MARKET SCANNER (Top Section) --- */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* Header */}
        <div className="p-4 border-b border-white/10 shrink-0">
            <div className="flex items-center gap-2 mb-4">
                <BarChart3 className="text-purple-400" size={20} />
                <h2 className="font-bold text-sm tracking-widest text-white/90">MARKET SCANNER</h2>
            </div>
            
            <div className="relative">
                 <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" size={14} />
                 <input 
                    type="text" 
                    placeholder="Filter assets..." 
                    className="w-full bg-black/20 border border-white/10 rounded-lg py-2 pl-9 pr-3 text-xs text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50"
                 />
            </div>
        </div>

        {/* Symbol List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {symbols.map(sym => {
                const inst = instruments[sym];
                const lastCandle = inst.data[inst.data.length - 1];
                const prevCandle = inst.data[inst.data.length - 2];
                
                const price = lastCandle?.close || 0;
                const prevPrice = prevCandle?.close || price;
                const percentChange = price > 0 ? ((price - prevPrice) / prevPrice) * 100 : 0;
                const isUp = percentChange >= 0;

                const isActive = sym === activeSymbol;

                return (
                    <button
                        key={sym}
                        onClick={() => onSelect(sym)}
                        className={`
                            w-full p-3 rounded-xl flex items-center justify-between group transition-all duration-200
                            ${isActive 
                                ? 'bg-purple-500/20 border border-purple-500/30 shadow-[0_0_15px_rgba(168,85,247,0.15)]' 
                                : 'hover:bg-white/5 border border-transparent hover:border-white/5'}
                        `}
                    >
                        <div className="flex flex-col items-start">
                            <span className={`font-bold text-xs ${isActive ? 'text-white' : 'text-white/70 group-hover:text-white'}`}>
                                {sym.replace('USDT', '')}
                            </span>
                            <span className="text-[10px] text-white/40">PERP</span>
                        </div>

                        <div className="flex flex-col items-end">
                            <span className="font-mono text-xs text-white/90">
                                {price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </span>
                            <div className={`flex items-center gap-1 text-[10px] ${isUp ? 'text-emerald-400' : 'text-red-400'}`}>
                                {isUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                                <span>{Math.abs(percentChange).toFixed(2)}%</span>
                            </div>
                        </div>
                    </button>
                );
            })}
        </div>
      </div>

      {/* --- TRADE HISTORY (Bottom Section) --- */}
      <div className="h-[250px] border-t border-white/10 flex flex-col bg-black/20 shrink-0">
          <div className="p-3 border-b border-white/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <History className="text-blue-400" size={16} />
                <h3 className="font-bold text-xs tracking-widest text-white/80">
                    {activeSymbol ? `${activeSymbol.replace('USDT', '')} TRADES` : 'RECENT TRADES'}
                </h3>
              </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {recentTrades.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-white/20">
                      <History size={24} className="mb-2 opacity-50"/>
                      <span className="text-[10px] italic">No closed trades for {activeSymbol.replace('USDT', '')}</span>
                  </div>
              ) : (
                  recentTrades.map(trade => (
                      <div key={trade.id} className="p-2 rounded-lg bg-white/5 border border-white/5 flex justify-between items-center text-xs hover:bg-white/10 transition-colors">
                          <div>
                              <div className="flex items-center gap-1.5">
                                  <span className="font-bold text-white/90">{trade.symbol.replace('USDT','')}</span>
                                  <span className={`text-[9px] px-1 rounded ${trade.side === 'LONG' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                                    {trade.side}
                                  </span>
                              </div>
                              <div className="text-[9px] text-white/30 mt-0.5">
                                  {new Date(trade.exitTime || '').toLocaleTimeString()}
                              </div>
                          </div>
                          <div className="text-right">
                              <div className={`font-mono font-bold ${trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                              </div>
                              <div className="text-[9px] text-white/30">
                                  {trade.source}
                              </div>
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
          <span>{symbols.length} ACTIVE</span>
      </div>
    </GlassPanel>
  );
};

export default MarketSidebar;
