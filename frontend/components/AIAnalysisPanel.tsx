import React, { useMemo } from 'react';
import { AMTAnalysis, Portfolio, RiskState, LLMHistoryEntry, AgentDecision, OrderBook, QuantDecisionAnalysis, AuctionAnalysis } from '../types';
import { Zap } from 'lucide-react';
import {
    EquityPanel,
    RiskStateDisplay,
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
    VaFreezeCard,
    ThreeAIndicator,
    AIAdvisorCard,
} from './ai';

interface AIAnalysisPanelProps {
    amtResult: AMTAnalysis | null;
    portfolio: Portfolio;
    riskState?: RiskState | null;
    agentDecision?: AgentDecision | null;
    llmHistory?: LLMHistoryEntry[];
    orderBook?: OrderBook | null;
    overseerAction?: string;
    overseerReason?: string;
    quantDecision?: QuantDecisionAnalysis | null;
    auction?: AuctionAnalysis | null;
    symbol?: string;
    data?: any[];
}

const AIAnalysisPanelInner: React.FC<AIAnalysisPanelProps> = ({
    amtResult, portfolio, riskState, agentDecision,
    orderBook, overseerAction, overseerReason, quantDecision, auction, symbol, data = []
}) => {
    const currentLtp = React.useMemo(() => {
        const bestBid = orderBook?.bids?.[0]?.price ?? 0;
        const bestAsk = orderBook?.asks?.[0]?.price ?? 0;
        if (bestBid > 0 && bestAsk > 0) {
            return (bestBid + bestAsk) / 2;
        }
        if (data.length > 0) return data[data.length - 1].close;
        return amtResult?.sessionVwap && amtResult.sessionVwap > 0 ? amtResult.sessionVwap : 0;
    }, [orderBook, amtResult?.sessionVwap, data]);

    const openPnl = useMemo(() =>
        portfolio.positions.reduce((acc, p) => {
            if (p.pnl !== undefined) return acc + p.pnl;
            const price = currentLtp > 0 ? currentLtp : p.entryPrice;
            const size = p.size;
            return acc + ((price - p.entryPrice) * size);
        }, 0),
        [portfolio.positions, currentLtp]
    );

    const aggScore = useMemo(() => {
        const liveAggression = amtResult?.aggression ?? 0;
        return typeof liveAggression === 'number'
            ? liveAggression
            : 0;
    }, [amtResult?.aggression]);

    const deltaScore = useMemo(() => amtResult?.deltaNormalizedOption ?? 0, [amtResult?.deltaNormalizedOption]);

    const liveMarketState = amtResult?.marketState || 'BALANCED';
    const isImbalanced = liveMarketState === 'IMBALANCED';
    const statusColor = isImbalanced ? 'text-orange-400' : 'text-blue-300';
    const statusBg   = isImbalanced ? 'bg-orange-500/20' : 'bg-blue-500/20';
    const poc = useMemo(() => amtResult?.poc?.toFixed(2) || '---', [amtResult?.poc]);

    return (
        <div className="flex flex-col h-full bg-[#0c0d0f] border border-white/8 rounded-xl overflow-hidden shadow-2xl font-sans text-slate-300">

            {/* ── Sticky Header ── */}
            <div className="sticky top-0 z-20 bg-[#0c0d0f]/97 backdrop-blur-xl border-b border-white/8 px-4 pt-3 pb-2 space-y-2.5">

                {/* Title row */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-lg bg-emerald-500/15 border border-emerald-500/25 flex items-center justify-center">
                            <Zap className="w-3.5 h-3.5 text-emerald-400" />
                        </div>
                        <div>
                            <div className="text-[11px] font-extrabold tracking-[0.12em] text-white uppercase leading-none">
                                Fabio Playbook
                            </div>
                            <div className="text-[8.5px] text-slate-500 font-mono tracking-widest uppercase mt-0.5">
                                AMT · Value Area 70%
                            </div>
                        </div>
                    </div>
                    <ThreeAIndicator amt={amtResult} approved={quantDecision?.approved ?? false} />
                </div>

                {/* Source attribution — Structure source vs Execution source */}
                {symbol && (
                    <div className="flex items-center gap-1.5 text-[8px] font-mono text-slate-500 truncate">
                        <span className="text-slate-600 uppercase tracking-widest">Struct:</span>
                        <span className="text-slate-400">{symbol.split(' ')[0]} FUT</span>
                        <span className="text-slate-700 mx-0.5">·</span>
                        <span className="text-slate-600 uppercase tracking-widest">Exec:</span>
                        <span className="text-slate-400 truncate">{symbol}</span>
                    </div>
                )}

                {/* Equity */}
                <EquityPanel portfolio={portfolio} openPnl={openPnl} riskState={riskState} />

                {/* Risk alert */}
                <RiskStateDisplay riskState={riskState} />
            </div>

            {/* ── Scrollable body ── */}
            <div className="flex-1 overflow-y-auto overscroll-contain px-3 py-3 space-y-3">
                <QuantDecisionCard quantDecision={quantDecision} />
                <AIAdvisorCard agentDecision={agentDecision} quantDecision={quantDecision} />
                
                {/* Market State & Location */}
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
                <AggressionCard deltaScore={deltaScore} aggScore={aggScore} />
                <LocationCard currentLtp={currentLtp} amtResult={amtResult} poc={poc} />
                
                {/* Auction Context */}
                <VaFreezeCard auction={auction} />
                <AbsorptionCard amtResult={amtResult} />
                <LvnPlayCard lvnPlay={amtResult?.lvnPlay} />

                {/* Trade Management */}
                <OverseerCard
                    overseerAction={overseerAction}
                    overseerReason={overseerReason}
                    hasPositions={portfolio.positions.length > 0}
                />
                <TradePlanCard positions={portfolio.positions} />
                <RecentExitsCard closedTrades={portfolio.closedTrades} />

                {/* Advanced Diagnostics (collapsed by default) */}
                <details className="group">
                    <summary className="cursor-pointer select-none list-none flex items-center gap-1.5 px-2 py-1.5 rounded-lg border border-white/5 bg-white/3 hover:bg-white/5 transition-colors">
                        <span className="text-[9px] font-mono font-bold uppercase tracking-wider text-slate-500 group-open:text-slate-300">
                            ▶ Advanced Diagnostics
                        </span>
                    </summary>
                    <div className="mt-2 space-y-3">
                        <OrderFlowCard amtResult={amtResult} symbol={symbol} orderBook={orderBook} />
                        <InitialBalanceCard amtResult={amtResult} currentLtp={currentLtp} />
                        <VwapContextCard amtResult={amtResult} currentLtp={currentLtp} />
                        <AgentProbabilityCard agentDecision={agentDecision} isSecondDrive={amtResult?.isSecondDrive} />
                        <DiagnosticsPanel amtResult={amtResult} currentLtp={currentLtp} agentDecision={agentDecision} />
                    </div>
                </details>
            </div>
        </div>
    );
};

export const AIAnalysisPanel = React.memo(AIAnalysisPanelInner);
