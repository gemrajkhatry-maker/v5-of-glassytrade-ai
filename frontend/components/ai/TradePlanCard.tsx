import React from 'react';
import { Shield } from 'lucide-react';
import { TradePosition } from '../../types';

interface TradePlanCardProps {
    positions: TradePosition[];
}

/** 04c. TRADE PLAN — open positions with SL/TP/trail, R-mult, partial TP, time held. */
const TradePlanCard = React.memo<TradePlanCardProps>(({ positions }) => {
    const openPositions = positions.filter(p => p.status === 'OPEN');

    if (openPositions.length === 0) return null;

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>04c. Trade Plan</span>
                <Shield className="w-3 h-3 hover:text-white/80 transition-colors" />
            </div>
            <div className="space-y-2">
                {openPositions.map(pos => {
                    const isLong = pos.side === 'LONG';
                    const riskDist = Math.abs(pos.entryPrice - pos.stopLoss);
                    const unrealR = riskDist > 0 ? (isLong ? (pos.pnl / pos.size) / riskDist : (-pos.pnl / pos.size) / riskDist) : 0;
                    const atBreakeven = Math.abs(pos.stopLoss - pos.entryPrice) < 0.01;
                    const elapsed = Math.round((Date.now() - new Date(pos.entryTime).getTime()) / 1000);
                    const mins = Math.floor(elapsed / 60);
                    const secs = elapsed % 60;
                    const hasPartial = (pos.partialRealizedPnl || 0) > 0;
                    const origSize = pos.originalSize || pos.size;
                    const sizeReduced = origSize > pos.size;
                    const isPut = pos.symbol && (pos.symbol.includes('PUT') || pos.symbol.includes('PE'));
                    const isCall = pos.symbol && (pos.symbol.includes('CALL') || pos.symbol.includes('CE'));
                    const displaySide = isPut ? 'BUY PUT (LONG)' : isCall ? 'BUY CALL (LONG)' : pos.side;
                    const thesisBadge = isPut ? 'BEARISH' : isCall ? 'BULLISH' : '';
                    return (
                        <div key={pos.id} className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-1.5">
                            {pos.symbol && (
                                <div className="flex justify-between items-center text-[10px] font-mono text-slate-300 pb-1 border-b border-white/5">
                                    <span className="font-semibold truncate max-w-[200px]" title={pos.symbol}>{pos.symbol}</span>
                                    {thesisBadge && (
                                        <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider border ${
                                            isPut ? 'bg-red-500/20 text-red-300 border-red-500/40' : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                                        }`}>
                                            {thesisBadge}
                                        </span>
                                    )}
                                </div>
                            )}
                            <div className="flex justify-between items-center">
                                <span className={`text-xs font-bold ${isLong ? 'text-green-400' : 'text-red-400'}`}>
                                    {displaySide} x{pos.size.toFixed(0)}{sizeReduced && <span className="text-white/30 text-[9px] ml-1">(was {origSize.toFixed(0)})</span>} @ {pos.entryPrice.toFixed(2)}
                                </span>
                                <span className={`text-xs font-mono font-bold ${pos.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {pos.pnl >= 0 ? '+' : ''}₹{pos.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </span>
                            </div>
                            {/* Partial TP status */}
                            {hasPartial && (
                                <div className="flex items-center gap-2 px-2 py-1 rounded bg-orange-500/10 border border-orange-500/15">
                                    <div className="h-1.5 w-1.5 rounded-full bg-orange-400"></div>
                                    <span className="text-[9px] text-orange-300">Partial TP booked</span>
                                    <span className="text-[9px] font-mono font-bold text-orange-400 ml-auto">
                                        +₹{(pos.partialRealizedPnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                                    </span>
                                </div>
                            )}
                            <div className="grid grid-cols-3 gap-2 text-[9px]">
                                <div>
                                    <div className="text-white/30">SL</div>
                                    <div className={`font-mono font-bold ${atBreakeven ? 'text-cyan-400' : 'text-red-300'}`}>
                                        {pos.stopLoss.toFixed(2)}
                                        {atBreakeven && <span className="ml-1 text-[8px]">BE</span>}
                                    </div>
                                </div>
                                <div>
                                    <div className="text-white/30">TP</div>
                                    <div className="font-mono font-bold text-green-300">{pos.takeProfit.toFixed(2)}</div>
                                </div>
                                <div>
                                    <div className="text-white/30">R-mult</div>
                                    <div className={`font-mono font-bold ${unrealR >= 1 ? 'text-green-400' : unrealR >= 0 ? 'text-yellow-400' : 'text-red-400'}`}>
                                        {unrealR >= 0 ? '+' : ''}{unrealR.toFixed(1)}R
                                    </div>
                                </div>
                            </div>
                            <div className="flex justify-between items-center text-[9px] pt-1 border-t border-white/5">
                                <span className="text-white/30 font-mono">{mins}m {secs}s held</span>
                                <span className="text-white/20 font-mono">{hasPartial ? 'Runner' : 'Full size'}</span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
});

TradePlanCard.displayName = 'TradePlanCard';

export default TradePlanCard;
