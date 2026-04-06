import React, { useMemo } from 'react';
import { GenAIAnalysis, AMTAnalysis, Portfolio, RiskState, LLMHistoryEntry, AgentDecision, OrderBook } from '../types';
import { Brain, TrendingUp, TrendingDown, MinusCircle, Target, Activity, Settings, Zap, AlertTriangle, Clock, BarChart3, Shield, Eye, Layers, ArrowUpDown, Crosshair, Navigation } from 'lucide-react';
import { EquityPanel, RiskStateDisplay, ModelIOPanel, DecisionHistoryPanel } from './ai';
import { sanitizeLlmText, sanitizeRationale } from '../utils/textSanitizer';

interface AIAnalysisPanelProps {
    analysis: GenAIAnalysis | null;
    amtResult: AMTAnalysis | null;
    portfolio: Portfolio;
    riskState?: RiskState | null;
    agentDecision?: AgentDecision | null;
    llmHistory?: LLMHistoryEntry[];
    orderBook?: OrderBook | null;
    depth20Active?: boolean;
    overseerAction?: string;
    overseerReason?: string;
}

const AIAnalysisPanelInner: React.FC<AIAnalysisPanelProps> = ({ analysis, amtResult, portfolio, riskState, agentDecision, llmHistory = [], orderBook, depth20Active, overseerAction, overseerReason }) => {
    // Determine current best price proxy (LTP) with 3-tier fallback chain.
    // Tier 1: Order book mid-price (most accurate, requires depth data)
    // Tier 2: Session VWAP from AMT analysis (always available after first tick)
    // Tier 3: 0 (no data available — location section shows "Building...")
    const currentLtp = React.useMemo(() => {
        if (orderBook?.bids?.[0]?.price > 0 && orderBook?.asks?.[0]?.price > 0) {
            return (orderBook.bids[0].price + orderBook.asks[0].price) / 2;
        }
        if (amtResult?.sessionVwap > 0) {
            return amtResult.sessionVwap;
        }
        return 0;
    }, [orderBook, amtResult?.sessionVwap]);

    // 2. Monitoring Mode: AMT ready, but no GenAI signal yet
    // We construct a "dummy" analysis object from AMT data to render the panel in "Monitoring" mode
    // MODIFIED: Use new reasoning model data if available!
    const effectiveAnalysis = useMemo<GenAIAnalysis>(() => {
        if (analysis) return analysis;
        
        return {
            direction: 'FLAT',
            rationale: amtResult?.llmThinking || "Monitoring market state and order flow. Waiting for Fabio Playbook setup.",
            confidence: 'Low',
            marketState: amtResult?.marketState || 'BALANCED',
            aggression: `Score:${amtResult?.aggression?.toFixed(2) || "0.00"}`,
            rawOutput: amtResult?.llmThinking || "",
            inputPrompt: "Reasoning Model Analysis" // Placeholder for now
        };
    }, [analysis, amtResult?.marketState, amtResult?.aggression, amtResult?.llmThinking]);

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

    return (
        <div className="bg-[#131722] border border-white/10 rounded-xl p-4 flex flex-col gap-4 font-sans text-slate-200 shadow-xl">

            {/* 0. Header (Sticky Top Bar) */}
            <div className="sticky top-0 z-20 bg-[#131722]/95 backdrop-blur-xl pb-3 mb-2 border-b border-white/10">
                <div className="flex justify-between items-start mb-3 pt-2">
                    <div className="flex items-center gap-2">
                        <Zap className="w-5 h-5 text-purple-400 fill-purple-400/20" />
                        <div>
                            <h2 className="text-sm font-bold tracking-wider text-white uppercase flex items-center gap-2">
                                Fabio Playbook
                                <span className="px-1.5 py-0.5 bg-blue-600/20 rounded border border-blue-500/30 text-[9px] text-blue-400 uppercase tracking-widest leading-none">
                                    {portfolio.leverage}x
                                </span>
                            </h2>
                            <div className="text-[10px] text-white/40 font-mono tracking-widest uppercase">Execution Engine</div>
                        </div>
                    </div>
                </div>

                {/* Engine Bar */}
                <div className="mb-3 px-3 py-2 bg-black/40 border-y border-white/5 flex flex-col justify-between items-center text-xs backdrop-blur-sm gap-2">
                    <div className="flex justify-between items-center w-full">
                        <div className="flex items-center gap-2 px-1.5 py-0.5 bg-emerald-500/10 border border-emerald-500/20 rounded">
                            <Shield className="w-3 h-3 text-emerald-400" />
                            <span className="text-emerald-400 font-bold tracking-widest text-[9px]">[ENGINE ARMED]</span>
                        </div>
                        <span className="text-white/40 text-[9px] uppercase tracking-wider cursor-pointer hover:text-white/80 transition-colors">Target vs Circuit</span>
                    </div>
                    {/* Target / Circuit Mini Progress Bar */}
                    <div className="w-full">
                        <div className="flex justify-between text-[8px] font-mono text-white/40 mb-1">
                            <span>-₹30K (Circuit)</span>
                            <span>+₹15K (Target)</span>
                        </div>
                        <div className="h-1 bg-white/10 rounded-full overflow-hidden flex relative">
                            <div className="absolute top-0 left-1/2 w-px h-full bg-white/20 z-10" />
                            {(() => {
                                const maxAbs = 30000;
                                const currentPnl = portfolio.equity - portfolio.balance;
                                const norm = Math.min(Math.abs(currentPnl) / maxAbs, 1);
                                return (
                                    <div className="h-full absolute transition-all duration-500 rounded-full" style={{
                                        width: `${norm * 50}%`,
                                        left: currentPnl > 0 ? '50%' : `${50 - norm * 50}%`,
                                        backgroundColor: currentPnl > 0 ? '#4ade80' : '#f87171'
                                    }} />
                                );
                            })()}
                        </div>
                    </div>
                </div>

                {/* Equity Panel (Header) */}
                <EquityPanel portfolio={portfolio} openPnl={openPnl} />

                {/* Risk State Warning */}
                <RiskStateDisplay riskState={riskState} />

                {/* LLM Timeout / Quant Only Banner */}
                {!analysis && amtResult && (
                    <div className="mt-2 px-3 py-1.5 bg-amber-500/10 border border-amber-500/20 rounded flex items-center gap-2 animate-pulse">
                        <Clock className="w-3.5 h-3.5 text-amber-400" />
                        <span className="text-[10px] font-bold text-amber-400 uppercase tracking-wider">
                            LLM Timeout — Running on Quant Logic Only
                        </span>
                    </div>
                )}
            </div>

            {/* 01. STATE */}
            <div className="flex flex-col gap-2 relative">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest absolute -top-2 right-1 z-10 bg-[#131722] px-1">
                    <Settings className="w-3 h-3 hover:text-white/80 transition-colors cursor-pointer" />
                </div>
                <div className={`p-3 rounded-lg bg-white/5 border border-white/10 relative overflow-hidden flex flex-col gap-2`}>
                    <div className={`absolute top-0 left-0 w-1 h-full ${statusBg.replace('20', '50').replace('bg-', 'bg-')}`} />
                    
                    <div className="flex items-center justify-between ml-2">
                        <span className="text-[10px] text-white/40 uppercase tracking-widest font-bold">Session & Leg</span>
                        <div className="flex items-center gap-2">
                            <div className={`px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide flex items-center gap-1.5 ${statusBg} ${statusColor}`}>
                                <span className="text-white/40 font-normal">SESSION</span>
                                <div className={`w-1.5 h-1.5 rounded-full ${isImbalanced ? 'bg-orange-400' : liveMarketState === 'PROBING' ? 'bg-blue-400' : 'bg-yellow-400'}`} />
                                {liveMarketState.toUpperCase()}
                            </div>
                            <div className={`px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide flex items-center gap-1.5 ${amtResult?.hasDisplacement ? 'bg-orange-500/20 text-orange-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                                <span className="text-white/40 font-normal">LEG</span>
                                <div className={`w-1.5 h-1.5 rounded-full ${amtResult?.hasDisplacement ? 'bg-orange-400' : 'bg-yellow-400'}`} />
                                {amtResult?.hasDisplacement ? 'DISPLACEMENT' : 'BALANCED'}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* 02. LOCATION */}
            <div className="flex flex-col gap-2">
                <div className="p-3 rounded-lg bg-white/5 border border-white/10 relative">
                    <span className="absolute -top-2 left-2 px-1 bg-[#131722] text-[10px] text-white/40 uppercase tracking-widest font-bold">Location</span>
                    
                    {currentLtp > 0 && (amtResult?.poc !== undefined && amtResult?.poc !== null) && amtResult?.valueAreaLow && amtResult?.valueAreaHigh ? (
                        <div className="mt-3 relative h-12 flex items-center justify-center">
                            {(() => {
                                const min = Math.min(amtResult.valueAreaLow, currentLtp) * 0.999;
                                const max = Math.max(amtResult.valueAreaHigh, currentLtp) * 1.001;
                                const range = max - min;
                                const getPos = (val: number) => `${Math.max(5, Math.min(95, ((val - min) / range) * 100))}%`;
                                
                                return (
                                    <div className="w-full relative h-1">
                                        {/* Base Track */}
                                        <div className="absolute top-0 left-0 w-full h-full bg-white/10 rounded-full"></div>
                                        {/* VA Fill */}
                                        <div className="absolute top-0 h-full bg-blue-500/20" style={{ left: getPos(amtResult.valueAreaLow), width: `${((amtResult.valueAreaHigh - amtResult.valueAreaLow) / range) * 100}%` }}></div>
                                        
                                        {/* VAH Marker */}
                                        <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: getPos(amtResult.valueAreaHigh) }}>
                                            <div className="w-0.5 h-3 bg-blue-400"></div>
                                            <span className="text-[8px] text-blue-400 mt-1 absolute top-3">VAH</span>
                                        </div>
                                        {/* VAL Marker */}
                                        <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: getPos(amtResult.valueAreaLow) }}>
                                            <div className="w-0.5 h-3 bg-blue-400"></div>
                                            <span className="text-[8px] text-blue-400 mt-1 absolute top-3">VAL</span>
                                        </div>
                                        {/* POC Marker */}
                                        <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center z-10" style={{ left: getPos(amtResult.poc) }}>
                                            <div className="w-2 h-2 rounded-full bg-yellow-400 shadow-[0_0_8px_rgba(250,204,21,0.5)]"></div>
                                            <span className="text-[9px] font-bold text-yellow-400 mt-1 absolute top-2 flex flex-col items-center">
                                                <span>POC</span>
                                                <span className="font-mono">{poc}</span>
                                            </span>
                                        </div>
                                        {/* LTP Marker */}
                                        <div className="absolute top-1/2 -translate-y-[120%] flex flex-col items-center z-20" style={{ left: getPos(currentLtp) }}>
                                            <div className="px-1.5 py-0.5 bg-white text-black text-[9px] font-bold font-mono rounded shadow-lg flex items-center gap-1 mb-1">
                                                {currentLtp.toFixed(1)} <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
                                            </div>
                                            <div className="w-px h-3 bg-white"></div>
                                        </div>
                                    </div>
                                );
                            })()}
                        </div>
                    ) : (
                        <div className="text-center text-[10px] text-white/30 py-4 font-mono">Building Volume Profile...</div>
                    )}
                </div>
            </div>

            {/* 03. AGGRESSION */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>03. Volume Aggression</span>
                    <Activity className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5">
                    <div className="flex justify-between items-end mb-2">
                        <div className="flex flex-col">
                            <span className="text-[10px] text-white/60 mb-0.5">Delta Score</span>
                            <span className={`text-[9px] font-bold tracking-wider ${aggScore > 0 ? 'text-green-400' : aggScore < 0 ? 'text-red-400' : 'text-white/40'}`}>
                                {aggScore > 0 ? '[BULLS IN CONTROL]' : aggScore < 0 ? '[BEARS IN CONTROL]' : '[NEUTRAL]'}
                            </span>
                        </div>
                        <span className={`text-xs font-mono font-bold ${aggScore > 0 ? 'text-green-400' : aggScore < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                            {aggScore > 0 ? '+' : ''}{aggScore.toFixed(2)}
                        </span>
                    </div>
                    {/* Progress Bar */}
                    <div className="h-1 bg-white/10 rounded-full overflow-hidden flex relative">
                        <div className="absolute top-0 left-1/2 w-px h-full bg-white/20 z-10" />
                        {/* Visual bar moving left or right based on score */}
                        <div className={`h-full absolute transition-all duration-500 rounded-full`} style={{
                            width: `${Math.min(Math.abs(aggScore) * 50, 50)}%`,
                            left: aggScore > 0 ? '50%' : `${50 - Math.min(Math.abs(aggScore) * 50, 50)}%`,
                            backgroundColor: aggScore > 0 ? '#4ade80' : '#f87171'
                        }}></div>
                    </div>
                </div>
            </div>

            {/* 03b. MARKET METRICS — Verification Bars */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>03B. Market Metrics</span>
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                    {/* OFI Bar */}
                    <div>
                        <div className="flex justify-between mb-1">
                            <span className="text-[10px] text-white/40">OFI</span>
                            <div className="flex items-center gap-1.5">
                                <span className={`text-[10px] ${(amtResult?.ofi ?? 0) > 0 ? 'text-green-400' : (amtResult?.ofi ?? 0) < 0 ? 'text-red-400' : 'text-white/40'}`}>
                                    {(amtResult?.ofi ?? 0) > 0 ? '╱╲↗' : (amtResult?.ofi ?? 0) < 0 ? '╲╱↘' : '—'}
                                </span>
                                <span className={`text-[10px] font-mono font-bold ${(amtResult?.ofi ?? 0) > 0 ? 'text-green-400' : (amtResult?.ofi ?? 0) < 0 ? 'text-red-400' : 'text-white/40'}`}>
                                    {(amtResult?.ofi ?? 0) > 0 ? '+' : ''}{(amtResult?.ofi ?? 0).toFixed(3)}
                                </span>
                            </div>
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
                            <div className="flex items-center gap-1.5">
                                <span className={`text-[10px] ${(amtResult?.cvdSlope ?? 0) > 0 ? 'text-green-400' : (amtResult?.cvdSlope ?? 0) < 0 ? 'text-red-400' : 'text-white/40'}`}>
                                    {(amtResult?.cvdSlope ?? 0) > 0 ? '╱╲↗' : (amtResult?.cvdSlope ?? 0) < 0 ? '╲╱↘' : '—'}
                                </span>
                                <span className={`text-[10px] font-mono font-bold ${(amtResult?.cvdSlope ?? 0) > 0 ? 'text-green-400' : (amtResult?.cvdSlope ?? 0) < 0 ? 'text-red-400' : 'text-white/40'}`}>
                                    {(amtResult?.cvdSlope ?? 0) > 0 ? '+' : ''}{(amtResult?.cvdSlope ?? 0).toFixed(1)}
                                    {amtResult?.cvdDivergence ? ` (${amtResult.cvdDivergence.replace('_DIV', '')})` : ''}
                                    {Math.abs(amtResult?.cvdSlope ?? 0) > 500 ? ((amtResult?.cvdSlope ?? 0) > 0 ? ' (BULLISH)' : ' (BEARISH)') : ''}
                                </span>
                            </div>
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
                    {/* Balance / Price Location */}
                    <div>
                        <div className="flex justify-between mb-1">
                            <span className="text-[10px] text-white/40">Balance</span>
                            {(() => {
                                const ltp = amtResult?.sessionVwap ?? 0;
                                const vah = amtResult?.valueAreaHigh ?? 0;
                                const val = amtResult?.valueAreaLow ?? 0;
                                const ratio = (amtResult?.balanceRatio ?? 0) * 100;
                                if (ltp > 0 && vah > 0 && ltp > vah) {
                                    return <span className="text-[10px] font-mono font-bold text-orange-400">0% in VA (Above ↑)</span>;
                                } else if (ltp > 0 && val > 0 && ltp < val) {
                                    return <span className="text-[10px] font-mono font-bold text-red-400">0% in VA (Below ↓)</span>;
                                } else if (ratio >= 50 && ratio <= 70) {
                                    return <span className="text-[10px] font-mono font-bold text-yellow-400">{ratio.toFixed(0)}% in VA (TRANSITIONING)</span>;
                                } else {
                                    return <span className="text-[10px] font-mono font-bold text-blue-300">{ratio.toFixed(0)}% in VA</span>;
                                }
                            })()}
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
                            <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${amtResult?.profileShape === 'B' ? 'bg-purple-500/20 text-purple-400' :
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
                            <span title="Order Book Depth" className={`text-[9px] font-mono px-1 py-0.5 rounded ${depth20Active ? 'bg-green-500/20 text-green-400' : 'bg-white/5 text-white/20'}`}>
                                {depth20Active ? 'Depth-20' : 'Depth-5'}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* 03c. MARKET STRUCTURE */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>03c. Structure</span>
                    <Layers className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2 relative overflow-hidden">
                    <div className="flex justify-between items-center">
                        <div className="flex items-center gap-3">
                            {/* CSS Donut Chart */}
                            {(() => {
                                const conf = amtResult?.structureConfidence ?? 0;
                                const color = conf >= 70 ? '#4ade80' : conf >= 40 ? '#facc15' : '#f87171';
                                return (
                                    <div className="relative w-10 h-10 rounded-full flex items-center justify-center shrink-0" 
                                         style={{ background: `conic-gradient(${color} ${conf}%, rgba(255,255,255,0.05) 0)` }}>
                                        <div className="absolute inset-1 bg-[#202532] rounded-full flex items-center justify-center">
                                            <span className="text-[10px] font-mono font-bold text-white/90">{conf}%</span>
                                        </div>
                                    </div>
                                );
                            })()}
                            <div className="flex flex-col">
                                <span className={`text-xs font-bold tracking-wider ${amtResult?.marketStructure === 'TREND_UP' ? 'text-emerald-400' :
                                    amtResult?.marketStructure === 'TREND_DOWN' ? 'text-red-400' :
                                        amtResult?.marketStructure === 'BREAKOUT' ? 'text-orange-400' :
                                            amtResult?.marketStructure === 'BREAKDOWN' ? 'text-rose-400' :
                                                'text-blue-300'
                                    }`}>
                                    {amtResult?.marketStructure || 'BALANCE'}
                                </span>
                                <span className="text-[9px] text-white/40 uppercase">Structure</span>
                            </div>
                        </div>
                        {((amtResult?.structureConfidence ?? 0) >= 70 && (amtResult?.structureConfidence ?? 0) <= 80) && (
                            <div className="absolute top-2 right-2 px-1.5 py-0.5 bg-yellow-500/10 border border-yellow-500/20 rounded text-[8px] text-yellow-400 font-bold animate-pulse">
                                WAIT FOR REJECTION
                            </div>
                        )}
                    </div>
                    {/* Acceptance / Rejection signals */}
                    <div className="flex gap-2 flex-wrap pt-1">
                        {amtResult?.acceptanceAbove && (
                            <span className="text-[8px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/20">ACCEPTANCE ↑</span>
                        )}
                        {amtResult?.acceptanceBelow && (
                            <span className="text-[8px] font-mono px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/20">ACCEPTANCE ↓</span>
                        )}
                        {amtResult?.rejectionAtHigh && (
                            <span className="text-[8px] font-mono px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400 border border-yellow-500/20">REJECTION @ HIGH</span>
                        )}
                        {amtResult?.rejectionAtLow && (
                            <span className="text-[8px] font-mono px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400 border border-yellow-500/20">REJECTION @ LOW</span>
                        )}
                        {!amtResult?.acceptanceAbove && !amtResult?.acceptanceBelow && !amtResult?.rejectionAtHigh && !amtResult?.rejectionAtLow && (
                            <span className="text-[8px] text-white/20">No acceptance/rejection signals</span>
                        )}
                    </div>
                </div>
            </div>

            {/* 03d. INITIAL BALANCE + BREAKS */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>03d. IB + Breaks</span>
                    <Crosshair className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                    {/* Initial Balance Range Band */}
                    <div className="flex justify-between items-center">
                        <span className="text-[10px] text-white/40">IB Range</span>
                        <span className="flex items-center gap-2">
                            {amtResult?.ibHigh && amtResult?.ibLow ? (
                                <span className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-[10px] font-mono text-white/70">
                                    {amtResult.ibLow.toFixed(2)} <span className="text-white/20 mx-1">──</span> {amtResult.ibHigh.toFixed(2)}
                                </span>
                            ) : (
                                <span className="text-[10px] font-mono text-white/40">Building...</span>
                            )}
                            
                            {amtResult?.ibComplete && (
                                <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wider ${amtResult?.breakDirection ? 'bg-orange-500/20 text-orange-400' : 'bg-emerald-500/20 text-emerald-400'}`}>
                                    {amtResult?.breakDirection ? `BROKEN ${amtResult.breakDirection === 'UP' ? '↑' : '↓'}` : '✅ INTACT'}
                                </span>
                            )}
                        </span>
                    </div>
                    {/* Proximity Warning */}
                    {(() => {
                        if (currentLtp > 0 && amtResult?.ibHigh && amtResult?.ibLow && amtResult?.ibComplete && !amtResult?.breakDirection) {
                            const ibRange = amtResult.ibHigh - amtResult.ibLow;
                            const threshold = ibRange * 0.1;
                            if (Math.abs(currentLtp - amtResult.ibHigh) <= threshold) {
                                return <div className="text-[9px] font-mono font-bold text-yellow-400 bg-yellow-500/10 px-1.5 py-0.5 rounded mt-1 mb-2 inline-block">Proximity to IB High — Prepare for Bounce/Break</div>;
                            } else if (Math.abs(currentLtp - amtResult.ibLow) <= threshold) {
                                return <div className="text-[9px] font-mono font-bold text-yellow-400 bg-yellow-500/10 px-1.5 py-0.5 rounded mt-1 mb-2 inline-block">Proximity to IB Low — Prepare for Bounce/Break</div>;
                            }
                        }
                        return null;
                    })()}
                    {/* Break Detection */}
                    {amtResult?.breakDirection ? (
                        <div className={`px-2 py-1.5 rounded border flex items-center justify-between ${amtResult.breakType === 'INITIATIVE' ? 'bg-orange-500/10 border-orange-500/20' :
                            amtResult.breakType === 'RESPONSIVE' ? 'bg-cyan-500/10 border-cyan-500/20' :
                                'bg-purple-500/10 border-purple-500/20'
                            }`}>
                            <div className="flex items-center gap-1.5">
                                <Navigation className={`w-3 h-3 ${amtResult.breakDirection === 'UP' ? 'text-emerald-400 rotate-0' : 'text-red-400 rotate-180'}`} />
                                <span className={`text-[9px] font-bold uppercase ${amtResult.breakType === 'INITIATIVE' ? 'text-orange-400' :
                                    amtResult.breakType === 'RESPONSIVE' ? 'text-cyan-400' :
                                        'text-purple-400'
                                    }`}>{amtResult.breakType} BREAK {amtResult.breakDirection}</span>
                            </div>
                            <span className="text-[9px] font-mono text-white/40">@ {amtResult.breakLevel?.toFixed(2)}</span>
                        </div>
                    ) : (
                        <div className="text-[9px] text-white/20">No break detected</div>
                    )}
                    {/* POC Migration */}
                    {amtResult?.pocSignal && (
                        <div className="flex justify-between items-center pt-1 border-t border-white/5">
                            <span className="text-[10px] text-white/40">POC Signal</span>
                            <span className={`text-[9px] font-mono font-bold ${amtResult.pocSignal.includes('BULLISH') ? 'text-emerald-400' :
                                amtResult.pocSignal.includes('BEARISH') ? 'text-red-400' :
                                    'text-yellow-400'
                                }`}>{amtResult.pocSignal.replace('POC_', '').replace('_', ' ')}</span>
                        </div>
                    )}
                    {amtResult?.pocVsPrice && (
                        <div className="flex justify-between items-center">
                            <span className="text-[10px] text-white/40">POC vs Price</span>
                            <span className={`text-[9px] font-mono ${amtResult.pocVsPrice === 'ALIGNED' ? 'text-green-400' : 'text-yellow-400'}`}>
                                {amtResult.pocVsPrice}
                            </span>
                        </div>
                    )}
                </div>
            </div>

            {/* 03e. LVN VELOCITY PLAY */}
            {amtResult?.lvnPlay && (
                <div className="flex flex-col gap-2">
                    <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                        <span>03e. LVN Play</span>
                        <ArrowUpDown className="w-3 h-3 text-amber-400" />
                    </div>
                    <div className="p-3 rounded-lg bg-amber-500/5 border border-amber-500/20 space-y-1.5">
                        <div className="flex justify-between items-center">
                            <span className={`text-xs font-bold ${amtResult.lvnPlay.direction === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>
                                {amtResult.lvnPlay.direction} @ LVN {amtResult.lvnPlay.lvn_price.toFixed(2)}
                            </span>
                            <span className="text-[9px] font-mono text-white/40">
                                Vol: {amtResult.lvnPlay.velocity_ratio.toFixed(1)}x
                            </span>
                        </div>
                        <div className="flex justify-between text-[9px]">
                            <span className="text-white/40">Target: <span className="text-yellow-400 font-mono">{amtResult.lvnPlay.target.toFixed(2)}</span></span>
                            <div className="flex gap-1.5">
                                {amtResult.lvnPlay.has_rejection && <span className="text-orange-400">Rejection</span>}
                                {amtResult.lvnPlay.has_delta_flip && <span className="text-purple-400">Delta Flip</span>}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* 03f. VWAP + PRIOR DAY */}
            {(amtResult?.sessionVwap ?? 0) > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                        <span>03e. VWAP + Context</span>
                    </div>
                    <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-1.5 text-[9px]">
                        <div className="flex justify-between">
                            <span className="text-white/40">Session VWAP</span>
                            <span className="font-mono text-cyan-400">{amtResult?.sessionVwap?.toFixed(2)}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-red-400/80 font-bold">+2σ / +1σ</span>
                            <span className="font-mono text-red-300">
                                {amtResult?.vwapUpper2?.toFixed(2)} / {amtResult?.vwapUpper1?.toFixed(2)}
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-emerald-400/80 font-bold">-1σ / -2σ</span>
                            <span className="font-mono text-emerald-300">
                                {amtResult?.vwapLower1?.toFixed(2)} / {amtResult?.vwapLower2?.toFixed(2)}
                            </span>
                        </div>
                        
                        {/* Inline Deviation Meter (-3σ to +3σ) */}
                        {currentLtp > 0 && amtResult?.sessionVwap && (
                            <div className="pt-3 pb-1 border-t border-white/5">
                                <div className="flex justify-between text-[8px] font-mono text-white/30 mb-1">
                                    <span className="text-emerald-400">-3σ</span>
                                    <span>VWAP</span>
                                    <span className="text-red-400">+3σ</span>
                                </div>
                                <div className="h-1.5 relative bg-white/5 rounded-full">
                                    <div className="absolute top-0 left-1/2 w-0.5 h-full bg-cyan-400"></div>
                                    <div className="absolute top-0 left-[33.3%] w-px h-full bg-emerald-500/30"></div>
                                    <div className="absolute top-0 left-[16.6%] w-px h-full bg-emerald-500/50"></div>
                                    <div className="absolute top-0 right-[33.3%] w-px h-full bg-red-500/30"></div>
                                    <div className="absolute top-0 right-[16.6%] w-px h-full bg-red-500/50"></div>
                                    
                                    {(() => {
                                        const diff = currentLtp - amtResult.sessionVwap;
                                        const stdDev = amtResult.vwapUpper1 ? (amtResult.vwapUpper1 - amtResult.sessionVwap) : 0;
                                        if (stdDev > 0) {
                                            const sigma = diff / stdDev;
                                            // Map -3 to +3 to 0% to 100%
                                            const percentage = Math.max(0, Math.min(100, ((sigma + 3) / 6) * 100));
                                            return (
                                                <div 
                                                    className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-white shadow-[0_0_5px_white] z-10"
                                                    style={{ left: `calc(${percentage}% - 4px)` }}
                                                />
                                            );
                                        }
                                        return null;
                                    })()}
                                </div>
                                {(() => {
                                    const diff = currentLtp - amtResult.sessionVwap;
                                    const stdDev = amtResult.vwapUpper1 ? (amtResult.vwapUpper1 - amtResult.sessionVwap) : 0;
                                    if (stdDev > 0) {
                                        const sigma = diff / stdDev;
                                        const isExtreme = Math.abs(sigma) >= 1.8;
                                        return (
                                            <div className={`mt-2 text-center text-[9px] font-mono font-bold flex flex-col items-center gap-1 ${sigma > 1 ? 'text-red-400' : sigma < -1 ? 'text-emerald-400' : 'text-yellow-400'}`}>
                                                <span>LTP is {sigma > 0 ? '+' : ''}{sigma.toFixed(2)}σ from VWAP</span>
                                                {isExtreme && (
                                                    <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 border border-red-500/30 rounded text-[8px] animate-pulse">
                                                        EXTREME DEVIATION - FADE ZONES ACTIVE
                                                    </span>
                                                )}
                                            </div>
                                        );
                                    }
                                    return <div className="mt-2 text-center text-[9px] text-white/40">Calculating σ...</div>;
                                })()}
                            </div>
                        )}
                        {(amtResult?.priorPoc ?? 0) > 0 && (
                            <>
                                <div className="border-t border-white/5 pt-1.5 flex justify-between">
                                    <span className="text-white/40">Prior POC</span>
                                    <span className="font-mono text-yellow-400/70">{amtResult?.priorPoc?.toFixed(2)}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-white/30">Prior VA</span>
                                    <span className="font-mono text-white/30">
                                        {amtResult?.priorVal?.toFixed(2)} — {amtResult?.priorVah?.toFixed(2)}
                                    </span>
                                </div>
                            </>
                        )}
                        {amtResult?.gapType && (
                            <div className="flex justify-between">
                                <span className="text-white/40">Gap</span>
                                <span className={`font-mono font-bold ${amtResult.gapType === 'LARGE' ? 'text-red-400' :
                                    amtResult.gapType === 'MEDIUM' ? 'text-orange-400' : 'text-white/50'
                                    }`}>{amtResult.gapType}</span>
                            </div>
                        )}
                        {amtResult?.openingBias && (
                            <div className="flex justify-between">
                                <span className="text-white/40">Opening Bias</span>
                                <span className={`font-mono font-bold ${amtResult.openingBias === 'LONG_BIAS' ? 'text-emerald-400' :
                                    amtResult.openingBias === 'SHORT_BIAS' ? 'text-red-400' : 'text-white/50'
                                    }`}>{amtResult.openingBias.replace('_BIAS', '')}</span>
                            </div>
                        )}
                        {(amtResult?.priceVelocity ?? 0) > 0 && (
                            <div className="flex justify-between">
                                <span className="text-white/40">Price Velocity</span>
                                <span className="font-mono text-white/50">{amtResult?.priceVelocity?.toFixed(4)}/s</span>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* 04. PROBABILITY ENGINE */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>04. Probability</span>
                    <Brain className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2 relative overflow-hidden">
                    {agentDecision ? (
                        <>
                            <div className={`absolute top-0 left-0 w-1 h-full ${agentDecision.timing === 'ENTER_NOW' ? 'bg-emerald-500' : 'bg-yellow-500/50'}`} />
                            <div className="flex justify-between items-center pl-2">
                                <span className="text-[10px] text-white/40">Direction</span>
                                <span className={`text-xs font-bold ${agentDecision.direction === 'LONG' ? 'text-emerald-400' : agentDecision.direction === 'SHORT' ? 'text-red-400' : 'text-blue-300'}`}>
                                    {agentDecision.direction}
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
            </div>

            {/* 04b. OVERSEER */}
            {(overseerAction || portfolio.positions.length > 0) && (
                <div className="flex flex-col gap-2">
                    <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                        <span>04b. Overseer</span>
                        <Eye className="w-3 h-3 hover:text-white/80 transition-colors" />
                    </div>
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
                </div>
            )}

            {/* 04c. TRADE PLAN — Open Positions with SL/TP/Trail */}
            {portfolio.positions.filter(p => p.status === 'OPEN').length > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                        <span>04c. Trade Plan</span>
                        <Shield className="w-3 h-3 hover:text-white/80 transition-colors" />
                    </div>
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
            )}

            {/* Recent Closed Trades */}
            {portfolio.closedTrades.length > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="text-[10px] text-white/40 uppercase tracking-widest">
                        Recent Exits ({portfolio.closedTrades.length})
                    </div>
                    <div className="space-y-1.5 max-h-[180px] overflow-y-auto">
                        {[...portfolio.closedTrades].reverse().slice(0, 5).map((t, i) => {
                            const partialPnl = t.partialRealizedPnl || 0;
                            const totalPnl = t.pnl;
                            const hadPartial = partialPnl > 0;
                            const duration = t.exitTime && t.entryTime
                                ? Math.round((new Date(t.exitTime).getTime() - new Date(t.entryTime).getTime()) / 1000)
                                : 0;
                            const dMins = Math.floor(duration / 60);
                            const dSecs = duration % 60;
                            return (
                                <div key={i} className="px-2 py-1.5 rounded bg-white/5 border border-white/5 space-y-1">
                                    <div className="flex justify-between items-center text-[9px]">
                                        <span className={`font-bold ${t.side === 'LONG' ? 'text-green-400/80' : 'text-red-400/80'}`}>
                                            {t.side} x{(t.originalSize || t.size).toFixed(0)}
                                        </span>
                                        <span className={`font-mono font-bold ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {totalPnl >= 0 ? '+' : ''}₹{totalPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                        </span>
                                    </div>
                                    <div className="flex justify-between items-center text-[8px]">
                                        <span className="text-white/25 font-mono">
                                            {t.entryPrice?.toFixed(2) || '—'} → {t.exitPrice?.toFixed(2) || '—'}
                                        </span>
                                        <span className="text-white/25 font-mono">{dMins > 0 ? `${dMins}m ${dSecs}s` : `${dSecs}s`}</span>
                                    </div>
                                    <div className="flex justify-between items-center text-[8px]">
                                        {hadPartial ? (
                                            <span className="text-orange-400/70">
                                                Partial +₹{partialPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })} + Runner ₹{(totalPnl - partialPnl).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                                            </span>
                                        ) : (
                                            <span className="text-white/20">Full exit</span>
                                        )}
                                        <span className={`font-mono px-1 py-0.5 rounded text-[7px] ${t.closeReason === 'TAKE_PROFIT' || t.closeReason === 'PARTIAL_TAKE_PROFIT' ? 'bg-green-500/20 text-green-400' :
                                            t.closeReason === 'STOP_LOSS' ? 'bg-red-500/20 text-red-400' :
                                                t.closeReason === 'SCRATCH' ? 'bg-yellow-500/20 text-yellow-400' :
                                                    t.closeReason === 'TRAILING_STOP' ? 'bg-blue-500/20 text-blue-400' :
                                                        t.closeReason === 'TIME_STOP' ? 'bg-purple-500/20 text-purple-400' :
                                                            'bg-white/10 text-white/40'
                                            }`}>{t.closeReason || '—'}</span>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* 05. RULE CHECKLIST */}
            {/* 05. RULE CHECKLIST */}
            <div className="flex flex-col gap-2 mt-2">
                {(() => {
                    let passedCount = 0;
                    const ts = amtResult?.tickSize || 0.05;
                    const distThreshold = 5 * ts;
                    if (amtResult?.marketState === 'IMBALANCED' || amtResult?.marketState === 'PROBING') passedCount++;
                    if (currentLtp && amtResult?.valueAreaLow && Math.abs(currentLtp - (currentLtp > amtResult.sessionVwap! ? amtResult.valueAreaHigh! : amtResult.valueAreaLow!)) < distThreshold) passedCount++;
                    if (Math.abs(aggScore) > 0.5) passedCount++;
                    if (agentDecision?.timing === 'ENTER_NOW') passedCount++;
                    const totalRules = 4;
                    
                    return (
                        <details open className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2 group cursor-pointer relative overflow-hidden">
                            <div className={`absolute top-0 left-0 w-1 h-full ${passedCount === totalRules ? 'bg-emerald-500' : passedCount > 0 ? 'bg-yellow-500' : 'bg-white/10'}`} />
                            <summary className="list-none flex justify-between items-center pl-2 text-[10px] text-white/40 uppercase tracking-widest font-bold">
                                <div className="flex items-center gap-2">
                                    <span>05. Rule Checklist</span>
                                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono ${passedCount === totalRules ? 'bg-emerald-500/20 text-emerald-400' : passedCount > 0 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-white/10 text-white/40'}`}>
                                        {passedCount === totalRules ? '✅ ' : ''}{passedCount}/{totalRules} Passed
                                    </span>
                                </div>
                                <span className="group-open:hidden">Show</span>
                                <span className="hidden group-open:block hover:text-white/80 transition-colors">Hide</span>
                            </summary>
                            <div className="space-y-1.5 pt-2 border-t border-white/5 mt-2 pl-2">
                                <div className="flex items-center gap-2 text-[10px]">
                                    <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${(amtResult?.marketState === 'IMBALANCED' || amtResult?.marketState === 'PROBING') ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-red-500/20 border-red-500/50 text-red-400'}`}>
                                        {(amtResult?.marketState === 'IMBALANCED' || amtResult?.marketState === 'PROBING') ? '✓' : '✗'}
                                    </div>
                                    <span className="text-white/60 w-24">AAA PRE-1</span>
                                    <span className="text-white/40 font-mono text-[9px]">Session {amtResult?.marketState || 'BALANCED'}</span>
                                </div>
                                <div className="flex items-center gap-2 text-[10px]">
                                    <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${currentLtp && amtResult?.valueAreaLow && Math.abs(currentLtp - (currentLtp > amtResult.sessionVwap! ? amtResult.valueAreaHigh! : amtResult.valueAreaLow!)) < distThreshold ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-red-500/20 border-red-500/50 text-red-400'}`}>
                                        {currentLtp && amtResult?.valueAreaLow && Math.abs(currentLtp - (currentLtp > amtResult.sessionVwap! ? amtResult.valueAreaHigh! : amtResult.valueAreaLow!)) < distThreshold ? '✓' : '✗'}
                                    </div>
                                    <span className="text-white/60 w-24">MR Location</span>
                                    <span className="text-white/40 font-mono text-[9px]">Price near {currentLtp && amtResult?.valueAreaHigh && Math.abs(currentLtp - amtResult.valueAreaHigh) < distThreshold ? 'VAH' : currentLtp && amtResult?.valueAreaLow && Math.abs(currentLtp - amtResult.valueAreaLow) < distThreshold ? 'VAL' : 'POC/Mid'}</span>
                                </div>
                                <div className="flex items-center gap-2 text-[10px]">
                                    <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${Math.abs(aggScore) > 0.5 ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-red-500/20 border-red-500/50 text-red-400'}`}>
                                        {Math.abs(aggScore) > 0.5 ? '✓' : '✗'}
                                    </div>
                                    <span className="text-white/60 w-24">Volume Alive</span>
                                    <span className="text-white/40 font-mono text-[9px]">{Math.abs(aggScore) > 0.5 ? 'ACTIVE' : 'DEAD'}</span>
                                </div>
                                <div className="flex items-center gap-2 text-[10px]">
                                    <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${agentDecision?.timing === 'ENTER_NOW' ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-white/10 border-white/20 text-white/60'}`}>
                                        {agentDecision?.timing === 'ENTER_NOW' ? '✓' : '⏸'}
                                    </div>
                                    <span className="text-white/60 w-24">Timing</span>
                                    <span className="text-white/40 font-mono text-[9px]">{agentDecision?.timing || 'SKIP'}</span>
                                </div>
                            </div>
                            <div className="flex justify-between items-center mt-2 pt-2 border-t border-white/5 pl-2">
                                <span className="text-[9px] text-white/30 cursor-pointer hover:text-white/70 transition-colors">View Rule Book</span>
                                <span className="text-[10px] font-mono font-bold tracking-wider text-blue-300">
                                    Verdict: {agentDecision?.timing === 'ENTER_NOW' ? 'ENTER_NOW' : 'MONITOR -> WAIT'}
                                </span>
                            </div>
                        </details>
                    );
                })()}
            </div>

            {/* MODEL I/O Footer */}
            <details className="mt-2 group border-t border-white/5 pt-2 cursor-pointer">
                <summary className="list-none flex items-start gap-2">
                    <div className={`mt-1 h-2 w-2 rounded-full ${displayAnalysis.direction === 'LONG' ? 'bg-green-500 animate-ping' : displayAnalysis.direction === 'SHORT' ? 'bg-red-500 animate-ping' : 'bg-slate-600'}`}></div>
                    <div className="flex-1 min-w-0">
                        <div className="flex justify-between items-center mb-1">
                            <div className="font-bold text-white/80 uppercase tracking-wider text-xs">
                                {displayAnalysis.direction === 'FLAT' ? "MODEL I/O: MONITORING MARKET" : `MODEL I/O: ENTRY SIGNAL ${displayAnalysis.direction}`}
                            </div>
                            <div className="text-[9px] text-white/40 bg-white/5 px-1.5 py-0.5 rounded">Expand</div>
                        </div>
                        <p className={`p-2 rounded font-mono text-[10px] truncate ${displayAnalysis.direction === 'LONG' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : displayAnalysis.direction === 'SHORT' ? 'bg-red-500/10 text-red-400 border border-red-500/20' : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'}`}>
                            {(() => {
                                let text = sanitizeRationale(displayAnalysis.rationale || displayAnalysis.rawOutput) || "";
                                try {
                                    if (text.trim().startsWith('{')) {
                                        const parsed = JSON.parse(text);
                                        text = parsed.quant_reason || parsed.rationale || parsed.reason || parsed.direction || "QUANT_FLAT_NO_EDGE";
                                    }
                                } catch (e) {}
                                return text || "QUANT_MONITORING_NO_EDGE";
                            })()}
                        </p>
                    </div>
                </summary>
                    <div className="mt-2 pl-4 border-l border-white/10 ml-1 pb-1">
                    <div className="text-[9px] text-white/50 font-mono whitespace-pre-wrap">
                        {sanitizeLlmText(displayAnalysis.rationale || displayAnalysis.rawOutput) || "No detailed output."}
                    </div>
                </div>
            </details>

            {/* 06. LLM DECISION HISTORY */}
            <DecisionHistoryPanel llmHistory={llmHistory} />

        </div>
    );
};

// Wrap in React.memo to avoid re-renders when parent state changes
// but AIAnalysisPanel props have not changed.
export const AIAnalysisPanel = React.memo(AIAnalysisPanelInner);
