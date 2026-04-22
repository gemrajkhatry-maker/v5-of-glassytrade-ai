import React, { useMemo } from 'react';
import { GenAIAnalysis, AMTAnalysis, Portfolio, RiskState, LLMHistoryEntry, AgentDecision, OrderBook } from '../types';
import { Brain, TrendingUp, TrendingDown, MinusCircle, Target, Activity, Settings, Zap, AlertTriangle, Clock, BarChart3, Shield, Eye, Layers, ArrowUpDown, Crosshair, Navigation } from 'lucide-react';
import { EquityPanel, RiskStateDisplay, ModelIOPanel, DecisionHistoryPanel } from './ai';
import { sanitizeLlmText, sanitizeRationale, extractDecisionText } from '../utils/textSanitizer';

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
    symbol?: string;
    underlyingPrice?: number;
    data?: any[];
}

const AIAnalysisPanelInner: React.FC<AIAnalysisPanelProps> = ({ analysis, amtResult, portfolio, riskState, agentDecision, llmHistory = [], orderBook, depth20Active, overseerAction, overseerReason, symbol, underlyingPrice, data = [] }) => {
    // Determine current best price proxy (LTP) with 3-tier fallback chain.
    // Tier 1: Order book mid-price (most accurate, requires depth data)
    // Tier 2: Last close price from history
    // Tier 3: Session VWAP from AMT analysis
    // Tier 4: 0 (no data available — location section shows "Building...")
    const currentLtp = React.useMemo(() => {
        if (orderBook?.bids?.[0]?.price > 0 && orderBook?.asks?.[0]?.price > 0) {
            return (orderBook.bids[0].price + orderBook.asks[0].price) / 2;
        }
        if (data.length > 0) {
            return data[data.length - 1].close;
        }
        if (amtResult?.sessionVwap > 0) {
            return amtResult.sessionVwap;
        }
        return 0;
    }, [orderBook, amtResult?.sessionVwap, data]);

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

    // Per-symbol delta score from backend
    const deltaScore = amtResult?.deltaNormalizedOption ?? 0;

    // Format CVD Slope for display: large raw values use K/M suffix + "lots" unit
    const formatCVD = (cvd: number): string => {
        const abs = Math.abs(cvd);
        if (abs >= 1_000_000) return `${(cvd / 1_000_000).toFixed(2)}M lots`;
        if (abs >= 1_000) return `${(cvd / 1_000).toFixed(1)}K lots`;
        return `${cvd.toFixed(1)} lots`;
    };

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
                                const totalPartialPnl = (portfolio.positions as any[]).reduce(
                                    (sum: number, p: any) => sum + (p.partialRealizedPnl || 0), 0
                                );
                                const closedPnl = (portfolio.closedTrades || []).reduce(
                                    (sum: number, t: any) => {
                                        // For SL-hit exits, PnL may be stored directly on the position
                                        // rather than in metadata
                                        const tradePnl = t.pnl || 0;
                                        return sum + tradePnl;
                                    }, 0
                                );
                                const currentPnl = closedPnl + totalPartialPnl;
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

                {/* P1-9: Underlying Index Panel */}
                {underlyingPrice && underlyingPrice > 0 && (
                    <div className="mt-2 px-3 py-1.5 bg-white/5 border border-white/10 rounded flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <Activity className="w-3.5 h-3.5 text-blue-400" />
                            <span className="text-[10px] font-bold text-white/70 uppercase tracking-wider">Underlying Index</span>
                        </div>
                        <span className="text-xs font-mono font-bold text-blue-400">{underlyingPrice.toFixed(2)}</span>
                    </div>
                )}

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
                            {liveMarketState === 'DEAD' ? (
                                <div className="px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide flex items-center gap-1.5 bg-red-500/20 text-red-400 border border-red-500/30">
                                    <span className="text-white/40 font-normal">SESSION</span>
                                    <div className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                                    DEAD MARKET
                                </div>
                            ) : (
                                <div className={`px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide flex items-center gap-1.5 ${statusBg} ${statusColor}`}>
                                    <span className="text-white/40 font-normal">SESSION</span>
                                    <div className={`w-1.5 h-1.5 rounded-full ${isImbalanced ? 'bg-orange-400' : liveMarketState === 'PROBING' ? 'bg-blue-400' : 'bg-yellow-400'}`} />
                                    {liveMarketState.toUpperCase()}
                                </div>
                            )}
                            <div title={amtResult?.hasDisplacement ? "DISPLACEMENT — Strong directional move from value, new auction beginning" : "BALANCED — Price rotating within accepted value"} 
                                 className={`px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide flex items-center gap-1.5 cursor-help ${amtResult?.hasDisplacement ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' : 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'}`}>
                                <span className="text-white/40 font-normal">LEG</span>
                                <div className={`w-1.5 h-1.5 rounded-full ${amtResult?.hasDisplacement ? 'bg-orange-400' : 'bg-yellow-400'}`} />
                                {amtResult?.hasDisplacement ? 'DISPLACEMENT' : 'BALANCED'}
                                {(amtResult?.legPoc ?? 0) > 0 && (
                                    <span className="text-[8px] font-mono text-white/50 font-normal">
                                        POC {amtResult?.legPoc?.toFixed(1)}
                                        {(amtResult?.legVah ?? 0) > 0 && ` | ${amtResult?.legVal?.toFixed(1)}–${amtResult?.legVah?.toFixed(1)}`}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>
                    
                    {/* Item 2.15: Session Gap Info */}
                    {(() => {
                        const gapType = amtResult?.gapType;
                        const openingBias = amtResult?.openingBias;
                        if (!gapType && !openingBias) return null;
                        
                        return (
                            <div className="flex items-center gap-2 px-2 pt-1 border-t border-white/5">
                                {gapType && (
                                    <div className={`px-1.5 py-0.5 rounded text-[8px] font-bold tracking-wide ${
                                        gapType.includes('UP') || gapType.includes('BULL') ? 'bg-green-500/15 text-green-400 border border-green-500/30' :
                                        gapType.includes('DOWN') || gapType.includes('BEAR') ? 'bg-red-500/15 text-red-400 border border-red-500/30' :
                                        'bg-white/5 text-white/50 border border-white/10'
                                    }`}>
                                        GAP: {gapType}
                                    </div>
                                )}
                                {openingBias && (
                                    <div className={`px-1.5 py-0.5 rounded text-[8px] font-bold tracking-wide ${
                                        openingBias.includes('BULL') || openingBias.includes('UP') ? 'bg-green-500/15 text-green-400 border border-green-500/30' :
                                        openingBias.includes('BEAR') || openingBias.includes('DOWN') ? 'bg-red-500/15 text-red-400 border border-red-500/30' :
                                        'bg-white/5 text-white/50 border border-white/10'
                                    }`}>
                                        OPEN: {openingBias}
                                    </div>
                                )}
                            </div>
                        );
                    })()}
                </div>
            </div>

            {/* 02. LOCATION */}
            <div className="flex flex-col gap-2">
                <div className="p-3 rounded-lg bg-white/5 border border-white/10 relative">
                    <span className="absolute -top-2 left-2 px-1 bg-[#131722] text-[10px] text-white/40 uppercase tracking-widest font-bold">Location</span>
                    
                    {currentLtp > 0 && (amtResult?.poc !== undefined && amtResult?.poc !== null) ? (
                        <>
                        <div className="mt-3 relative h-16 flex items-center justify-center">
                            {(() => {
                                const min = Math.min(amtResult.valueAreaLow || currentLtp, amtResult.dailyVal || currentLtp, amtResult.legVal || currentLtp, currentLtp) * 0.999;
                                const max = Math.max(amtResult.valueAreaHigh || currentLtp, amtResult.dailyVah || currentLtp, amtResult.legVah || currentLtp, currentLtp) * 1.001;
                                const range = max - min || 1;
                                const getPos = (val: number) => `${Math.max(5, Math.min(95, ((val - min) / range) * 100))}%`;
                                
                                return (
                                    <div className="w-full relative h-1">
                                        {/* Base Track */}
                                        <div className="absolute top-0 left-0 w-full h-full bg-white/10 rounded-full"></div>
                                        
                                        {/* VA Fill (Session) */}
                                        {amtResult.valueAreaHigh > 0 && (
                                            <div className="absolute top-0 h-full bg-blue-500/20" style={{ left: getPos(amtResult.valueAreaLow), width: `${((amtResult.valueAreaHigh - amtResult.valueAreaLow) / range) * 100}%` }}></div>
                                        )}
                                        
                                        {/* VAH Marker */}
                                        {amtResult.valueAreaHigh > 0 && (
                                            <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: getPos(amtResult.valueAreaHigh) }}>
                                                <div className="w-0.5 h-3 bg-blue-400"></div>
                                                <span className="text-[8px] text-blue-400 mt-1 absolute top-3 whitespace-nowrap">VAH {amtResult.valueAreaHigh?.toFixed(1)}</span>
                                            </div>
                                        )}
                                        {/* VAL Marker */}
                                        {amtResult.valueAreaLow > 0 && (
                                            <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center" style={{ left: getPos(amtResult.valueAreaLow) }}>
                                                <div className="w-0.5 h-3 bg-blue-400"></div>
                                                <span className="text-[8px] text-blue-400 mt-1 absolute top-3 whitespace-nowrap">VAL {amtResult.valueAreaLow?.toFixed(1)}</span>
                                            </div>
                                        )}
                                        
                                        {/* Hourly POC (Blue Dot) */}
                                        {amtResult.hourlyPoc > 0 && (
                                            <div className="absolute top-1/2 -translate-y-[150%] flex flex-col items-center z-5" style={{ left: getPos(amtResult.hourlyPoc) }}>
                                                <div className="w-1.5 h-1.5 rounded-full bg-blue-500/60 border border-blue-400"></div>
                                                <span className="text-[7px] text-blue-400 mb-1 absolute bottom-1 whitespace-nowrap">HPOC</span>
                                            </div>
                                        )}

                                        {/* Daily POC (Purple Dot) */}
                                        {amtResult.dailyPoc > 0 && (
                                            <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center z-5" style={{ left: getPos(amtResult.dailyPoc) }}>
                                                <div className="w-2 h-2 rounded-full bg-purple-500/80 border border-purple-400"></div>
                                                <span className="text-[8px] font-bold text-purple-400 mt-1 absolute top-2 whitespace-nowrap">DPOC</span>
                                            </div>
                                        )}

                                        {/* Session POC Marker (Yellow) */}
                                        <div className="absolute top-1/2 -translate-y-1/2 flex flex-col items-center z-10" style={{ left: getPos(amtResult.poc) }}>
                                            <div className="w-2 h-2 rounded-full bg-yellow-400 shadow-[0_0_8px_rgba(250,204,21,0.5)]"></div>
                                            <span className="text-[9px] font-bold text-yellow-400 mt-1 absolute top-2 flex flex-col items-center">
                                                <span>POC</span>
                                                <span className="font-mono">{poc}</span>
                                            </span>
                                        </div>

                                        {/* Leg POC Marker (Orange) */}
                                        {amtResult.legPoc > 0 && Math.abs(amtResult.legPoc - amtResult.poc) > 0.5 && (
                                            <div className="absolute top-1/2 translate-y-[50%] flex flex-col items-center z-10" style={{ left: getPos(amtResult.legPoc) }}>
                                                <div className="w-1.5 h-1.5 rounded-full bg-orange-500 shadow-[0_0_4px_rgba(249,115,22,0.5)]"></div>
                                                <span className="text-[8px] font-bold text-orange-400 mt-0.5 absolute top-1.5 whitespace-nowrap">LEG {amtResult.legPoc.toFixed(1)}</span>
                                            </div>
                                        )}

                                        {/* LTP Marker */}
                                        <div className="absolute top-1/2 -translate-y-[140%] flex flex-col items-center z-20" style={{ left: getPos(currentLtp) }}>
                                            <div className="px-1.5 py-0.5 bg-white text-black text-[9px] font-bold font-mono rounded shadow-lg flex items-center gap-1 mb-1">
                                                {currentLtp.toFixed(1)} <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
                                            </div>
                                            <div className="w-px h-3 bg-white"></div>
                                        </div>
                                    </div>
                                );
                            })()}
                        </div>
                        {/* Overflow indicators when LTP is outside VA */}
                        {(() => {
                            // Use leg VAH/VAL when PROBING/IMBALANCED for relevant distance display
                            const isLegActive = amtResult.legPoc > 0 && (amtResult.marketState === 'PROBING' || amtResult.marketState === 'IMBALANCED');
                            const refVah = isLegActive && amtResult.legVah > 0 ? amtResult.legVah : amtResult.valueAreaHigh;
                            const refVal = isLegActive && amtResult.legVal > 0 ? amtResult.legVal : amtResult.valueAreaLow;
                            const vahLabel = isLegActive && amtResult.legVah > 0 ? 'Leg VAH' : 'Session VAH';
                            const valLabel = isLegActive && amtResult.legVal > 0 ? 'Leg VAL' : 'Session VAL';
                            return <>
                                {refVah > 0 && currentLtp > refVah && (
                                    <div className="text-[9px] text-amber-400 font-mono mt-2 text-center">
                                        ↑ ABOVE {vahLabel} by {(currentLtp - refVah).toFixed(2)} pts
                                    </div>
                                )}
                                {refVal > 0 && currentLtp < refVal && (
                                    <div className="text-[9px] text-amber-400 font-mono mt-2 text-center">
                                        ↓ BELOW {valLabel} by {(refVal - currentLtp).toFixed(2)} pts
                                    </div>
                                )}
                            </>;
                        })()}
                    </>
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
                            <span className="text-[10px] text-white/60 mb-0.5">Delta Score <span className="text-[8px] text-white/25">(norm)</span></span>
                            <span className={`text-[9px] font-bold tracking-wider ${Math.abs(deltaScore) > 0.05 && aggScore > 0.1 ? (deltaScore > 0 ? 'text-green-400' : 'text-red-400') : 'text-white/40'}`}>
                                {Math.abs(deltaScore) > 0.05 && aggScore > 0.1 ? (deltaScore > 0 ? '[BULLS IN CONTROL]' : '[BEARS IN CONTROL]') : '[DELTA NEUTRAL / NEGLIGIBLE]'}
                            </span>
                        </div>
                        <div className="flex flex-col items-end gap-0.5">
                            <span className={`text-xs font-mono font-bold ${deltaScore > 0 ? 'text-green-400' : deltaScore < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                                {deltaScore > 0 ? '+' : ''}{deltaScore.toFixed(2)}
                            </span>
                            {agentDecision && (() => {
                                // Delta confidence: strength of delta signal (0-100%)
                                // When delta is near-zero, show ~50% (neutral/no edge)
                                const isDeltaNeutral = Math.abs(deltaScore) < 0.05;
                                const deltaConfidence = isDeltaNeutral 
                                    ? 50 
                                    : Math.min(100, Math.abs(deltaScore) * 100);
                                const confColor = isDeltaNeutral 
                                    ? 'text-yellow-400' 
                                    : agentDecision.probability >= 0.6 
                                        ? 'text-emerald-400' 
                                        : agentDecision.probability > 0.45 
                                            ? 'text-yellow-400' 
                                            : agentDecision.probability > 0 
                                                ? 'text-red-400' 
                                                : 'text-white/30';
                                
                                return (
                                    <span className={`text-[9px] font-mono font-bold ${confColor}`}>
                                        {isDeltaNeutral ? '~50%' : `${deltaConfidence.toFixed(1)}%`}
                                    </span>
                                );
                            })()}
                        </div>
                    </div>
                    {/* Progress Bar */}
                    <div className="h-1 bg-white/10 rounded-full overflow-hidden flex relative">
                        <div className="absolute top-0 left-1/2 w-px h-full bg-white/20 z-10" />
                        {/* Visual bar moving left or right based on score */}
                        <div className={`h-full absolute transition-all duration-500 rounded-full`} style={{
                            width: `${Math.min(Math.abs(deltaScore) * 50, 50)}%`,
                            left: deltaScore > 0 ? '50%' : `${50 - Math.min(Math.abs(deltaScore) * 50, 50)}%`,
                            backgroundColor: deltaScore > 0 ? '#4ade80' : '#f87171'
                        }}></div>
                    </div>
                    {/* Aggression indicator */}
                    <div className="flex justify-between text-[9px] mt-1.5 pt-1 border-t border-white/5">
                        <span className="text-white/40">Aggression</span>
                        <span className={`font-mono font-bold ${aggScore > 0 ? 'text-green-400' : aggScore < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                            {aggScore.toFixed(2)}{deltaScore < -0.05 ? ' (Bearish)' : deltaScore > 0.05 ? ' (Bullish)' : ''}
                        </span>
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
                            <span className="text-[10px] text-white/40">OFI <span className="text-[8px] text-white/25">(norm)</span></span>
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
                                    {(amtResult?.cvdSlope ?? 0) > 0 ? '+' : ''}{formatCVD(amtResult?.cvdSlope ?? 0)}
                                    {amtResult?.cvdDivergence ? ` (${amtResult.cvdDivergence.replace('_DIV', '')})` : ''}
                                    {(amtResult?.cvdSlope ?? 0) > 0.01 ? ' BULLISH' : (amtResult?.cvdSlope ?? 0) < -0.01 ? ' BEARISH' : ' FLAT'}
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
                    {/* Item 3.13: CVD Sparkline */}
                    {(() => {
                        // Create a simple sparkline from CVD slope value
                        // Since we only have current CVD slope, we'll simulate a mini trend
                        const cvd = amtResult?.cvdSlope ?? 0;
                        const cvdAbs = Math.abs(cvd);
                        const cvdDirection = cvd > 0 ? 1 : cvd < 0 ? -1 : 0;
                        
                        if (cvdAbs < 0.01) return null;
                        
                        // Generate a simple 10-point sparkline showing recent trend
                        const points = 10;
                        const width = 60;
                        const height = 20;
                        const strokeWidth = 1.5;
                        
                        // Simulate trend: recent values leading to current CVD
                        const sparkData: number[] = [];
                        for (let i = 0; i < points; i++) {
                            // Linear progression from 0 to current value with slight noise
                            const progress = i / (points - 1);
                            const noise = (Math.sin(i * 1.5) * 0.1) * cvd; // 10% noise
                            sparkData.push(cvd * progress + noise);
                        }
                        
                        const minVal = Math.min(...sparkData);
                        const maxVal = Math.max(...sparkData);
                        const range = maxVal - minVal || 1;
                        
                        // Convert to SVG path
                        const pathPoints = sparkData.map((val, i) => {
                            const x = (i / (points - 1)) * width;
                            const y = height - ((val - minVal) / range) * (height - 4) - 2; // 2px padding
                            return `${x.toFixed(1)},${y.toFixed(1)}`;
                        });
                        const pathD = `M ${pathPoints.join(' L ')}`;
                        
                        const strokeColor = cvdDirection > 0 ? '#4ade80' : '#f87171';
                        
                        return (
                            <div className="flex items-center gap-2 mt-2 pt-2 border-t border-white/5">
                                <span className="text-[8px] text-white/40">CVD Trend</span>
                                <svg width={width} height={height} className="flex-shrink-0">
                                    {/* Grid line */}
                                    <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="rgba(255,255,255,0.1)" strokeWidth="0.5" />
                                    {/* Sparkline */}
                                    <path d={pathD} fill="none" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
                                    {/* End dot */}
                                    <circle 
                                        cx={width} 
                                        cy={height - ((sparkData[sparkData.length - 1] - minVal) / range) * (height - 4) - 2} 
                                        r="2" 
                                        fill={strokeColor} 
                                    />
                                </svg>
                                <span className={`text-[8px] font-mono ${cvdDirection > 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {cvdDirection > 0 ? '↗' : '↘'} {cvdAbs > 1000 ? `${(cvdAbs / 1000).toFixed(1)}K` : cvdAbs.toFixed(0)}
                                </span>
                            </div>
                        );
                    })()}
                    {/* Aggression Divergence Check */}
                    {(() => {
                        const delta = amtResult?.deltaNormalizedOption ?? 0;
                        const cvd = amtResult?.cvdSlope ?? 0;
                        const ofi = amtResult?.ofi ?? 0;
                        const ibBreak = amtResult?.breakDirection ?? '';
                        // Lowered delta threshold from 0.1 to 0.02 to catch more divergence cases
                        const bullCount = (delta > 0.02 ? 1 : 0) + (cvd > 0.01 ? 1 : 0) + (ofi > 0.1 ? 1 : 0);
                        const bearCount = (delta < -0.02 ? 1 : 0) + (cvd < -0.01 ? 1 : 0) + (ofi < -0.1 ? 1 : 0);
                        // Also detect CVD vs IB break divergence (e.g. bullish CVD but bearish IB break)
                        const cvdBullish = cvd > 0.01;
                        const cvdBearish = cvd < -0.01;
                        const ibBullish = ibBreak === 'UP';
                        const ibBearish = ibBreak === 'DOWN';
                        const cvdIbDivergence = (cvdBullish && ibBearish) || (cvdBearish && ibBullish);
                        const hasConflict = (bullCount > 0 && bearCount > 0) || cvdIbDivergence;
                        // CE/PE context: interpret option flow direction relative to underlying
                        const isCE = symbol?.toUpperCase().includes(' CE') || symbol?.toUpperCase().endsWith('CE');
                        const isPE = symbol?.toUpperCase().includes(' PE') || symbol?.toUpperCase().endsWith('PE');
                        const cvdDir = cvd > 0.01 ? 'bullish' : cvd < -0.01 ? 'bearish' : 'neutral';
                        const underlyingSignal = isCE
                            ? (cvdDir === 'bullish' ? '↗ Bullish flow on CE → underlying bullish signal' : cvdDir === 'bearish' ? '↘ Bearish flow on CE → underlying bearish signal' : '')
                            : isPE
                            ? (cvdDir === 'bullish' ? '↗ Bullish flow on PE → underlying bearish signal (put accumulation)' : cvdDir === 'bearish' ? '↘ Bearish flow on PE → underlying bullish signal (put unwinding)' : '')
                            : '';
                        return (
                            <>
                                {hasConflict && (
                                    <div className="mt-1.5 px-2 py-1 bg-yellow-500/10 border border-yellow-500/30 rounded text-[9px] font-bold text-yellow-400 text-center">
                                        CONFLICTED AGGRESSION — {cvdIbDivergence && !(bullCount > 0 && bearCount > 0)
                                            ? `CVD/IB Divergence — CVD ${cvdBullish ? 'Bullish' : 'Bearish'} vs IB ${ibBullish ? 'UP' : 'DOWN'}`
                                            : 'Delta/CVD/OFI Divergence'}
                                    </div>
                                )}
                                {underlyingSignal && (
                                    <div className="mt-1 px-2 py-0.5 bg-blue-500/10 border border-blue-500/20 rounded text-[8px] font-medium text-blue-400 text-center">
                                        OPTION CONTEXT: {underlyingSignal}
                                    </div>
                                )}
                            </>
                        );
                    })()}
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
                            <span className="text-[8px] text-white/30">
                                ({amtResult?.profileType || 'Session'})
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
                    {/* Item 2.14: VA Acceptance Duration (simplified - based on current state) */}
                    {(() => {
                        const isAccepted = amtResult?.acceptanceAbove || amtResult?.acceptanceBelow;
                        if (!isAccepted) return null;
                        
                        // Simplified: estimate duration based on current market state
                        // In reality, this requires server-side timestamp tracking
                        const direction = amtResult?.acceptanceAbove ? 'above VAH' : 'below VAL';
                        const estimatedDuration = amtResult?.marketState === 'IMBALANCED' ? 'Extended' : 'Developing';
                        const durationColor = estimatedDuration === 'Extended' ? 'text-orange-400' : 'text-blue-400';
                        
                        return (
                            <div className="flex justify-between items-center px-1 py-0.5 bg-white/5 rounded border border-white/10">
                                <span className="text-[8px] text-white/40">VA Acceptance</span>
                                <span className={`text-[8px] font-bold ${durationColor}`}>
                                    {direction} — {estimatedDuration}
                                </span>
                            </div>
                        );
                    })()}
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
                    {/* Item 4.9: IB Size Classification */}
                    {amtResult?.ibHigh && amtResult?.ibLow && amtResult.ibHigh > 0 && amtResult.ibLow > 0 && (() => {
                        const ibSize = amtResult.ibHigh - amtResult.ibLow;
                        const ibMid = (amtResult.ibHigh + amtResult.ibLow) / 2;
                        // Classification based on IB size relative to mid price (percentage)
                        const ibPct = (ibSize / ibMid) * 100;
                        let sizeClass = 'NORMAL';
                        let sizeColor = 'text-white/60';
                        let sizeBg = 'bg-white/5';
                        
                        if (ibPct < 0.5) {
                            sizeClass = 'NARROW';
                            sizeColor = 'text-yellow-400';
                            sizeBg = 'bg-yellow-500/10';
                        } else if (ibPct > 1.5) {
                            sizeClass = 'WIDE';
                            sizeColor = 'text-red-400';
                            sizeBg = 'bg-red-500/10';
                        }
                        
                        return (
                            <div className="flex justify-between items-center pt-1 border-t border-white/5">
                                <span className="text-[10px] text-white/40">IB Size</span>
                                <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold ${sizeColor} ${sizeBg}`}>
                                    {ibSize.toFixed(2)} pts — {sizeClass} ({ibPct.toFixed(2)}%)
                                </span>
                            </div>
                        );
                    })()}
                    {/* Item 4.10: IB Extension Targets (1.5x, 2x IB Range) */}
                    {amtResult?.ibHigh && amtResult?.ibLow && amtResult.ibHigh > 0 && amtResult.ibLow > 0 && amtResult?.breakDirection && (() => {
                        const ibRange = amtResult.ibHigh - amtResult.ibLow;
                        const isUpBreak = amtResult.breakDirection === 'UP';
                        
                        // Extension targets based on break direction
                        const target15x = isUpBreak 
                            ? amtResult.ibHigh + (ibRange * 0.5)  // 1.5x above IB high
                            : amtResult.ibLow - (ibRange * 0.5);  // 1.5x below IB low
                        const target2x = isUpBreak 
                            ? amtResult.ibHigh + ibRange  // 2x above IB high
                            : amtResult.ibLow - ibRange;  // 2x below IB low
                        
                        return (
                            <div className="pt-1 border-t border-white/5 space-y-1">
                                <div className="text-[9px] text-white/40 font-bold tracking-wide">IB EXTENSION TARGETS</div>
                                <div className="flex justify-between items-center px-1">
                                    <span className="text-[9px] text-white/50">1.5x IB</span>
                                    <span className="px-1.5 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-[9px] font-mono font-bold text-cyan-400">
                                        {target15x.toFixed(2)}
                                    </span>
                                </div>
                                <div className="flex justify-between items-center px-1">
                                    <span className="text-[9px] text-white/50">2.0x IB</span>
                                    <span className="px-1.5 py-0.5 rounded bg-purple-500/10 border border-purple-500/30 text-[9px] font-mono font-bold text-purple-400">
                                        {target2x.toFixed(2)}
                                    </span>
                                </div>
                            </div>
                        );
                    })()}
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
                    {/* Failed Breakout Detection (MRL-009): IB broke UP but price below VAL, or IB broke DOWN but price above VAH */}
                    {(() => {
                        const ibDir = amtResult?.breakDirection ?? '';
                        const val = amtResult?.valueAreaLow ?? 0;
                        const vah = amtResult?.valueAreaHigh ?? 0;
                        if (!ibDir || !currentLtp || val <= 0 || vah <= 0) return null;
                        
                        // Strict failure: price completely outside VA on wrong side
                        const failedUpBreak = ibDir === 'UP' && currentLtp < val;
                        const failedDownBreak = ibDir === 'DOWN' && currentLtp > vah;
                        
                        // Weak failure: price rejected back into value, near opposite boundary
                        const vaRange = vah - val;
                        const threshold = vaRange * 0.05; // 5% of VA range
                        const weakFailedUp = ibDir === 'UP' && currentLtp < (val + threshold) && currentLtp > val;
                        const weakFailedDown = ibDir === 'DOWN' && currentLtp > (vah - threshold) && currentLtp < vah;
                        
                        if (failedUpBreak || weakFailedUp) {
                            return (
                                <div className="mt-1 px-2 py-1 bg-red-500/10 border border-red-500/30 rounded text-[9px] font-bold text-red-400 text-center animate-pulse">
                                    ⚠️ FAILED BREAKOUT — REJECTION OF VALUE (IB broke ↑ but rejected)
                                </div>
                            );
                        }
                        if (failedDownBreak || weakFailedDown) {
                            return (
                                <div className="mt-1 px-2 py-1 bg-red-500/10 border border-red-500/30 rounded text-[9px] font-bold text-red-400 text-center animate-pulse">
                                    ⚠️ FAILED BREAKOUT — REJECTION OF VALUE (IB broke ↓ but rejected)
                                </div>
                            );
                        }
                        return null;
                    })()}
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

            {/* Items 3.16-3.17: Absorption & Large Print Detection */}
            {(() => {
                const absorptionSide = amtResult?.absorptionSide;
                const absorptionRangeRatio = amtResult?.absorptionRangeRatio ?? 0;
                const absorptionVolRatio = amtResult?.absorptionVolRatio ?? 0;
                const aggressivePrints = amtResult?.aggressivePrints ?? [];
                const swingDelta = amtResult?.swingDelta ?? 0;
                
                // Check if we have any absorption or large prints to show
                const hasAbsorption = absorptionSide && absorptionRangeRatio > 0;
                const hasLargePrints = aggressivePrints.length > 0;
                
                if (!hasAbsorption && !hasLargePrints && Math.abs(swingDelta) < 100) return null;
                
                return (
                    <div className="flex flex-col gap-2">
                        <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                            <span>03d. Absorption & Large Prints</span>
                        </div>
                        <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                            {/* Absorption Detection */}
                            {hasAbsorption && (
                                <div className={`px-2 py-1.5 rounded border ${
                                    absorptionSide === 'BUY' 
                                        ? 'bg-green-500/10 border-green-500/30' 
                                        : 'bg-red-500/10 border-red-500/30'
                                }`}>
                                    <div className="flex items-center justify-between">
                                        <span className={`text-[9px] font-bold ${
                                            absorptionSide === 'BUY' ? 'text-green-400' : 'text-red-400'
                                        }`}>
                                            {absorptionSide === 'BUY' ? '🟢 BUY' : '🔴 SELL'} ABSORPTION
                                        </span>
                                        <span className="text-[8px] font-mono text-white/50">
                                            Range: {absorptionRangeRatio.toFixed(2)}x | Vol: {absorptionVolRatio.toFixed(1)}x
                                        </span>
                                    </div>
                                    <div className="text-[8px] text-white/40 mt-1">
                                        Price stalled despite {absorptionSide === 'BUY' ? 'selling pressure' : 'buying pressure'} — limit orders absorbing market
                                    </div>
                                </div>
                            )}
                            
                            {/* Large Institutional Prints */}
                            {hasLargePrints && (
                                <div className="space-y-1">
                                    <div className="text-[9px] text-white/40 font-bold">LARGE PRINTS ({aggressivePrints.length})</div>
                                    <div className="flex flex-wrap gap-1">
                                        {aggressivePrints.slice(-5).map((print, idx) => (
                                            <span 
                                                key={idx}
                                                className={`px-1.5 py-0.5 rounded text-[8px] font-mono font-bold ${
                                                    print.side === 'BUY' 
                                                        ? 'bg-green-500/20 text-green-400 border border-green-500/30' 
                                                        : 'bg-red-500/20 text-red-400 border border-red-500/30'
                                                }`}
                                            >
                                                {print.side === 'BUY' ? 'B' : 'S'} {print.volume > 1000 ? `${(print.volume / 1000).toFixed(1)}K` : print.volume}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}
                            
                            {/* Swing Delta (Initiative vs Responsive) */}
                            {Math.abs(swingDelta) >= 100 && (
                                <div className="flex justify-between items-center px-1 py-0.5 bg-white/5 rounded border border-white/10">
                                    <span className="text-[8px] text-white/40">Swing Delta</span>
                                    <span className={`text-[8px] font-mono font-bold ${
                                        swingDelta > 0 ? 'text-green-400' : 'text-red-400'
                                    }`}>
                                        {swingDelta > 0 ? '+' : ''}{swingDelta > 1000 ? `${(swingDelta / 1000).toFixed(1)}K` : swingDelta.toFixed(0)}
                                        {swingDelta > 500 ? ' (INITIATIVE)' : swingDelta < -500 ? ' (RESPONSIVE)' : ''}
                                    </span>
                                </div>
                            )}
                        </div>
                    </div>
                );
            })()}

            {/* 03f. VWAP + PRIOR DAY */}
            {(amtResult?.sessionVwap ?? 0) > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                        <span>03e. VWAP + Context</span>
                    </div>
                    <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-1.5 text-[9px]">
                        {(() => {
                            const vwapStd = (amtResult.vwapUpper1 ?? 0) - (amtResult.sessionVwap ?? 0);
                            const isVwapFlat = amtResult.vwapDeviationSigmas === null || amtResult.vwapDeviationSigmas === undefined;
                            return (
                                <>
                                    <div className="flex justify-between">
                                        <span className="text-white/40">Session VWAP</span>
                                        <span className="font-mono text-cyan-400">{amtResult?.sessionVwap?.toFixed(2)}</span>
                                    </div>
                                    {isVwapFlat ? (
                                        <div className="text-center py-2 text-[9px] font-bold text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded">
                                            FLAT MARKET — Insufficient Price Variance
                                        </div>
                                    ) : (
                                        <>
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
                                        </>
                                    )}
                                    
                                    {/* Inline Deviation Meter (-3σ to +3σ) */}
                                    {currentLtp > 0 && amtResult?.sessionVwap && (
                                        <div className="pt-3 pb-1 border-t border-white/5">
                                            {!isVwapFlat && (
                                                <>
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
                                                            if (isVwapFlat) return null;
                                                            const sigma = amtResult.vwapDeviationSigmas;
                                                            if (sigma !== null && sigma !== undefined) {
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
                                                </>
                                            )}
                                            {isVwapFlat ? (
                                                <div className="mt-2 text-center text-[9px] text-amber-400/60 font-mono">σ N/A — Flat Market</div>
                                            ) : (
                                                (() => {
                                                    const sigma = amtResult.vwapDeviationSigmas;
                                                    if (sigma !== null && sigma !== undefined) {
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
                                                })()
                                            )}
                                        </div>
                                    )}
                                </>
                            );
                        })()}
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
                        
                        {/* Items 5.12-5.14: VWAP Events & AVWAP Detection */}
                        {(() => {
                            const vwap = amtResult?.sessionVwap ?? 0;
                            const ltp = currentLtp;
                            if (vwap <= 0 || ltp <= 0) return null;
                            
                            // Detect VWAP cross direction
                            const distFromVwap = ((ltp - vwap) / vwap) * 100;
                            const vwapCrossThreshold = 0.3; // 0.3% from VWAP
                            const isNearVwap = Math.abs(distFromVwap) < vwapCrossThreshold;
                            
                            // Check if price is at VWAP sigma bands
                            const upper1 = amtResult?.vwapUpper1 ?? 0;
                            const lower1 = amtResult?.vwapLower1 ?? 0;
                            const upper2 = amtResult?.vwapUpper2 ?? 0;
                            const lower2 = amtResult?.vwapLower2 ?? 0;
                            
                            const atUpper1 = upper1 > 0 && Math.abs((ltp - upper1) / upper1) < 0.002;
                            const atLower1 = lower1 > 0 && Math.abs((ltp - lower1) / lower1) < 0.002;
                            const atUpper2 = upper2 > 0 && Math.abs((ltp - upper2) / upper2) < 0.002;
                            const atLower2 = lower2 > 0 && Math.abs((ltp - lower2) / lower2) < 0.002;
                            
                            const hasVWAPEvent = isNearVwap || atUpper1 || atLower1 || atUpper2 || atLower2;

                            if (!hasVWAPEvent) return null;

                            const sig = amtResult?.vwapDeviationSigmas;
                            let primary: 'u2' | 'l2' | 'u1' | 'l1' | 'near' | null = null;
                            if (typeof sig === 'number' && Number.isFinite(sig)) {
                                if (sig >= 1.65 && atUpper2) primary = 'u2';
                                else if (sig <= -1.65 && atLower2) primary = 'l2';
                                else if (sig >= 0.8 && atUpper1) primary = 'u1';
                                else if (sig <= -0.8 && atLower1) primary = 'l1';
                                else if (Math.abs(sig) < 0.5 && isNearVwap) primary = 'near';
                            }
                            if (!primary) {
                                if (atUpper2) primary = 'u2';
                                else if (atLower2) primary = 'l2';
                                else if (atUpper1) primary = 'u1';
                                else if (atLower1) primary = 'l1';
                                else if (isNearVwap) primary = 'near';
                            }

                            const activeCount = [isNearVwap, atUpper1, atLower1, atUpper2, atLower2].filter(Boolean).length;
                            const ambiguous = activeCount > 2 && primary === 'near';
                            if (ambiguous) {
                                return (
                                    <div className="border-t border-white/5 pt-2 space-y-1.5">
                                        <div className="text-[8px] text-white/40 font-bold tracking-wide">VWAP EVENTS</div>
                                        <div className="px-1.5 py-1 bg-white/5 border border-white/10 rounded text-[8px] text-white/55 font-mono">
                                            Between VWAP bands — no single active touch (see sigma meter above)
                                        </div>
                                    </div>
                                );
                            }

                            const rowCls = (id: NonNullable<typeof primary>) =>
                                id === primary ? 'opacity-100' : 'opacity-35 saturate-50 pointer-events-none';

                            return (
                                <div className="border-t border-white/5 pt-2 space-y-1.5">
                                    <div className="text-[8px] text-white/40 font-bold tracking-wide">VWAP EVENTS</div>

                                    {isNearVwap && (
                                        <div className={`px-1.5 py-1 bg-cyan-500/10 border border-cyan-500/30 rounded transition-opacity ${rowCls('near')}`}>
                                            <div className="text-[8px] font-bold text-cyan-400">
                                                AT VWAP — Decision Zone
                                            </div>
                                            <div className="text-[7px] text-white/40 mt-0.5">
                                                Price testing session fair value — watch for bounce/break
                                            </div>
                                        </div>
                                    )}

                                    {atUpper1 && (
                                        <div className={`px-1.5 py-0.5 bg-orange-500/10 border border-orange-500/30 rounded text-[8px] font-bold text-orange-400 transition-opacity ${rowCls('u1')}`}>
                                            Testing +1σ VWAP — Resistance
                                        </div>
                                    )}
                                    {atLower1 && (
                                        <div className={`px-1.5 py-0.5 bg-emerald-500/10 border border-emerald-500/30 rounded text-[8px] font-bold text-emerald-400 transition-opacity ${rowCls('l1')}`}>
                                            Testing -1σ VWAP — Support
                                        </div>
                                    )}
                                    {atUpper2 && (
                                        <div className={`px-1.5 py-0.5 bg-red-500/10 border border-red-500/30 rounded text-[8px] font-bold text-red-400 transition-opacity ${rowCls('u2')} ${primary === 'u2' ? 'animate-pulse' : ''}`}>
                                            Testing +2σ VWAP — Extreme Overbought
                                        </div>
                                    )}
                                    {atLower2 && (
                                        <div className={`px-1.5 py-0.5 bg-green-500/10 border border-green-500/30 rounded text-[8px] font-bold text-green-400 transition-opacity ${rowCls('l2')} ${primary === 'l2' ? 'animate-pulse' : ''}`}>
                                            Testing -2σ VWAP — Extreme Oversold
                                        </div>
                                    )}
                                </div>
                            );
                        })()}
                    </div>
                </div>
            )}

            {/* Items 6.6-6.8: Market Structure Panel */}
            {amtResult?.marketStructure && (
                <div className="flex flex-col gap-2">
                    <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                        <span>05. Market Structure</span>
                    </div>
                    <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                        {(() => {
                            const structure = amtResult.marketStructure;
                            const confidence = amtResult.structureConfidence ?? 0;
                            
                            // Structure color coding
                            const structureConfig: Record<string, { color: string; bg: string; icon: string; desc: string }> = {
                                'TREND_UP': { color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/30', icon: '↗', desc: 'Higher highs & higher lows — bullish trend' },
                                'TREND_DOWN': { color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30', icon: '↘', desc: 'Lower highs & lower lows — bearish trend' },
                                'RANGE': { color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/30', icon: '⟷', desc: 'Price rotating between support/resistance' },
                                'BREAKOUT': { color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/30', icon: '⚡', desc: 'Price breaking out of range — potential trend start' },
                                'REVERSAL': { color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/30', icon: '↺', desc: 'Trend reversal in progress' },
                            };
                            
                            const config = structureConfig[structure] || { color: 'text-white/60', bg: 'bg-white/5 border-white/10', icon: '●', desc: 'Unknown structure' };
                            
                            return (
                                <>
                                    <div className={`px-2 py-1.5 rounded border ${config.bg}`}>
                                        <div className="flex items-center justify-between">
                                            <span className={`text-[10px] font-bold ${config.color}`}>
                                                {config.icon} {structure.replace('_', ' ')}
                                            </span>
                                            <span className="text-[8px] font-mono text-white/50">
                                                {confidence}% confidence
                                            </span>
                                        </div>
                                        <div className="text-[8px] text-white/40 mt-1">
                                            {config.desc}
                                        </div>
                                    </div>
                                    
                                    {/* Confidence bar */}
                                    <div className="space-y-1">
                                        <div className="flex justify-between text-[8px]">
                                            <span className="text-white/40">Structure Strength</span>
                                            <span className={`font-mono ${
                                                confidence >= 70 ? 'text-green-400' : 
                                                confidence >= 50 ? 'text-yellow-400' : 
                                                'text-red-400'
                                            }`}>
                                                {confidence >= 70 ? 'STRONG' : confidence >= 50 ? 'MODERATE' : 'WEAK'}
                                            </span>
                                        </div>
                                        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                                            <div 
                                                className="h-full rounded-full transition-all duration-300"
                                                style={{
                                                    width: `${confidence}%`,
                                                    backgroundColor: confidence >= 70 ? '#4ade80' : confidence >= 50 ? '#fbbf24' : '#f87171',
                                                }}
                                            />
                                        </div>
                                    </div>
                                    
                                    {/* Structure-based trading guidance */}
                                    <div className="px-1.5 py-1 bg-white/5 rounded border border-white/10">
                                        <div className="text-[8px] text-white/40 font-bold mb-1">TRADING CONTEXT</div>
                                        <div className="text-[8px] text-white/50">
                                            {structure === 'TREND_UP' && 'Look for pullback entries in direction of trend'}
                                            {structure === 'TREND_DOWN' && 'Look for rally entries to short in direction of trend'}
                                            {structure === 'RANGE' && 'Fade extremes — buy support, sell resistance'}
                                            {structure === 'BREAKOUT' && 'Wait for acceptance before entering — avoid false breaks'}
                                            {structure === 'REVERSAL' && 'High risk/reward — confirm with volume & CVD'}
                                        </div>
                                    </div>
                                </>
                            );
                        })()}
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
                                    {(() => {
                                        const dir = agentDecision?.direction || 'FLAT';
                                        const regime = agentDecision?.regime || '';
                                        const optionType = amtResult?.optionType || '';
                                        
                                        if (dir === 'FLAT') return 'FLAT';
                                        
                                        // Map direction to option action
                                        const action = dir === 'LONG' ? 'BUY' : 'SELL';
                                        const optionLabel = optionType ? ` ${optionType}` : '';
                                        
                                        // AMT playbook terminology
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
                            
                            {/* Fabio Playbook: Second Drive Indicator */}
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
                            
                            {/* Fabio Playbook: LVN Play Indicator */}
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
                                        {sanitizeRationale(agentDecision.rationale)} <span className="text-white/20">({agentDecision.latencyUs}μs)</span>
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
            <div className="flex flex-col gap-2 mt-2">
                {(() => {
                    let passedCount = 0;
                    const ts = amtResult?.tickSize || 0.05;
                    const distThreshold = 5 * ts;
                    if (amtResult?.marketState !== 'DEAD') passedCount++;
                    if (currentLtp && amtResult?.valueAreaLow && Math.abs(currentLtp - (currentLtp > amtResult.sessionVwap! ? amtResult.valueAreaHigh! : amtResult.valueAreaLow!)) < distThreshold) passedCount++;
                    if (amtResult?.marketState !== 'DEAD') passedCount++;
                    if (agentDecision?.timing === 'ENTER_NOW') passedCount++;
                    const totalRules = 4;
                    const sigmaV = amtResult?.vwapDeviationSigmas || 0;
                    const verdictText =
                        Math.abs(sigmaV) >= 3.0
                            ? 'RESPONSIVE FADE ACTIVE'
                            : agentDecision?.timing === 'ENTER_NOW'
                              ? 'ENTER_NOW'
                              : 'MONITOR -> WAIT';
                    const verdictClass =
                        Math.abs(sigmaV) >= 3.0
                            ? 'text-orange-400 border-orange-500/40 bg-orange-500/10'
                            : 'text-blue-300 border-blue-500/30 bg-blue-500/10';

                    return (
                        <details className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2 group cursor-pointer relative overflow-hidden">
                            <div className={`absolute top-0 left-0 w-1 h-full ${passedCount === totalRules ? 'bg-emerald-500' : passedCount > 0 ? 'bg-yellow-500' : 'bg-white/10'}`} />
                            <summary className="list-none flex flex-col gap-2 pl-2 text-[10px] text-white/40 uppercase tracking-widest font-bold">
                                <div className="flex justify-between items-center w-full">
                                    <div className="flex items-center gap-2">
                                        <span>05. Rule Checklist</span>
                                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono ${passedCount === totalRules ? 'bg-emerald-500/20 text-emerald-400' : passedCount > 0 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-white/10 text-white/40'}`}>
                                            {passedCount === totalRules ? '\u2713 ' : ''}{passedCount}/{totalRules} Passed
                                        </span>
                                    </div>
                                    <span className="group-open:hidden">Show</span>
                                    <span className="hidden group-open:block hover:text-white/80 transition-colors">Hide</span>
                                </div>
                                <div className={`text-[10px] font-mono font-bold tracking-wider normal-case px-2 py-1.5 rounded border w-full ${verdictClass}`}>
                                    Verdict: {verdictText}
                                </div>
                            </summary>
                            <div className="space-y-1.5 pt-2 border-t border-white/5 mt-2 pl-2">
                                <div className="flex items-center gap-2 text-[10px]">
                                    <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${amtResult?.marketState !== 'DEAD' ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-red-500/20 border-red-500/50 text-red-400'}`}>
                                        {amtResult?.marketState !== 'DEAD' ? '✓' : '✗'}
                                    </div>
                                    <span className="text-white/60 w-24">AAA PRE-1</span>
                                    <span className="text-white/40 font-mono text-[9px]">Session {amtResult?.marketState || 'BALANCED'}</span>
                                </div>
                                <div className="flex items-center gap-2 text-[10px]">
                                    <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${currentLtp && amtResult?.valueAreaLow && (Math.abs(currentLtp - (currentLtp > amtResult.sessionVwap! ? amtResult.valueAreaHigh! : amtResult.valueAreaLow!)) < distThreshold || Math.abs(amtResult.vwapDeviationSigmas || 0) >= 3.0) ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-red-500/20 border-red-500/50 text-red-400'}`}>
                                        {currentLtp && amtResult?.valueAreaLow && (Math.abs(currentLtp - (currentLtp > amtResult.sessionVwap! ? amtResult.valueAreaHigh! : amtResult.valueAreaLow!)) < distThreshold || Math.abs(amtResult.vwapDeviationSigmas || 0) >= 3.0) ? '✓' : '✗'}
                                    </div>
                                    <span className="text-white/60 w-24">MR Location</span>
                                    <span className="text-white/40 font-mono text-[9px]">
                                        {(() => {
                                            const sigma = amtResult?.vwapDeviationSigmas || 0;
                                            if (Math.abs(sigma) >= 3.0) return `⚠️ EXTREME EXTENSION — ${sigma > 0 ? '+' : ''}${sigma.toFixed(2)}σ (Fade Zone)`;
                                            
                                            const ltp = currentLtp;
                                            const vah = amtResult?.valueAreaHigh;
                                            const val = amtResult?.valueAreaLow;
                                            const poc = amtResult?.poc;
                                            const ibH = amtResult?.ibHigh;
                                            const ibL = amtResult?.ibLow;
                                            const breakDir = amtResult?.breakDirection;
                                            
                                            // IB break context (Fix 2: Initiative breakdown/breakout)
                                            if (ltp && ibL && ltp < ibL && breakDir === 'DOWN') {
                                                return `Price below IB Low (${ibL.toFixed(1)}) — Initiative breakdown, targets at 1.5x/2.0x IB extension`;
                                            }
                                            if (ltp && ibH && ltp > ibH && breakDir === 'UP') {
                                                return `Price above IB High (${ibH.toFixed(1)}) — Initiative breakout, targets at 1.5x/2.0x IB extension`;
                                            }
                                            
                                            // VA context (Fix 2: Clarify this is OPTION value area)
                                            if (ltp && val && ltp < val) {
                                                return `Price below option VAL (${val.toFixed(1)}) — Bearish auction, option premium discounted`;
                                            }
                                            if (ltp && vah && ltp > vah) {
                                                return `Price above option VAH (${vah.toFixed(1)}) — Bullish auction, option premium extended`;
                                            }
                                            
                                            // POC context
                                            if (ltp && poc) {
                                                const pocDist = Math.abs(ltp - poc);
                                                const threshold = distThreshold * 2;
                                                if (pocDist < threshold) return `Price at option POC (${poc.toFixed(1)}) — Fair value, no edge`;
                                                return ltp < poc ? `Price below option POC — Lower value area, seek support` : `Price above option POC — Upper value area, seek resistance`;
                                            }
                                            
                                            return 'Price in mid-range — No structural reference';
                                        })()}
                                    </span>
                                </div>
                                
                                {/* P1-11: Prior Day Levels */}
                                {amtResult && (amtResult.priorVah || amtResult.priorVal || amtResult.priorPoc) && (
                                    <div className="mt-1 pl-5 flex flex-wrap gap-2 opacity-50">
                                        {amtResult.priorVah && <span className="text-[8px] font-mono">P-VAH: {amtResult.priorVah.toFixed(1)}</span>}
                                        {amtResult.priorVal && <span className="text-[8px] font-mono">P-VAL: {amtResult.priorVal.toFixed(1)}</span>}
                                        {amtResult.priorPoc && <span className="text-[8px] font-mono">P-POC: {amtResult.priorPoc.toFixed(1)}</span>}
                                    </div>
                                )}
                                <div className="flex items-center gap-2 text-[10px]">
                                    <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${amtResult?.marketState !== 'DEAD' ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-red-500/20 border-red-500/50 text-red-400'}`}>
                                        {amtResult?.marketState !== 'DEAD' ? '✓' : '✗'}
                                    </div>
                                    <span className="text-white/60 w-24">Volume Alive</span>
                                    <span className="text-white/40 font-mono text-[9px]">{amtResult?.marketState !== 'DEAD' ? 'ACTIVE' : 'DEAD'}</span>
                                </div>
                                <div className="flex items-center gap-2 text-[10px]">
                                    <div className={`w-3 h-3 rounded-full flex items-center justify-center border ${agentDecision?.timing === 'ENTER_NOW' ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'bg-white/10 border-white/20 text-white/60'}`}>
                                        {agentDecision?.timing === 'ENTER_NOW' ? '✓' : '⏸'}
                                    </div>
                                    <span className="text-white/60 w-24">Timing</span>
                                    {(() => {
                                        const timing = agentDecision?.timing || 'SKIP';
                                        const timeWindow = amtResult?.amtTimeWindow;
                                        
                                        if (!timeWindow) return <span className="text-white/40 font-mono text-[9px]">{timing}</span>;
                                        
                                        const timingColor = timing === 'ENTER_NOW' ? 'text-emerald-400' : 
                                                            timing === 'WAIT' ? 'text-yellow-400' : 'text-white/40';
                                        
                                        return (
                                            <div className="flex flex-col gap-0.5">
                                                <span className={`font-mono text-[9px] font-bold ${timingColor}`}>{timing}</span>
                                                <span className="text-[8px] text-white/30">{timeWindow.label}</span>
                                            </div>
                                        );
                                    })()}
                                </div>
                            </div>
                            <div className="mt-2 pt-2 border-t border-white/5 pl-2">
                                <span className="text-[9px] text-white/30 cursor-pointer hover:text-white/70 transition-colors">View Rule Book</span>
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
                            {extractDecisionText(displayAnalysis.rationale || displayAnalysis.rawOutput, 'QUANT_MONITORING_NO_EDGE')}
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
