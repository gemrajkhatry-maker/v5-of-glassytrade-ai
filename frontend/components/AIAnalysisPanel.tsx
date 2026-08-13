import React, { useMemo } from 'react';
import { AMTAnalysis, Portfolio, RiskState, DecisionHistoryEntry, AgentDecision, OrderBook, QuantDecisionAnalysis } from '../types';
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
    TradePlanCard,
    RecentExitsCard,
    DiagnosticsPanel,
} from './ai';

interface AIAnalysisPanelProps {
    amtResult: AMTAnalysis | null;
    portfolio: Portfolio;
    riskState?: RiskState | null;
    agentDecision?: AgentDecision | null;
    decisionHistory?: DecisionHistoryEntry[];
    orderBook?: OrderBook | null;
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

const AIAnalysisPanelInner: React.FC<AIAnalysisPanelProps> = ({ amtResult, portfolio, riskState, agentDecision, decisionHistory = [], orderBook, quantDecision, symbol, data = [] }) => {
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

    // Memoize open PnL calculation (used 3 times in render)
    const openPnl = useMemo(() =>
        portfolio.positions.reduce((acc, p) => acc + p.pnl, 0),
        [portfolio.positions]
    );

    // Aggression from live AMT data (deterministic)
    const aggScore = amtResult?.aggression ?? 0;

    // Per-symbol delta score from backend
    const deltaScore = amtResult?.deltaNormalizedOption ?? 0;

    // Market state from AMT (real-time)
    const liveMarketState = amtResult?.marketState || 'BALANCED';
    const isImbalanced = liveMarketState === 'IMBALANCED';

    // Determine Status Color based on market state
    const statusColor = isImbalanced ? "text-orange-400" : "text-blue-300";
    const statusBg = isImbalanced ? "bg-orange-500/20" : "bg-blue-500/20";

    // Location Data
    const poc = useMemo(() => amtResult?.poc?.toFixed(2) || "---", [amtResult?.poc]);

    // 1. Fallback: If both are missing -> Initializing
    if (!amtResult && !quantDecision) {
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

            {/* 04c. TRADE PLAN — Open Positions with SL/TP/Trail */}
            <TradePlanCard positions={portfolio.positions} />

            {/* Recent Closed Trades */}
            <RecentExitsCard closedTrades={portfolio.closedTrades} />

            {/* DIAGNOSTICS TIER — collapsed by default */}
            <DiagnosticsPanel amtResult={amtResult} currentLtp={currentLtp} agentDecision={agentDecision} />

            </LegacyAmtWrapper>

            {/* 06. DECISION HISTORY */}
            <DecisionHistoryPanel decisionHistory={decisionHistory} />

        </div>
    );
};

// Wrap in React.memo to avoid re-renders when parent state changes
// but AIAnalysisPanel props have not changed.
export const AIAnalysisPanel = React.memo(AIAnalysisPanelInner);
