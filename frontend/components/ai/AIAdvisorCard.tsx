import React, { useMemo } from 'react';
import {
    Brain,
    Sparkles,
    ShieldCheck,
    AlertTriangle,
    Activity,
    CheckCircle2,
    XCircle,
    TrendingUp,
    TrendingDown,
    Minus,
    Cpu,
    Layers,
    ShieldAlert,
    Target,
    Clock,
    Lock,
    Crosshair,
    Radar,
    Info,
} from 'lucide-react';
import { AgentDecision, QuantDecisionAnalysis, GateResult, Portfolio } from '../../types';

interface AIAdvisorCardProps {
    agentDecision?: AgentDecision | null;
    quantDecision?: QuantDecisionAnalysis | null;
    portfolio?: Portfolio | null;
}

export const AIAdvisorCard: React.FC<AIAdvisorCardProps> = React.memo(({ agentDecision, quantDecision, portfolio }) => {
    if (!agentDecision) return null;

    const rawDecision = (agentDecision || {}) as AgentDecision;
    const openPos = portfolio?.positions?.find(p => p.status === 'OPEN' || (p.size !== undefined && p.size !== 0));
    const role = (rawDecision.role || (rawDecision.activePosition || openPos ? 'POSITION_MANAGEMENT' : 'SCANNING')).toUpperCase();
    const isPositionMgmt = role === 'POSITION_MANAGEMENT' || Boolean(rawDecision.activePosition) || Boolean(openPos);

    const direction = (rawDecision.direction || (openPos ? openPos.side : 'FLAT')).toUpperCase();
    const action = (rawDecision.action || (isPositionMgmt ? 'HOLD' : (direction !== 'FLAT' ? `ENTER_${direction}` : 'FLAT'))).toUpperCase();
    const setup = rawDecision.setup || (isPositionMgmt ? 'POSITION_MGMT' : 'AMT_AUCTION');
    const reason = rawDecision.reason;
    const confidence = rawDecision.confidence || (direction !== 'FLAT' ? 'High' : 'Low');
    const confidenceScore = rawDecision.confidenceScore ?? (confidence === 'High' ? 0.85 : confidence === 'Medium' ? 0.55 : 0.25);
    const rationale = rawDecision.rationale || (isPositionMgmt
        ? `Managing open ${direction} position: tracking trailing stop and value area acceptance.`
        : 'Analyzing volume profile, multi-step horizon, and auction order flow...');
    const source = rawDecision.source || 'TIMESFM_3.0';
    const isAdvisory = rawDecision.isAdvisory ?? /TIMESFM|LLM/i.test(source);
    const latencyMs = rawDecision.latencyMs ?? (rawDecision.latencyUs ? Math.round(rawDecision.latencyUs / 1000) : undefined);

    const forecastSteps = rawDecision.forecastSteps || [];
    const quantileSpread = rawDecision.quantileSpread ?? 0.0;
    const meanForecast = rawDecision.meanForecast ?? (openPos?.currentPrice || openPos?.entryPrice || 0.0);
    const gateResults: GateResult[] = rawDecision.gateResults || [];
    const modelVersions = rawDecision.modelVersions || { timesfm: '3.0' };
    const activePosition = rawDecision.activePosition || (openPos ? {
        side: openPos.side,
        entryPrice: openPos.entryPrice,
        currentPrice: openPos.currentPrice ?? openPos.entryPrice,
        pnl: openPos.pnl ?? 0,
        stopLoss: openPos.stopLoss,
        takeProfit: openPos.takeProfit,
        barsHeld: 0,
        isRiskFree: Boolean(openPos.side === 'LONG' ? (openPos.stopLoss && openPos.stopLoss >= openPos.entryPrice) : (openPos.stopLoss && openPos.stopLoss <= openPos.entryPrice)),
    } : undefined);
    const dynamicTrailStop = rawDecision.dynamicTrailStop || openPos?.stopLoss;

    // Check agreement with deterministic quant decision
    const quantDir = (quantDecision?.signal?.type || 'FLAT').toUpperCase();
    const isAligned = direction === quantDir;

    // Horizon step breakdown
    const stepCounts = useMemo(() => {
        let longCount = 0;
        let shortCount = 0;
        let flatCount = 0;
        forecastSteps.forEach((s) => {
            const step = String(s).toUpperCase();
            if (step === 'LONG') longCount++;
            else if (step === 'SHORT') shortCount++;
            else flatCount++;
        });
        return { longCount, shortCount, flatCount, total: forecastSteps.length };
    }, [forecastSteps]);

    // Role-specific action pill configuration
    const actionConfig = useMemo(() => {
        if (action === 'HOLD') {
            return {
                badge: 'text-emerald-400 border-emerald-500/40 bg-emerald-500/15 shadow-[0_0_12px_rgba(16,185,129,0.25)]',
                icon: <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />,
                label: 'HOLD (TREND INTACT)',
            };
        }
        if (action === 'TIGHTEN_SL') {
            return {
                badge: 'text-cyan-400 border-cyan-500/40 bg-cyan-500/15 shadow-[0_0_12px_rgba(6,182,212,0.25)]',
                icon: <Lock className="w-3.5 h-3.5 text-cyan-400" />,
                label: 'TIGHTEN SL (RISK-ZERO)',
            };
        }
        if (action === 'TAKE_PROFIT') {
            return {
                badge: 'text-amber-400 border-amber-500/40 bg-amber-500/15 shadow-[0_0_12px_rgba(245,158,11,0.25)]',
                icon: <Target className="w-3.5 h-3.5 text-amber-400" />,
                label: 'TAKE PROFIT (SCALE OUT)',
            };
        }
        if (action === 'EXIT') {
            return {
                badge: 'text-rose-400 border-rose-500/40 bg-rose-500/15 shadow-[0_0_12px_rgba(244,63,94,0.25)]',
                icon: <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />,
                label: `EXIT (${reason || 'THESIS FLIP'})`,
            };
        }
        if (direction === 'LONG' || action === 'ENTER_LONG') {
            return {
                badge: 'text-emerald-400 border-emerald-500/40 bg-emerald-500/15 shadow-[0_0_12px_rgba(16,185,129,0.25)]',
                icon: <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />,
                label: 'LONG (ENTER)',
            };
        }
        if (direction === 'SHORT' || action === 'ENTER_SHORT') {
            return {
                badge: 'text-rose-400 border-rose-500/40 bg-rose-500/15 shadow-[0_0_12px_rgba(244,63,94,0.25)]',
                icon: <TrendingDown className="w-3.5 h-3.5 text-rose-400" />,
                label: 'SHORT (ENTER)',
            };
        }
        return {
            badge: 'text-slate-400 border-white/10 bg-white/5',
            icon: <Minus className="w-3.5 h-3.5 text-slate-400" />,
            label: 'FLAT (NO EDGE)',
        };
    }, [action, direction, reason]);

    const confBadge = useMemo(() => {
        if (confidence === 'High') {
            return 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10';
        }
        if (confidence === 'Medium') {
            return 'text-amber-300 border-amber-500/30 bg-amber-500/10';
        }
        return 'text-slate-400 border-white/10 bg-slate-800/40';
    }, [confidence]);

    return (
        <div className="p-3.5 rounded-xl border border-purple-500/25 bg-gradient-to-br from-purple-950/20 via-slate-950/40 to-black/60 backdrop-blur-md shadow-[0_0_20px_rgba(168,85,247,0.08)] space-y-3 font-sans">
            {/* Header: Title + Role Badge + Model Tags + Latency */}
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-purple-500"></span>
                    </span>
                    <span className="text-[10.5px] font-extrabold uppercase tracking-wider text-purple-200 flex items-center gap-1.5">
                        <Brain className="w-3.5 h-3.5 text-purple-400" />
                        AI Market Thesis
                    </span>

                    {/* Advisory vs Deterministic Badge */}
                    <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[8.5px] font-mono font-bold uppercase tracking-wider border ${
                            isAdvisory
                                ? 'bg-amber-500/15 text-amber-300 border-amber-500/35 shadow-[0_0_8px_rgba(245,158,11,0.2)]'
                                : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/35 shadow-[0_0_8px_rgba(16,185,129,0.2)]'
                        }`}
                        title="Advisory signals are for reference only. Real orders are placed by the deterministic AMT engine."
                    >
                        {isAdvisory ? <Info className="w-2.5 h-2.5 text-amber-400" /> : <ShieldCheck className="w-2.5 h-2.5 text-emerald-400" />}
                        {isAdvisory ? 'Advisory' : 'Deterministic'}
                    </span>

                    {/* Dynamic Role Badge */}
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[8.5px] font-mono font-bold uppercase tracking-wider border ${
                        isPositionMgmt
                            ? 'bg-amber-500/15 text-amber-300 border-amber-500/35 shadow-[0_0_8px_rgba(245,158,11,0.2)]'
                            : 'bg-cyan-500/15 text-cyan-300 border-cyan-500/35 shadow-[0_0_8px_rgba(6,182,212,0.2)]'
                    }`}>
                        {isPositionMgmt ? <Crosshair className="w-2.5 h-2.5 text-amber-400" /> : <Radar className="w-2.5 h-2.5 text-cyan-400" />}
                        Role: {isPositionMgmt ? 'Position Manager' : 'Auction Scanner'}
                    </span>
                </div>

                <div className="flex items-center gap-1.5 flex-wrap">
                    {/* Model Version Chips */}
                    {modelVersions.timesfm && (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-mono font-semibold bg-cyan-500/10 text-cyan-300 border border-cyan-500/25">
                            <Cpu className="w-2.5 h-2.5" />
                            TimesFM {modelVersions.timesfm}
                        </span>
                    )}
                    {latencyMs !== undefined && latencyMs > 0 && (
                        <span className="px-1.5 py-0.5 rounded text-[8px] font-mono text-slate-400 bg-white/5 border border-white/10">
                            {latencyMs}ms
                        </span>
                    )}
                    <span className="px-1.5 py-0.5 rounded text-[8px] font-mono font-bold uppercase tracking-wider bg-purple-500/15 text-purple-300 border border-purple-500/25">
                        {source}
                    </span>
                </div>
            </div>

            {/* Deterministic AMT Signal (Primary - Real Orders) */}
            {!isAdvisory && quantDecision?.signal && (
                <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-500/25 space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[9px] font-mono font-bold uppercase tracking-wider text-emerald-300">
                        <ShieldCheck className="w-3 h-3 text-emerald-400" />
                        Deterministic AMT Signal — Primary
                    </div>
                    <div className="flex items-center gap-3 text-[9px] font-mono text-slate-300 flex-wrap">
                        <span className="font-bold text-emerald-200 uppercase">{quantDecision.signal.type}</span>
                        <span>Entry: <strong className="text-slate-200">₹{quantDecision.signal.entry}</strong></span>
                        <span>SL: <strong className="text-rose-300">₹{quantDecision.signal.sl}</strong></span>
                        <span>TP: <strong className="text-emerald-300">₹{quantDecision.signal.tp}</strong></span>
                        <span>RR: <strong className="text-slate-200">{quantDecision.signal.rr.toFixed(2)}</strong></span>
                        <span className="text-slate-500">{quantDecision.signal.modelLabel}</span>
                    </div>
                </div>
            )}

            {/* Separator: Deterministic vs Advisory */}
            {isAdvisory && (
                <div className="flex items-center gap-2 py-1">
                    <div className="flex-1 h-px bg-gradient-to-r from-transparent via-amber-500/40 to-transparent"></div>
                    <span className="text-[8px] font-mono font-bold uppercase tracking-widest text-amber-400/80 flex items-center gap-1">
                        <Info className="w-2.5 h-2.5" />
                        Advisory Only — No Order Impact
                    </span>
                    <div className="flex-1 h-px bg-gradient-to-r from-transparent via-amber-500/40 to-transparent"></div>
                </div>
            )}

            {/* Action + Setup + Conviction + Metrics */}
            <div className="flex items-center justify-between gap-2 flex-wrap bg-black/30 p-2 rounded-lg border border-white/5">
                <div className="flex items-center gap-2 flex-wrap">
                    {/* Action Pill */}
                    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-mono font-black border uppercase tracking-wider ${actionConfig.badge}`}>
                        {actionConfig.icon}
                        <span>{actionConfig.label}</span>
                    </div>

                    {/* Setup / Reason Tag */}
                    <span className="px-2 py-1 rounded text-[8.5px] font-mono font-semibold bg-white/5 text-slate-300 border border-white/10 uppercase">
                        {reason ? `REASON: ${reason}` : setup}
                    </span>

                    {/* Conviction Badge */}
                    <div className={`flex items-center gap-1.5 px-2 py-1 rounded text-[8.5px] font-mono font-semibold border ${confBadge}`}>
                        <span>{confidence} Conviction</span>
                        <span className="text-[7.5px] opacity-75 font-mono">({Math.round(confidenceScore * 100)}%)</span>
                    </div>
                </div>

                {/* Horizon Metrics: Spread & Forecast Price */}
                <div className="flex items-center gap-2 text-[9px] font-mono text-slate-300">
                    {meanForecast > 0 && (
                        <div className="flex items-center gap-1 bg-white/5 px-2 py-0.5 rounded border border-white/5">
                            <span className="text-slate-500">Forecast:</span>
                            <span className="font-bold text-slate-200">₹{meanForecast.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
                        </div>
                    )}
                    {quantileSpread > 0 && (
                        <div className="flex items-center gap-1 bg-white/5 px-2 py-0.5 rounded border border-white/5">
                            <span className="text-slate-500">Spread:</span>
                            <span className="font-semibold text-purple-300">±{quantileSpread.toFixed(2)}</span>
                        </div>
                    )}
                </div>
            </div>

            {/* Active Position Management Details Strip (When In Live Trade) */}
            {isPositionMgmt && activePosition && (
                <div className="p-2 rounded-lg bg-gradient-to-r from-amber-950/20 via-slate-900/60 to-black/40 border border-amber-500/20 flex items-center justify-between gap-2 flex-wrap text-[8.5px] font-mono">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-amber-300 uppercase flex items-center gap-1">
                            <Crosshair className="w-2.5 h-2.5 text-amber-400" />
                            {activePosition.side} @ ₹{activePosition.entryPrice}
                        </span>
                        <span className="text-slate-400">
                            Curr: <strong className="text-slate-200">₹{activePosition.currentPrice}</strong>
                        </span>
                        <span className={`${activePosition.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'} font-bold`}>
                            PnL: {activePosition.pnl >= 0 ? `+₹${activePosition.pnl}` : `-₹${Math.abs(activePosition.pnl)}`}
                        </span>
                        {dynamicTrailStop !== null && dynamicTrailStop !== undefined && (
                            <span className="text-cyan-300 bg-cyan-950/30 px-1.5 py-0.5 rounded border border-cyan-500/20">
                                Trail SL: <strong>₹{dynamicTrailStop}</strong>
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-2 text-slate-400 text-[8px]">
                        <span className="flex items-center gap-0.5">
                            <Clock className="w-2.5 h-2.5 text-slate-400" />
                            {activePosition.barsHeld} bars held
                        </span>
                        <span className={`px-1.5 py-0.5 rounded font-bold ${
                            activePosition.isRiskFree
                                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                                : 'bg-slate-800 text-slate-400 border border-white/5'
                        }`}>
                            {activePosition.isRiskFree ? 'Risk-Free Locked' : 'Risk Active'}
                        </span>
                    </div>
                </div>
            )}

            {/* 32-Step Multi-Horizon Forecast Strip */}
            {forecastSteps.length > 0 && (
                <div className="p-2 rounded-lg bg-black/40 border border-white/5 space-y-1.5">
                    <div className="flex items-center justify-between text-[8px] font-mono text-slate-400">
                        <span className="uppercase tracking-wider flex items-center gap-1 text-slate-400 font-bold">
                            <Layers className="w-2.5 h-2.5 text-cyan-400" />
                            TimesFM 32-Step Forecast Horizon
                        </span>
                        <div className="flex items-center gap-2 text-[7.5px]">
                            {stepCounts.longCount > 0 && (
                                <span className="text-emerald-400 font-semibold">{stepCounts.longCount} Long</span>
                            )}
                            {stepCounts.shortCount > 0 && (
                                <span className="text-rose-400 font-semibold">{stepCounts.shortCount} Short</span>
                            )}
                            {stepCounts.flatCount > 0 && (
                                <span className="text-slate-400 font-semibold">{stepCounts.flatCount} Flat</span>
                            )}
                        </div>
                    </div>

                    {/* Step Visualizer Pills */}
                    <div className="flex items-center gap-0.5 w-full pt-0.5">
                        {forecastSteps.map((step, idx) => {
                            const s = String(step).toUpperCase();
                            const stepColor = s === 'LONG'
                                ? 'bg-emerald-500 hover:bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.4)]'
                                : s === 'SHORT'
                                ? 'bg-rose-500 hover:bg-rose-400 shadow-[0_0_6px_rgba(244,63,94,0.4)]'
                                : 'bg-slate-850 hover:bg-slate-700 bg-slate-800/80';
                            return (
                                <div
                                    key={idx}
                                    title={`Step +${idx + 1}: ${s}`}
                                    className={`flex-1 h-3 min-w-[2px] rounded-[1.5px] transition-colors cursor-pointer ${stepColor}`}
                                />
                            );
                        })}
                    </div>
                </div>
            )}

            {/* 4-Gate Pipeline Verification Results (When Scanning) */}
            {!isPositionMgmt && gateResults.length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 pt-0.5">
                    {gateResults.map((gate) => {
                        const passed = gate.passed;
                        return (
                            <div
                                key={gate.gate_no}
                                className={`p-1.5 rounded-md border text-[8px] font-mono flex flex-col justify-between ${
                                    passed
                                        ? 'bg-emerald-950/20 border-emerald-500/25 text-emerald-300'
                                        : 'bg-rose-950/20 border-rose-500/25 text-rose-300'
                                }`}
                            >
                                <div className="flex items-center justify-between">
                                    <span className="font-bold tracking-tight truncate">G{gate.gate_no}: {gate.gate_name}</span>
                                    {passed ? (
                                        <CheckCircle2 className="w-2.5 h-2.5 text-emerald-400 shrink-0 ml-1" />
                                    ) : (
                                        <XCircle className="w-2.5 h-2.5 text-rose-400 shrink-0 ml-1" />
                                    )}
                                </div>
                                {!passed && gate.message && (
                                    <span className="text-[7px] text-rose-400/80 truncate mt-0.5">
                                        {gate.message}
                                    </span>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Narrative Reasoning (AMT Institutional Thesis) */}
            <div className="p-2.5 rounded-lg bg-black/40 border border-purple-500/20 text-[9.5px] text-slate-200 leading-relaxed font-sans">
                <div className="flex items-start gap-2">
                    <Sparkles className="w-3.5 h-3.5 text-purple-400 shrink-0 mt-0.5" />
                    <p className="min-w-0 font-normal leading-relaxed text-slate-200">{rationale}</p>
                </div>
            </div>

            {/* Alignment Status with Quantitative Gate Engine */}
            <div className="flex items-center justify-between text-[8.5px] font-mono pt-1.5 border-t border-white/5 text-slate-400">
                <span className="text-slate-500 uppercase tracking-wider flex items-center gap-1">
                    <Activity className="w-2.5 h-2.5 text-purple-400" />
                    Quant Engine Alignment:
                </span>
                <span className={`font-semibold flex items-center gap-1 ${
                    isAligned
                        ? (direction === 'FLAT' ? 'text-slate-400' : 'text-emerald-400')
                        : 'text-amber-300'
                }`}>
                    {isAligned ? (
                        <>
                            <ShieldCheck className="w-3 h-3 text-emerald-400" />
                            {direction === 'FLAT' ? 'Aligned — No Setup' : `Aligned (${direction})`}
                        </>
                    ) : (
                        <>
                            <AlertTriangle className="w-3 h-3 text-amber-400" />
                            {`Divergent: Quant ${quantDir} vs AI ${direction}`}
                        </>
                    )}
                </span>
            </div>
        </div>
    );
});

AIAdvisorCard.displayName = 'AIAdvisorCard';
export default AIAdvisorCard;

