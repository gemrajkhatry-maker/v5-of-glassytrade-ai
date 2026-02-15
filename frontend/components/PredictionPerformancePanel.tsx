
import React from 'react';
import { StrategyStats, TradePosition, OHLCData, AIAnalysis, ModelWeights } from '../types';
import GlassPanel from './GlassPanel';
import { Sparkles, TrendingUp, History, Zap, ArrowRight, Activity, BarChart2, Brain, Network } from 'lucide-react';

interface PredictionPerformancePanelProps {
  stats: StrategyStats;
  activeTrade: TradePosition | undefined;
  ghostCandles: OHLCData[];
  analysis: AIAnalysis | null;
  weights: ModelWeights | null;
  generation: number;
}

const PredictionPerformancePanel: React.FC<PredictionPerformancePanelProps> = ({ stats, activeTrade, ghostCandles, analysis, weights, generation }) => {
  
  // Calculate Projected Profit based on the last ghost candle
  let projectedPnL = 0;
  let projectedPrice = 0;
  
  if (activeTrade && ghostCandles.length > 0) {
      projectedPrice = ghostCandles[ghostCandles.length - 1].close;
      const priceDiff = activeTrade.side === 'LONG' 
          ? projectedPrice - activeTrade.entryPrice 
          : activeTrade.entryPrice - projectedPrice;
      projectedPnL = priceDiff * activeTrade.size;
  }

  // Sentiment Colors
  const sentimentColor = analysis?.sentiment === 'BULLISH' ? 'text-emerald-400' 
                       : analysis?.sentiment === 'BEARISH' ? 'text-red-400' 
                       : 'text-gray-400';

  return (
    <GlassPanel className="w-full p-4 backdrop-blur-3xl bg-[#0f172a]/40 border-purple-500/20 shadow-[0_0_40px_-10px_rgba(168,85,247,0.1)]">
        
        {/* Header */}
        <div className="flex items-center gap-2 mb-4 pb-3 border-b border-purple-500/10">
            <Sparkles className="w-4 h-4 text-purple-400" />
            <h2 className="font-bold text-xs tracking-wide text-purple-100">AI LEARNING MODEL</h2>
            <div className="ml-auto text-[9px] bg-purple-500/20 px-2 py-0.5 rounded text-purple-300 font-mono">
                GEN {generation}
            </div>
        </div>

        <div className="space-y-4">
            
            {/* NEW: Sentiment & Confidence Meter */}
            {analysis && (
                <div className="bg-black/20 p-3 rounded-lg border border-purple-500/10">
                    <div className="flex justify-between items-center mb-2">
                         <div className="flex items-center gap-1.5 text-[10px] uppercase text-white/50">
                            <Activity size={12} /> SENTIMENT
                         </div>
                         <span className={`text-xs font-bold ${sentimentColor}`}>
                             {analysis.sentiment}
                         </span>
                    </div>
                    
                    <div className="space-y-1">
                        <div className="flex justify-between text-[10px] text-white/40">
                            <span>Confidence</span>
                            <span>{analysis.confidence.toFixed(0)}%</span>
                        </div>
                        <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
                            <div 
                                className={`h-full transition-all duration-500 ${analysis.confidence > 65 ? 'bg-purple-500' : 'bg-gray-600'}`}
                                style={{ width: `${analysis.confidence}%` }}
                            />
                        </div>
                        <div className="text-[9px] text-right text-white/20 mt-0.5">
                            Threshold: 65%
                        </div>
                    </div>
                </div>
            )}

            {/* Neural Weights Visualization */}
            {weights && (
                <div className="bg-black/20 p-3 rounded-lg border border-purple-500/10">
                    <div className="flex justify-between items-center mb-3">
                         <div className="flex items-center gap-1.5 text-[10px] uppercase text-white/50">
                            <Network size={12} /> Neural Weights
                         </div>
                    </div>
                    
                    <div className="space-y-2">
                        {[
                            { label: 'Trend', val: weights.trend, color: 'bg-blue-500' },
                            { label: 'Momentum', val: weights.momentum, color: 'bg-pink-500' },
                            { label: 'Order Flow', val: weights.delta, color: 'bg-emerald-500' },
                            { label: 'L2 Book', val: weights.orderBook, color: 'bg-yellow-500' },
                        ].map((w) => (
                            <div key={w.label} className="flex items-center gap-2">
                                <span className="text-[9px] text-white/40 w-14">{w.label}</span>
                                <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
                                    <div 
                                        className={`h-full transition-all duration-1000 ${w.color}`} 
                                        style={{ width: `${Math.min(100, w.val * 100 * 1.5)}%` }} // Scale up slightly for visual
                                    />
                                </div>
                                <span className="text-[9px] text-white/60 w-6 text-right">
                                    {(w.val * 100).toFixed(0)}%
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* 1. Active Trade Section */}
            {activeTrade ? (
                <div className="bg-purple-500/10 rounded-xl p-3 border border-purple-500/20 relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-16 h-16 bg-purple-500/20 blur-xl rounded-full -mr-8 -mt-8"></div>
                    
                    <div className="flex justify-between items-center mb-2">
                        <span className="text-[10px] uppercase text-purple-300 font-bold tracking-wider flex items-center gap-1">
                            <Zap size={10} /> Active Position
                        </span>
                        <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${activeTrade.side === 'LONG' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-red-500/20 text-red-300'}`}>
                            {activeTrade.side}
                        </span>
                    </div>

                    {/* Current PnL */}
                    <div className="flex justify-between items-end mb-1">
                        <span className="text-xs text-white/60">Current PnL</span>
                        <span className={`font-mono text-lg font-bold ${activeTrade.pnl >= 0 ? 'text-white' : 'text-red-300'}`}>
                            {activeTrade.pnl >= 0 ? '+' : ''}${activeTrade.pnl.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                        </span>
                    </div>

                    {/* Projected PnL */}
                    {ghostCandles.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-dashed border-purple-500/20">
                            <div className="flex justify-between items-center mb-1">
                                <span className="text-[10px] uppercase text-purple-300/70 flex items-center gap-1">
                                    AI Projection <ArrowRight size={8} />
                                </span>
                                <span className="text-[10px] font-mono text-purple-200 opacity-60">
                                    Target: {projectedPrice.toLocaleString()}
                                </span>
                            </div>
                             <div className="flex justify-between items-end">
                                <span className="text-xs text-white/40">Expected PnL</span>
                                <span className={`font-mono font-bold ${projectedPnL >= 0 ? 'text-purple-300' : 'text-red-400'}`}>
                                    {projectedPnL >= 0 ? '+' : ''}${projectedPnL.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                                </span>
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                <div className="p-4 rounded-xl border border-dashed border-white/10 text-center">
                    <span className="text-xs text-white/30 italic">No Active Prediction Trade</span>
                </div>
            )}

            {/* 2. Strategy Performance Stats */}
            <div className="grid grid-cols-2 gap-2">
                <div className="p-3 bg-black/20 rounded-lg border border-white/5">
                    <div className="text-[10px] text-white/40 mb-1 flex items-center gap-1">
                        <History size={10} /> TOTAL PNL
                    </div>
                    <div className={`font-mono font-bold text-xs ${stats.netProfit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {stats.netProfit >= 0 ? '+' : ''}${stats.netProfit.toLocaleString(undefined, {maximumFractionDigits: 0})}
                    </div>
                </div>
                <div className="p-3 bg-black/20 rounded-lg border border-white/5">
                    <div className="text-[10px] text-white/40 mb-1 flex items-center gap-1">
                        <TrendingUp size={10} /> WIN RATE
                    </div>
                    <div className="font-mono font-bold text-xs text-white">
                        {stats.winRate.toFixed(1)}%
                    </div>
                </div>
            </div>
            
             <div className="flex justify-between text-[10px] text-white/30 px-1">
                 <span>Trades: {stats.totalTrades}</span>
                 <span>Wins: {stats.wins}</span>
                 <span>Losses: {stats.losses}</span>
            </div>

        </div>
    </GlassPanel>
  );
};

export default PredictionPerformancePanel;
