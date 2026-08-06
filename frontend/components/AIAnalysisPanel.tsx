import React, { useMemo } from 'react';
import { GenAIAnalysis, AMTAnalysis, Portfolio, RiskState, LLMHistoryEntry, AgentDecision, OrderBook, QuantDecisionAnalysis } from '../types';
import { Zap, Clock } from 'lucide-react';
import {
    EquityPanel,
    RiskStateDisplay,
    DecisionHistoryPanel,
    QuantDecisionCard,
    MarketStateCard,
    LocationCard,
    AggressionCard,
    OrderFlowCard,
    InitialBalanceCard,
    LvnPlayCard,
    AbsorptionCard,
    VwapContextCard,
    AgentProbabilityCard,
    OverseerCard,
    TradePlanCard,
    RecentExitsCard,
    DiagnosticsPanel,
    ModelIoFooter,
} from './ai';

interface AIAnalysisPanelProps {
    analysis: GenAIAnalysis | null;
    amtResult: AMTAnalysis | null;
    portfolio: Portfolio;
    riskState?: RiskState | null;
    agentDecision?: AgentDecision | null;
    llmHistory?: LLMHistoryEntry[];
    orderBook?: OrderBook | null;
    overseerAction?: string;
    overseerReason?: string;
    quantDecision?: QuantDecisionAnalysis | null;
    symbol?: string;
    data?: any[];
}

/**
 * Wraps the legacy AMT-driven analysis body. When a quant decision is present
 * the legacy body is the SECONDARY view: collapsed into a grayed details block.
 * Without a quant decision the body renders unwrapped (current behaviour).
 */
const LegacyAmtWrapper: React.FC<{
    quantDecision: QuantDecisionAnalysis | null | undefined;
    children: React.ReactNode;
}> = ({ quantDecision, children }) => {
    if (!quantDecision) return <>{children}</>;
    return (
        <details className="rounded-md border border-glassy-border-subtle bg-glassy-bg-elevated/30">
            <summary className="list-none flex items-center justify-between px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-glassy-text-tertiary cursor-pointer select-none">
                <span className="flex items-center gap-1.5">
                    <Clock className="w-3 h-3" /> Legacy AMT Analysis
                </span>
                <span className="text-glassy-text-disabled">Expand</span>
            </summary>
            <div className="opacity-60 px-2 pb-2">{children}</div>
        </details>
    );
};

