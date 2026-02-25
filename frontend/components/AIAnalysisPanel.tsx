import React, { useMemo } from 'react';
import { GenAIAnalysis, AMTAnalysis, Portfolio, RiskState, LLMHistoryEntry, AgentDecision, OrderBook } from '../types';
import { Brain, TrendingUp, TrendingDown, MinusCircle, Target, Activity, Settings, Zap, AlertTriangle, Clock, BarChart3 } from 'lucide-react';

interface AIAnalysisPanelProps {
    analysis: GenAIAnalysis | null;
    amtResult: AMTAnalysis | null;
    portfolio: Portfolio;
    riskState?: RiskState | null;
    agentDecision?: AgentDecision | null;
    llmHistory?: LLMHistoryEntry[];
    orderBook?: OrderBook | null;
    depth20Active?: boolean;
}

export const AIAnalysisPanel: React.FC<AIAnalysisPanelProps> = ({ analysis, amtResult, portfolio, riskState, agentDecision, llmHistory = [], orderBook, depth20Active }) => {
    // 1. Fallback: If both are missing -> Initializing
    if (!analysis && !amtResult) {
        return (
            <div className="bg-[#131722] border border-white/10 rounded-xl p-4 flex flex-col gap-4 font-sans text-slate-200 shadow-xl opacity-70">
                <div className="flex justify-between items-start">
                    <div className="flex items-center gap-2">
                        <Zap className="w-5 h-5 text-gray-500" />
                        <div>
                            <h2 className="text-sm font-bold tracking-wider text-white uppercase">Fabio Playbook</h2>
                            <div className="text-[10px] text-white/40 font-mono tracking-widest uppercase">CONNECTING TO FEED...</div>
                        </div>
                    </div>
                </div>
                <div className="h-32 flex items-center justify-center">
                    <div className="text-xs text-white/30 animate-pulse">Waiting for Market Data...</div>
                </div>
            </div>
        );
    }

    // 2. Monitoring Mode: AMT ready, but no GenAI signal yet
    // We construct a "dummy" analysis object from AMT data to render the panel in "Monitoring" mode
    const effectiveAnalysis = useMemo<GenAIAnalysis>(() => analysis || {
        direction: 'FLAT',
        rationale: "Monitoring market state and order flow. Waiting for Fabio Playbook setup.",
        confidence: 'Low',
        marketState: amtResult?.marketState || 'BALANCED',
        aggression: `Score:${amtResult?.aggression?.toFixed(2) || "0.00"}`
    }, [analysis, amtResult?.marketState, amtResult?.aggression]);

    // Always prefer AMT data for market state and aggression (real market data > LLM defaults)
    const displayAnalysis = useMemo(() => ({
        ...effectiveAnalysis,
        marketState: amtResult?.marketState || effectiveAnalysis.marketState || 'BALANCED',
        aggression: effectiveAnalysis.aggression && effectiveAnalysis.aggression !== ''
            ? effectiveAnalysis.aggression
            : `Score:${amtResult?.aggression?.toFixed(2) || "0.00"}`,
    }), [effectiveAnalysis, amtResult?.marketState, amtResult?.aggression]);

    // Memoize open PnL calculation (used 3 times in render)
    const openPnl = useMemo(() =>
        portfolio.positions.reduce((acc, p) => acc + p.pnl, 0),
        [portfolio.positions]
    );

    // Parse aggression — prefer live AMT aggression over LLM's stale value
    const aggScore = useMemo(() => {
        const liveAggression = amtResult?.aggression ?? 0;
        return typeof liveAggression === 'number' ? liveAggression : parseFloat(displayAnalysis.aggression?.split(':')[1] || "0.00");
    }, [amtResult?.aggression, displayAnalysis.aggression]);

    // Market state from AMT (real-time) not LLM (stale)
    const liveMarketState = amtResult?.marketState || displayAnalysis.marketState || 'BALANCED';
    const isImbalanced = liveMarketState === 'IMBALANCED';

    // Determine Status Color based on market state (not LLM direction)
    const statusColor = isImbalanced ? "text-orange-400" : "text-blue-300";
    const statusBg = isImbalanced ? "bg-orange-500/20" : "bg-blue-500/20";

    // Location Data
    const vah = useMemo(() => amtResult?.valueAreaHigh?.toFixed(2) || "---", [amtResult?.valueAreaHigh]);
    const val = useMemo(() => amtResult?.valueAreaLow?.toFixed(2) || "---", [amtResult?.valueAreaLow]);
    const poc = useMemo(() => amtResult?.poc?.toFixed(2) || "---", [amtResult?.poc]);

    return (
        <div className="bg-[#131722] border border-white/10 rounded-xl p-4 flex flex-col gap-4 font-sans text-slate-200 shadow-xl">

            {/* 0. Header */}
            <div className="flex justify-between items-start">
                <div className="flex items-center gap-2">
                    <Zap className="w-5 h-5 text-blue-400 fill-blue-400/20" />
                    <div>
                        <h2 className="text-sm font-bold tracking-wider text-white uppercase">Fabio Playbook</h2>
                        <div className="text-[10px] text-white/40 font-mono tracking-widest uppercase">AMT Execution Engine</div>
                    </div>
                </div>
                <div className="px-2 py-1 bg-blue-600/20 rounded border border-blue-500/30 text-[10px] font-bold text-blue-400 uppercase tracking-wider">
                    10x Live
                </div>
            </div>

            {/* Equity Panel */}
            <div className="grid grid-cols-2 gap-4 pb-4 border-b border-white/5">
                <div>
                    <div className="text-[10px] uppercase tracking-widest text-white/40 mb-1">Equity</div>
                    <div className="text-sm font-bold font-mono text-white">
                        ${portfolio.equity.toLocaleString()}
                    </div>
                </div>
                <div className="text-right">
                    <div className="text-[10px] uppercase tracking-widest text-white/40 mb-1">Open PNL</div>
                    <div className={`text-sm font-bold font-mono ${openPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {openPnl >= 0 ? '+' : ''}
                        ${openPnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </div>
                </div>
            </div>

            {/* Risk State Warning */}
            {riskState?.halted && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
                    <div>
                        <div className="text-[10px] uppercase tracking-widest text-red-400 font-bold">Trading Halted</div>
                        <div className="text-[10px] text-red-300/70">{riskState.haltReason}</div>
                    </div>
                </div>
            )}
            {riskState && !riskState.halted && riskState.consecutiveLosses > 0 && (
                <div className="flex justify-between text-[10px] px-1">
                    <span className="text-white/40">Consecutive Losses: <span className="text-yellow-400 font-bold">{riskState.consecutiveLosses}</span></span>
                    <span className="text-white/40">Daily P&L: <span className={riskState.dailyPnl >= 0 ? 'text-green-400' : 'text-red-400'}>${riskState.dailyPnl.toFixed(2)}</span></span>
                </div>
            )}

            {/* 01. STATE */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>01. State</span>
                    <Settings className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className={`p-3 rounded-lg bg-white/5 border border-white/5 ${statusBg}`}>
                    <div className="flex justify-between items-center mb-2">
                        <div className="text-[9px] text-white/30 uppercase tracking-wider">Session</div>
                        <div className="h-2 w-2 rounded-full bg-green-400 animate-pulse" title="Live"></div>
                    </div>
                    <div className="flex justify-between items-center">
                        <div className={`text-sm font-bold ${statusColor} tracking-wide`}>
                            {liveMarketState.toUpperCase()}
                        </div>
                        <div className="text-[10px] text-white/50">
                            {isImbalanced ? 'Trend Mode' : 'Range Mode'}
                        </div>
                    </div>
                    <div className="border-t border-white/5 mt-2 pt-2">
                        <div className="text-[9px] text-white/30 uppercase tracking-wider mb-1">Leg</div>
                        <div className="flex justify-between items-center">
                            <div className={`text-sm font-bold tracking-wide ${amtResult?.hasDisplacement ? 'text-orange-400' : 'text-cyan-400'}`}>
                                {amtResult?.hasDisplacement ? 'IMBALANCED' : 'BALANCED'}
                            </div>
                            <div className="text-[10px] text-white/50">
                                {amtResult?.hasDisplacement ? 'Displacement' : 'Rotation'}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* 02. LOCATION */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>02. Location</span>
                    <Target className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                    <div className="flex justify-between items-baseline">
                        <span className="text-[10px] text-white/40">VA High</span>
                        <span className="text-xs font-mono text-blue-300">{vah}</span>
                    </div>
                    <div className="flex justify-between items-baseline">
                        <span className="text-[10px] text-yellow-500/80 font-bold">POC</span>
                        <span className="text-xs font-mono text-yellow-400">{poc}</span>
                    </div>
                    <div className="flex justify-between items-baseline">
                        <span className="text-[10px] text-white/40">VA Low</span>
                        <span className="text-xs font-mono text-blue-300">{val}</span>
                    </div>
                    {amtResult?.poc && amtResult.poc > 0 && (
                        <div className="flex justify-between items-baseline pt-1 border-t border-white/5">
                            <span className="text-[10px] text-white/40">LVNs</span>
                            <span className="text-[10px] font-mono text-white/30">
                                {amtResult.lvns?.length ? amtResult.lvns.map(l => l.toFixed(0)).join(', ') : 'None'}
                            </span>
                        </div>
                    )}
                </div>
            </div>

            {/* 03. AGGRESSION */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>03. Aggression</span>
                    <Activity className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5">
                    <div className="flex justify-between mb-2">
                        <span className="text-[10px] text-white/60">Delta Score</span>
                        <span className={`text-xs font-mono font-bold ${Math.abs(aggScore) > 0.5 ? 'text-green-400' : 'text-gray-400'}`}>
                            {aggScore.toFixed(2)}
                        </span>
                    </div>
                    {/* Progress Bar */}
                    <div className="h-1 bg-white/10 rounded-full overflow-hidden flex">
                        <div style={{ width: '50%' }} className="bg-transparent border-r border-white/10"></div>
                        {/* Visual bar moving left or right based on score (-1 to 1 mapped to width) */}
                        <div className={`h-full transition-all duration-500 relative`} style={{
                            width: `${Math.min(Math.abs(aggScore) * 50, 50)}%`,
                            left: aggScore > 0 ? '0%' : `-${Math.min(Math.abs(aggScore) * 50, 50)}%`,
                            backgroundColor: aggScore > 0 ? '#4ade80' : '#f87171'
                        }}></div>
                    </div>
                </div>
            </div>

            {/* 03b. MARKET METRICS — Verification Bars */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>03b. Market Metrics</span>
                    <BarChart3 className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                    {/* OFI Bar */}
                    <div>
                        <div className="flex justify-between mb-1">
                            <span className="text-[10px] text-white/40">OFI</span>
                            <span className={`text-[10px] font-mono font-bold ${(amtResult?.ofi ?? 0) > 0 ? 'text-green-400' : (amtResult?.ofi ?? 0) < 0 ? 'text-red-400' : 'text-white/40'}`}>
                                {(amtResult?.ofi ?? 0) > 0 ? '+' : ''}{(amtResult?.ofi ?? 0).toFixed(3)}
                            </span>
                        </div>
                        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden relative">
                            <div className="absolute top-0 left-1/2 w-px h-full bg-white/20" />
                            {(amtResult?.ofi ?? 0) !== 0 && (
                                <div className="absolute top-0 h-full rounded-full transition-all duration-300" style={{
                                    left: (amtResult?.ofi ?? 0) > 0 ? '50%' : `${50 + (amtResult?.ofi ?? 0) * 50}%`,
                                    width: `${Math.min(Math.abs(amtResult?.ofi ?? 0) * 50, 50)}%`,
                                    backgroundColor: (amtResult?.ofi ?? 0) > 0 ? '#4ade80' : '#f87171',
                                    opacity: 0.7,
                                }} />
                            )}
                        </div>
                    </div>
                    {/* CVD Slope Bar */}
                    <div>
                        <div className="flex justify-between mb-1">
                            <span className="text-[10px] text-white/40">CVD Slope</span>
                            <span className={`text-[10px] font-mono font-bold ${(amtResult?.cvdSlope ?? 0) > 0 ? 'text-green-400' : (amtResult?.cvdSlope ?? 0) < 0 ? 'text-red-400' : 'text-white/40'}`}>
                                {(amtResult?.cvdSlope ?? 0).toFixed(1)}
                                {amtResult?.cvdDivergence ? ` (${amtResult.cvdDivergence.replace('_DIV', '')})` : ''}
                            </span>
                        </div>
                        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden relative">
                            <div className="absolute top-0 left-1/2 w-px h-full bg-white/20" />
                            {(() => {
                                const cvd = amtResult?.cvdSlope ?? 0;
                                const norm = Math.min(Math.abs(cvd) / 100, 1);
                                return cvd !== 0 ? (
                                    <div className="absolute top-0 h-full rounded-full transition-all duration-300" style={{
                                        left: cvd > 0 ? '50%' : `${50 - norm * 50}%`,
                                        width: `${norm * 50}%`,
                                        backgroundColor: cvd > 0 ? '#4ade80' : '#f87171',
                                        opacity: 0.7,
                                    }} />
                                ) : null;
                            })()}
                        </div>
                    </div>
                    {/* Balance Ratio Bar */}
                    <div>
                        <div className="flex justify-between mb-1">
                            <span className="text-[10px] text-white/40">Balance</span>
                            <span className="text-[10px] font-mono font-bold text-blue-300">
                                {((amtResult?.balanceRatio ?? 0) * 100).toFixed(0)}% in VA
                            </span>
                        </div>
                        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                            <div className="h-full rounded-full transition-all duration-300" style={{
                                width: `${(amtResult?.balanceRatio ?? 0) * 100}%`,
                                backgroundColor: '#60a5fa',
                                opacity: 0.6,
                            }} />
                        </div>
                    </div>
                    {/* Profile Shape + Spread + Depth row */}
                    <div className="flex justify-between items-center pt-1 border-t border-white/5">
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] text-white/40">Shape</span>
                            <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${
                                amtResult?.profileShape === 'B' ? 'bg-purple-500/20 text-purple-400' :
                                amtResult?.profileShape === 'P' ? 'bg-red-500/20 text-red-400' :
                                amtResult?.profileShape === 'b' ? 'bg-green-500/20 text-green-400' :
                                'bg-white/10 text-white/40'
                            }`}>
                                {amtResult?.profileShape === 'B' ? 'B Bimodal' :
                                 amtResult?.profileShape === 'P' ? 'P Top-heavy' :
                                 amtResult?.profileShape === 'b' ? 'b Bottom-heavy' :
                                 amtResult?.profileShape === 'D' ? 'D Balanced' : '—'}
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            {(() => {
                                const bestBid = orderBook?.bids?.[0]?.price ?? 0;
                                const bestAsk = orderBook?.asks?.[0]?.price ?? 0;
                                const mid = (bestBid + bestAsk) / 2;
                                const spreadBps = mid > 0 ? ((bestAsk - bestBid) / mid * 10000) : 0;
                                return bestBid > 0 ? (
                                    <span className={`text-[10px] font-mono ${spreadBps <= 5 ? 'text-green-400' : spreadBps <= 15 ? 'text-yellow-400' : 'text-red-400'}`}>
                                        {spreadBps.toFixed(1)} bps
                                    </span>
                                ) : <span className="text-[10px] text-white/20">—</span>;
                            })()}
                            <span className={`text-[9px] font-mono px-1 py-0.5 rounded ${depth20Active ? 'bg-green-500/20 text-green-400' : 'bg-white/5 text-white/20'}`}>
                                {depth20Active ? 'D20' : 'D5'}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* 04. PROBABILITY ENGINE */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>04. Probability</span>
                    <Brain className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                    {agentDecision ? (
                        <>
                            <div className="flex justify-between items-center">
                                <span className="text-[10px] text-white/40">Direction</span>
                                <span className={`text-xs font-bold ${agentDecision.direction === 'LONG' ? 'text-emerald-400' : agentDecision.direction === 'SHORT' ? 'text-red-400' : 'text-blue-300'}`}>
                                    {agentDecision.direction}
                                </span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-[10px] text-white/40">P(target)</span>
                                <span className={`text-xs font-mono font-bold ${agentDecision.probability >= 0.6 ? 'text-emerald-400' : agentDecision.probability >= 0.45 ? 'text-yellow-400' : 'text-red-400'}`}>
                                    {(agentDecision.probability * 100).toFixed(1)}%
                                </span>
                            </div>
                            {/* Probability bar */}
                            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                                <div className="h-full rounded-full transition-all duration-500" style={{
                                    width: `${Math.min(agentDecision.probability * 100, 100)}%`,
                                    backgroundColor: agentDecision.probability >= 0.6 ? '#4ade80' : agentDecision.probability >= 0.45 ? '#facc15' : '#f87171',
                                }} />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-[10px] text-white/40">Regime</span>
                                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                                    agentDecision.regime === 'TRENDING' ? 'bg-purple-500/20 text-purple-400' :
                                    agentDecision.regime === 'BALANCED' ? 'bg-blue-500/20 text-blue-400' :
                                    agentDecision.regime === 'VOLATILE' ? 'bg-orange-500/20 text-orange-400' :
                                    'bg-white/10 text-white/40'
                                }`}>{agentDecision.regime}</span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-[10px] text-white/40">Timing</span>
                                <span className={`text-[10px] font-mono ${agentDecision.timing === 'ENTER_NOW' ? 'text-emerald-400' : 'text-yellow-400'}`}>
                                    {agentDecision.timing}
                                </span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-[10px] text-white/40">Kelly Size</span>
                                <span className="text-[10px] font-mono text-white/60">{(agentDecision.sizeFraction * 100).toFixed(1)}%</span>
                            </div>
                            <div className="text-[9px] text-white/30 font-mono pt-1 border-t border-white/5">
                                {agentDecision.rationale} ({agentDecision.latencyUs}μs)
                            </div>
                        </>
                    ) : (
                        <div className="text-[10px] text-white/30 text-center py-2">Waiting for probability engine...</div>
                    )}
                </div>
            </div>

            {/* Footer Status */}
            <div className="mt-2 text-xs text-white/40 flex items-start gap-2 pt-2 border-t border-white/5">
                <div className={`mt-1 h-2 w-2 rounded-full ${displayAnalysis.direction !== 'FLAT' ? 'bg-green-500 animate-ping' : 'bg-slate-600'}`}></div>
                <div className="flex-1 min-w-0">
                    <div className="font-bold text-white/80 uppercase tracking-wider mb-1">
                        {displayAnalysis.direction === 'FLAT' ? "MONITORING MARKET" : `ENTRY SIGNAL: ${displayAnalysis.direction}`}
                    </div>
                    <p className="leading-relaxed font-light text-[10px] line-clamp-3">
                        {displayAnalysis.rationale.split('Trigger:')[0].trim() || "Analyzing order flow and market structure for Fabio Playbook setups."}
                    </p>
                </div>
            </div>

            {/* 04. MODEL I/O LOG */}
            <div className="flex flex-col gap-2 pt-2 border-t border-white/5">
                <div className="text-[10px] text-white/40 uppercase tracking-widest">05. Model I/O</div>
                <div className="p-2 rounded-lg bg-black/30 border border-white/5 space-y-2 max-h-[200px] overflow-y-auto">
                    <div>
                        <div className="text-[9px] text-cyan-400/60 uppercase font-bold mb-1">Prompt → Model</div>
                        <div className="text-[9px] font-mono text-white/50 leading-relaxed whitespace-pre-wrap break-words">
                            {displayAnalysis.inputPrompt || "Waiting for first LLM call..."}
                        </div>
                    </div>
                    <div className="border-t border-white/5 pt-2">
                        <div className="text-[9px] text-amber-400/60 uppercase font-bold mb-1">Model → Output</div>
                        <div className="text-[9px] font-mono text-white/50 leading-relaxed whitespace-pre-wrap break-words">
                            {displayAnalysis.rawOutput || "No output yet."}
                        </div>
                    </div>
                </div>
            </div>

            {/* 05. LLM DECISION HISTORY */}
            {llmHistory.length > 0 && (
                <div className="flex flex-col gap-2 pt-2 border-t border-white/5">
                    <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                        <span>06. Decision History ({llmHistory.length})</span>
                        <Clock className="w-3 h-3" />
                    </div>
                    <div className="space-y-1 max-h-[250px] overflow-y-auto">
                        {[...llmHistory].reverse().map((entry, i) => {
                            const dirColor = entry.direction === 'LONG' ? 'text-green-400' : entry.direction === 'SHORT' ? 'text-red-400' : 'text-blue-300';
                            const dirBg = entry.direction === 'LONG' ? 'border-green-500/20' : entry.direction === 'SHORT' ? 'border-red-500/20' : 'border-white/5';
                            const timeStr = new Date(entry.timestamp).toLocaleTimeString();
                            return (
                                <details key={i} className={`p-2 rounded-lg bg-black/20 border ${dirBg} cursor-pointer`}>
                                    <summary className="flex justify-between items-center text-[10px]">
                                        <div className="flex items-center gap-2">
                                            <span className={`font-bold ${dirColor}`}>{entry.direction}</span>
                                            <span className="text-white/30">{entry.confidence}</span>
                                        </div>
                                        <span className="text-white/30 font-mono">{timeStr}</span>
                                    </summary>
                                    <div className="mt-2 space-y-2">
                                        <div className="text-[9px] text-white/50 leading-relaxed">{entry.rationale}</div>
                                        {entry.inputPrompt && (
                                            <div>
                                                <div className="text-[9px] text-cyan-400/60 uppercase font-bold mb-1">Prompt</div>
                                                <div className="text-[9px] font-mono text-white/40 whitespace-pre-wrap break-words max-h-[100px] overflow-y-auto">{entry.inputPrompt}</div>
                                            </div>
                                        )}
                                        {entry.rawOutput && (
                                            <div>
                                                <div className="text-[9px] text-amber-400/60 uppercase font-bold mb-1">Output</div>
                                                <div className="text-[9px] font-mono text-white/40 whitespace-pre-wrap break-words max-h-[100px] overflow-y-auto">{entry.rawOutput}</div>
                                            </div>
                                        )}
                                    </div>
                                </details>
                            );
                        })}
                    </div>
                </div>
            )}

        </div>
    );
};
