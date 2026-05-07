import React from 'react';
import { Brain, Eye, Shield, TrendingUp, TrendingDown } from 'lucide-react';
import { AMTAnalysis, AgentDecision, Portfolio, LLMHistoryEntry } from '../../../types';

interface MetricsTabProps {
  agentDecision?: AgentDecision | null;
  overseerAction?: string;
  overseerReason?: string;
  portfolio: Portfolio;
  amtResult?: AMTAnalysis | null;
  llmHistory?: LLMHistoryEntry[];
}

/**
 * MetricsTab - Combines Probability Engine, Overseer, and Trade Plan
 * Extracted from AIAnalysisPanel.tsx lines 1365-1580
 */
const MetricsTab: React.FC<MetricsTabProps> = ({
  agentDecision,
  overseerAction,
  overseerReason,
  portfolio,
  amtResult,
  llmHistory = [],
}) => {
  return (
    <div className="flex flex-col gap-3 p-3">
      {/* 04. PROBABILITY ENGINE */}
      <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2 relative overflow-hidden">
        {agentDecision ? (
          <>
            <div className={`absolute top-0 left-0 w-1 h-full ${agentDecision.timing === 'ENTER_NOW' ? 'bg-emerald-500' : 'bg-yellow-500/50'}`} />
            
            <div className="flex justify-between items-center pl-2">
              <span className="text-[10px] text-white/40">Direction</span>
              <span className={`text-xs font-bold ${agentDecision.direction === 'LONG' ? 'text-emerald-400' : agentDecision.direction === 'SHORT' ? 'text-red-400' : 'text-blue-300'}`}>
                {(() => {
                  const dir = agentDecision?.direction || 'FLAT';
                  const regime = agentDecision?.regime || '';
                  const optionType = amtResult?.optionType || '';
                  
                  if (dir === 'FLAT') return 'FLAT';
                  
                  const action = dir === 'LONG' ? 'BUY' : 'SELL';
                  const optionLabel = optionType ? ` ${optionType}` : '';
                  
                  const playbookLabel = regime === 'TRENDING' ? 'Initiative Trend' : 
                                        regime === 'BALANCED' ? 'Responsive Fade' : 
                                        regime === 'PROBING' ? 'Breakout Test' : 
                                        regime === 'DEAD' ? 'Failed Auction' : regime;
                  
                  return `${action}${optionLabel} (${playbookLabel})`;
                })()}
              </span>
            </div>
            
            <div className="flex justify-between items-center pl-2">
              <span className="text-[10px] text-white/40">P(target)</span>
              <span className={`text-xs font-mono font-bold ${agentDecision.probability >= 0.6 ? 'text-emerald-400' : agentDecision.probability > 0.45 ? 'text-yellow-400' : agentDecision.probability > 0 ? 'text-red-400' : 'text-white/30'}`}>
                {(agentDecision.probability * 100).toFixed(1)}%
              </span>
            </div>
            
            {/* Probability bar */}
            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden ml-2">
              <div className="h-full rounded-full transition-all duration-500" style={{
                width: `${Math.min(agentDecision.probability * 100, 100)}%`,
                backgroundColor: agentDecision.probability >= 0.6 ? '#4ade80' : agentDecision.probability > 0.45 ? '#facc15' : agentDecision.probability > 0 ? '#f87171' : '#334155',
              }} />
            </div>
            
            <div className="flex justify-between items-center pl-2 pt-1">
              <span className="text-[10px] text-white/40">Timing / Size</span>
              <div className="flex items-center gap-2">
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-bold tracking-wider ${agentDecision.timing === 'ENTER_NOW' ? 'bg-emerald-500/20 text-emerald-400' : agentDecision.timing === 'SKIP' ? 'bg-white/10 text-white/30' : 'bg-yellow-500/20 text-yellow-400'}`}>
                  {agentDecision.timing}
                </span>
                <span className="text-[10px] font-mono font-bold text-white/80">{(agentDecision.sizeFraction * 100).toFixed(1)}%</span>
              </div>
            </div>
            
            {/* Second Drive Indicator */}
            {amtResult?.isSecondDrive !== undefined && (
              <div className="flex justify-between items-center pl-2 pt-1">
                <span className="text-[10px] text-white/40">Drive Cycle</span>
                {amtResult.isSecondDrive ? (
                  <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                    <span>✅ SECOND DRIVE</span>
                    <span className="text-[8px] font-normal text-white/50">High probability re-test</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
                    <span>⚠️ FIRST DRIVE</span>
                    <span className="text-[8px] font-normal text-white/50">Wait for re-test if possible</span>
                  </div>
                )}
              </div>
            )}
            
            {/* LVN Play Indicator */}
            {amtResult?.lvnPlay && (
              <div className="flex justify-between items-center pl-2 pt-1">
                <span className="text-[10px] text-white/40">LVN Entry</span>
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide bg-violet-500/20 text-violet-400 border border-violet-500/30">
                  <span>🎯 LVN PLAY</span>
                  <span className="text-[8px] font-mono font-normal text-white/50">@ {amtResult.lvnPlay.lvn_price.toFixed(1)}</span>
                  <span className={`text-[8px] font-bold ${amtResult.lvnPlay.direction === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>
                    {amtResult.lvnPlay.direction}
                  </span>
                </div>
              </div>
            )}
            
            <details className="group mt-2 pt-2 border-t border-white/5 pl-2 cursor-pointer">
              <summary className="list-none flex justify-between items-center text-[9px] text-white/40 uppercase tracking-widest font-bold">
                <span>Logic Formulas</span>
                <span className="group-open:hidden">Expand</span>
                <span className="hidden group-open:block">Collapse</span>
              </summary>
              <div className="mt-2 space-y-1">
                <div className="flex justify-between items-center">
                  <span className="text-[9px] text-white/40">Regime</span>
                  <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${agentDecision.regime === 'TRENDING' ? 'bg-purple-500/20 text-purple-400' :
                      agentDecision.regime === 'BALANCED' ? 'bg-blue-500/20 text-blue-400' :
                          agentDecision.regime === 'VOLATILE' ? 'bg-orange-500/20 text-orange-400' :
                              'bg-white/10 text-white/40'
                      }`}>{agentDecision.regime}</span>
                </div>
                <div className="text-[9px] text-white/30 font-mono mt-1 bg-black/20 p-1.5 rounded">
                  {agentDecision.rationale} <span className="text-white/20">({agentDecision.latencyUs}μs)</span>
                </div>
              </div>
            </details>
          </>
        ) : (
          <div className="text-[10px] text-white/30 text-center py-2">Waiting for probability engine...</div>
        )}
      </div>

      {/* 04b. OVERSEER */}
      {(overseerAction || portfolio.positions.length > 0) && (
        <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
          {overseerAction ? (
            <>
              <div className="flex justify-between items-center">
                <span className="text-[10px] text-white/40">Action</span>
                <span className={`text-xs font-bold uppercase ${overseerAction === 'HOLD' ? 'text-blue-300' :
                    overseerAction === 'TIGHTEN' ? 'text-yellow-400' :
                        overseerAction === 'FULL_EXIT' ? 'text-red-400' :
                            overseerAction === 'PARTIAL' ? 'text-orange-400' :
                                overseerAction === 'ADD' ? 'text-green-400' :
                                    'text-white/60'
                    }`}>{overseerAction}</span>
              </div>
              {overseerReason && (
                <div className="text-[9px] text-white/40 font-mono leading-relaxed">
                  {overseerReason}
                </div>
              )}
            </>
          ) : (
            <div className="text-[10px] text-white/30 text-center">No overseer decision yet</div>
          )}
        </div>
      )}

      {/* 04c. TRADE PLAN — Open Positions */}
      {portfolio.positions.filter(p => p.status === 'OPEN').length > 0 && (
        <div className="space-y-2">
          {portfolio.positions.filter(p => p.status === 'OPEN').map(pos => {
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
            
            return (
              <div key={pos.id} className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-1.5">
                <div className="flex justify-between items-center">
                  <span className={`text-xs font-bold ${isLong ? 'text-green-400' : 'text-red-400'}`}>
                    {pos.side} x{pos.size.toFixed(0)}{sizeReduced && <span className="text-white/30 text-[9px] ml-1">(was {origSize.toFixed(0)})</span>} @ {pos.entryPrice.toFixed(2)}
                  </span>
                  <span className={`text-xs font-mono font-bold ${pos.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {pos.pnl >= 0 ? '+' : ''}₹{pos.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
                
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
      )}
    </div>
  );
};

export default MetricsTab;