const AIAnalysisPanelInner: React.FC<AIAnalysisPanelProps> = ({ analysis, amtResult, portfolio, riskState, agentDecision, llmHistory = [], orderBook, overseerAction, overseerReason, quantDecision, symbol, data = [] }) => {
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

    // Market state from AMT (real-time) not LLM (stale)
    const liveMarketState = amtResult?.marketState || displayAnalysis.marketState || 'BALANCED';
    const isImbalanced = liveMarketState === 'IMBALANCED';

    // Determine Status Color based on market state (not LLM direction)
    const statusColor = isImbalanced ? "text-orange-400" : "text-blue-300";
    const statusBg = isImbalanced ? "bg-orange-500/20" : "bg-blue-500/20";

    // Location Data
    const poc = useMemo(() => amtResult?.poc?.toFixed(2) || "---", [amtResult?.poc]);

    // 1. Fallback: If both are missing -> Initializing
    if (!analysis && !amtResult) {
        return (
            <div className="bg-glassy-bg-tertiary border border-glassy-border-default rounded-md p-4 flex flex-col gap-4 font-sans text-glassy-text-secondary shadow-xl opacity-70">
                <div className="flex justify-between items-start">
                    <div className="flex items-center gap-2">
                        <Zap className="w-5 h-5 text-glassy-text-disabled" />
                        <div>
                            <h2 className="text-sm font-bold tracking-wider text-glassy-text-primary uppercase">Fabio Playbook</h2>
                            <div className="text-[9px] text-glassy-text-disabled font-mono tracking-widest uppercase">Connecting to feed...</div>
                        </div>
                    </div>
                </div>
                <div className="h-32 flex items-center justify-center">
                    <div className="text-xs text-glassy-text-disabled animate-pulse">Waiting for Market Data...</div>
                </div>
            </div>
        );
    }

    return (
        <div className="bg-glassy-bg-tertiary border border-glassy-border-default rounded-md p-4 flex flex-col gap-4 font-sans text-glassy-text-secondary shadow-xl">

            {/* 0. Header (Sticky Top Bar) */}
            <div className="sticky top-0 z-20 bg-glassy-bg-tertiary/95 backdrop-blur-xl pb-3 mb-2 border-b border-glassy-border-default">
                <div className="flex justify-between items-start mb-3 pt-2">
                    <div className="flex items-center gap-2">
                        <Zap className="w-5 h-5 text-glassy-ai-primary fill-glassy-ai-primary/20" />
                        <div>
                            <h2 className="text-sm font-bold tracking-wider text-glassy-text-primary uppercase flex items-center gap-2">
                                Fabio Playbook
                                <span className="px-1.5 py-0.5 bg-glassy-neutral-cool/20 rounded-sm border border-glassy-neutral-cool/30 text-[8px] text-glassy-neutral-cool uppercase tracking-widest leading-none">
                                    {portfolio.leverage}x
                                </span>
                            </h2>
                            <div className="text-[9px] text-glassy-text-tertiary font-mono tracking-wider uppercase">Execution Engine</div>
                        </div>
                    </div>
                </div>

                {/* Equity Panel (Header) */}
                <EquityPanel portfolio={portfolio} openPnl={openPnl} />

                {/* Risk State Warning */}
                <RiskStateDisplay riskState={riskState} />

                {/* LLM Timeout / Quant Only Banner */}
                {!analysis && amtResult && (
                    <div className="mt-2 px-3 py-1.5 bg-glassy-warning/10 border border-glassy-warning/20 rounded-sm flex items-center gap-2 animate-pulse">
                        <Clock className="w-3.5 h-3.5 text-glassy-warning" />
                        <span className="text-[9px] font-bold text-glassy-warning uppercase tracking-wider">
                            LLM Timeout — Running on Quant Logic Only
                        </span>
                    </div>
                )}
            </div>

            {/* 00. QUANT DECISION — PRIMARY */}
            <QuantDecisionCard quantDecision={quantDecision} />

            <LegacyAmtWrapper quantDecision={quantDecision}>

            {/* 01. STATE */}
            <MarketStateCard
                marketState={liveMarketState}
                isImbalanced={isImbalanced}
                statusColor={statusColor}
                statusBg={statusBg}
                hasDisplacement={amtResult?.hasDisplacement}
                legPoc={amtResult?.legPoc}
                legVah={amtResult?.legVah}
                legVal={amtResult?.legVal}
            />

            {/* 02. LOCATION */}
            <LocationCard currentLtp={currentLtp} amtResult={amtResult} poc={poc} />

            {/* 03. AGGRESSION */}
            <AggressionCard deltaScore={deltaScore} aggScore={aggScore} />

            {/* 03b. MARKET METRICS — Verification Bars */}
            <OrderFlowCard amtResult={amtResult} symbol={symbol} orderBook={orderBook} />

            {/* 03d. INITIAL BALANCE + BREAKS */}
            <InitialBalanceCard amtResult={amtResult} currentLtp={currentLtp} />

            {/* 03e. LVN VELOCITY PLAY */}
            <LvnPlayCard lvnPlay={amtResult?.lvnPlay} />

            {/* Items 3.16-3.17: Absorption & Large Print Detection */}
            <AbsorptionCard amtResult={amtResult} />

            {/* 03f. VWAP + PRIOR DAY */}
            <VwapContextCard amtResult={amtResult} currentLtp={currentLtp} />

            {/* 04. PROBABILITY ENGINE */}
            <AgentProbabilityCard agentDecision={agentDecision} isSecondDrive={amtResult?.isSecondDrive} />

            {/* 04b. OVERSEER */}
            <OverseerCard overseerAction={overseerAction} overseerReason={overseerReason} hasPositions={portfolio.positions.length > 0} />

            {/* 04c. TRADE PLAN — Open Positions with SL/TP/Trail */}
            <TradePlanCard positions={portfolio.positions} />

            {/* Recent Closed Trades */}
            <RecentExitsCard closedTrades={portfolio.closedTrades} />

            {/* DIAGNOSTICS TIER — collapsed by default */}
            <DiagnosticsPanel amtResult={amtResult} currentLtp={currentLtp} agentDecision={agentDecision} />

            </LegacyAmtWrapper>

            {/* MODEL I/O Footer */}
            <ModelIoFooter analysis={displayAnalysis} />

            {/* 06. LLM DECISION HISTORY */}
            <DecisionHistoryPanel llmHistory={llmHistory} />

        </div>
    );
};

// Wrap in React.memo to avoid re-renders when parent state changes
// but AIAnalysisPanel props have not changed.
export const AIAnalysisPanel = React.memo(AIAnalysisPanelInner);
