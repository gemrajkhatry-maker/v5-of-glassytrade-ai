import React from 'react';
import { GenAIAnalysis, AMTAnalysis, Portfolio } from '../types';
import { Brain, TrendingUp, TrendingDown, MinusCircle, Target, Activity, Settings, Zap } from 'lucide-react';

interface AIAnalysisPanelProps {
    analysis: GenAIAnalysis | null;
    amtResult: AMTAnalysis | null;
    portfolio: Portfolio;
}

export const AIAnalysisPanel: React.FC<AIAnalysisPanelProps> = ({ analysis, amtResult, portfolio }) => {
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
    const effectiveAnalysis: GenAIAnalysis = analysis || {
        direction: 'FLAT',
        rationale: "Monitoring market state and order flow. Waiting for Fabio Playbook setup.",
        confidence: 'Low',
        marketState: amtResult?.marketState || 'BALANCED',
        aggression: `Score:${amtResult?.aggression?.toFixed(2) || "0.00"}`
    };

    const displayAnalysis = effectiveAnalysis;

    // --- Helper: Format Logic ---
    const isLong = displayAnalysis.direction === 'LONG';
    const isShort = displayAnalysis.direction === 'SHORT';

    // Parse aggression
    const aggScore = parseFloat(displayAnalysis.aggression?.split(':')[1] || "0.00");

    // Determine Status Color
    const statusColor = isLong ? "text-green-400" : isShort ? "text-red-400" : "text-blue-300";
    const statusBg = isLong ? "bg-green-500/20" : isShort ? "bg-red-500/20" : "bg-blue-500/20";

    // Location Data
    const vah = amtResult?.valueAreaHigh?.toFixed(2) || "---";
    const val = amtResult?.valueAreaLow?.toFixed(2) || "---";
    const poc = amtResult?.poc?.toFixed(2) || "---";

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
                    <div className={`text-sm font-bold font-mono ${portfolio.positions.reduce((acc, p) => acc + p.pnl, 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {portfolio.positions.reduce((acc, p) => acc + p.pnl, 0) >= 0 ? '+' : ''}
                        ${portfolio.positions.reduce((acc, p) => acc + p.pnl, 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </div>
                </div>
            </div>

            {/* 01. STATE */}
            <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                    <span>01. State</span>
                    <Settings className="w-3 h-3 hover:text-white/80 transition-colors" />
                </div>
                <div className={`p-3 rounded-lg bg-white/5 border border-white/5 flex justify-between items-center ${statusBg}`}>
                    <div>
                        <div className={`text-sm font-bold ${statusColor} tracking-wide`}>
                            {displayAnalysis.marketState?.toUpperCase() || "BALANCED"}
                        </div>
                        <div className="text-[10px] text-white/50">
                            {displayAnalysis.marketState?.includes('Trend') ? 'Trend Mode' : 'Range Mode'}
                        </div>
                    </div>
                    {displayAnalysis.confidence === 'High' && <div className="h-2 w-2 rounded-full bg-blue-400 animate-pulse"></div>}
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

            {/* Footer Status */}
            <div className="mt-2 text-xs text-white/40 flex items-start gap-2 pt-2 border-t border-white/5">
                <div className={`mt-1 h-2 w-2 rounded-full ${displayAnalysis.direction !== 'FLAT' ? 'bg-green-500 animate-ping' : 'bg-slate-600'}`}></div>
                <div>
                    <div className="font-bold text-white/80 uppercase tracking-wider mb-1">
                        {displayAnalysis.direction === 'FLAT' ? "MONITORING MARKET" : `ENTRY SIGNAL: ${displayAnalysis.direction}`}
                    </div>
                    <p className="leading-relaxed font-light text-[10px] line-clamp-3">
                        {displayAnalysis.rationale.split('Trigger:')[0].trim() || "Analyzing order flow and market structure for Fabio Playbook setups."}
                    </p>
                    {displayAnalysis.inputPrompt && (
                        <div className="mt-2 space-y-1">
                            <details className="group">
                                <summary className="text-[9px] text-white/20 cursor-pointer hover:text-white/40 uppercase list-none flex items-center gap-1">
                                    <span>▶</span> Debug Input
                                </summary>
                                <div className="mt-1 p-1 bg-black/20 rounded text-[9px] font-mono text-white/40 max-w-[250px] overflow-hidden truncate">
                                    {analysis.inputPrompt.slice(0, 150)}...
                                </div>
                            </details>
                            <details className="group">
                                <summary className="text-[9px] text-white/20 cursor-pointer hover:text-white/40 uppercase list-none flex items-center gap-1">
                                    <span>▶</span> Debug Output
                                </summary>
                                <div className="mt-1 p-1 bg-black/20 rounded text-[9px] font-mono text-white/40 leading-relaxed whitespace-pre-wrap">
                                    {analysis.rawOutput || "No output captured."}
                                </div>
                            </details>
                        </div>
                    )}
                </div>
            </div>

        </div>
    );
};
