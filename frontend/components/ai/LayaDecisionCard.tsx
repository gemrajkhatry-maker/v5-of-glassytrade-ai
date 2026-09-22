import React, { useMemo, useState } from 'react';
import {
    Zap,
    Brain,
    ShieldCheck,
    AlertTriangle,
    TrendingUp,
    TrendingDown,
    Minus,
    Cpu,
    Activity,
    Layers,
    CheckCircle2,
    XCircle,
    ChevronDown,
    ChevronUp,
    Gauge,
    Sparkles,
    Crosshair,
    Radar,
    Target,
    Lock,
    ShieldAlert,
} from 'lucide-react';
import { LayaDecision, QuantDecisionAnalysis, Portfolio } from '../../types';

interface LayaDecisionCardProps {
    layaDecision?: LayaDecision | null;
    quantDecision?: QuantDecisionAnalysis | null;
    portfolio?: Portfolio | null;
    collapsible?: boolean;
    defaultExpanded?: boolean;
}

export const LayaDecisionCard: React.FC<LayaDecisionCardProps> = React.memo(({
    layaDecision,
    quantDecision,
    portfolio,
    collapsible = true,
    defaultExpanded = true,
}) => {
    const [isExpanded, setIsExpanded] = useState(defaultExpanded);

    // Find active position from portfolio if present
    const openPos = portfolio?.positions?.find(p => p.status === 'OPEN' || (p.size !== undefined && p.size !== 0));

    // Fallback display if no decision is emitted yet
    const data: LayaDecision = useMemo(() => {
        if (layaDecision) return layaDecision;
        const isPos = Boolean(openPos);
        return {
            role: isPos ? 'POSITION_MANAGEMENT' : 'SCANNING',
            action: isPos ? 'HOLD' : 'FLAT',
            setup: isPos ? 'POSITION_MGMT' : 'NO_EDGE',
            probabilities: isPos
                ? { HOLD: 0.85, TIGHTEN_SL: 0.08, TAKE_PROFIT: 0.04, EXIT: 0.03 }
                : { ENTER_LONG: 0.10, ENTER_SHORT: 0.08, FLAT: 0.82 },
            confidence: 0.70,
            trade_permitted_p: 0.0,
            latency_ms: 13.2,
            source: 'LAYA_MLX_MULTILINGUAL',
            model: 'Laya-MLX (322M mmBERT)',
        };
    }, [layaDecision, openPos]);

    // Role resolution: SCANNING vs POSITION_MANAGEMENT
    const role = (data.role || (data.active_position || openPos ? 'POSITION_MANAGEMENT' : 'SCANNING')).toUpperCase();
    const isPositionMgmt = role === 'POSITION_MANAGEMENT' || Boolean(data.active_position) || Boolean(openPos);

    const rawAction = String(data.action || '').toUpperCase();
    const isMgmtAction = ['HOLD', 'TIGHTEN', 'PROFIT', 'EXIT'].some(k => rawAction.includes(k));
    const action = isPositionMgmt
        ? (isMgmtAction ? (rawAction.includes('HOLD') ? 'HOLD' : rawAction.includes('TIGHTEN') ? 'TIGHTEN_SL' : rawAction.includes('PROFIT') ? 'TAKE_PROFIT' : 'EXIT') : 'HOLD')
        : (rawAction || 'FLAT');
    const setup = isPositionMgmt
        ? (data.setup && data.setup !== 'NO_EDGE' ? String(data.setup).toUpperCase() : 'POSITION_MGMT')
        : String(data.setup || 'NO_EDGE').toUpperCase();
    const latency = data.latency_ms ?? 13.2;
    const model = data.model || 'Laya-MLX (322M mmBERT)';
    const tradePermittedP = data.trade_permitted_p ?? 0.0;
    const convictionScore = data.conviction_score ?? 2.0;
    const scoreMax = data.score_max ?? 4.0;
    const scorePercent = data.score_percent ?? Math.round((convictionScore / scoreMax) * 100);

    // Active position extraction
    const activePos = data.active_position || (openPos ? {
        side: openPos.side,
        entryPrice: openPos.entryPrice,
        currentPrice: openPos.currentPrice ?? openPos.entryPrice,
        pnl: openPos.pnl ?? 0,
        stopLoss: openPos.stopLoss,
        takeProfit: openPos.takeProfit,
        barsHeld: 0,
        isRiskFree: Boolean(openPos.side === 'LONG' ? (openPos.stopLoss && openPos.stopLoss >= openPos.entryPrice) : (openPos.stopLoss && openPos.stopLoss <= openPos.entryPrice)),
    } : undefined);

    // Probabilities for Scanning mode
    const scanningProbs = useMemo(() => {
        const p = data.probabilities || {};
        const longP = p.ENTER_LONG ?? p.BUY ?? p.LONG ?? 0.10;
        const shortP = p.ENTER_SHORT ?? p.SELL ?? p.SHORT ?? 0.10;
        const flatP = p.FLAT ?? p.HOLD ?? (1.0 - longP - shortP);
        const sum = (longP + shortP + flatP) || 1.0;
        return {
            long: Math.round((longP / sum) * 100),
            short: Math.round((shortP / sum) * 100),
            flat: Math.round((flatP / sum) * 100),
        };
    }, [data.probabilities]);

    // Probabilities for Position Management mode
    const mgmtProbs = useMemo(() => {
        const p = data.probabilities || {};
        const holdP = p.HOLD ?? 0.80;
        const tightenP = p.TIGHTEN_SL ?? 0.10;
        const tpP = p.TAKE_PROFIT ?? 0.05;
        const exitP = p.EXIT ?? 0.05;
        const sum = (holdP + tightenP + tpP + exitP) || 1.0;
        return {
            hold: Math.round((holdP / sum) * 100),
            tighten: Math.round((tightenP / sum) * 100),
            tp: Math.round((tpP / sum) * 100),
            exit: Math.round((exitP / sum) * 100),
        };
    }, [data.probabilities]);

    // Quant Alignment Check
    const quantDir = (quantDecision?.signal?.type || 'FLAT').toUpperCase();
    const isAligned = useMemo(() => {
        if (isPositionMgmt) {
            return action !== 'EXIT';
        }
        return (action.includes('LONG') && quantDir === 'LONG') ||
               (action.includes('SHORT') && quantDir === 'SHORT') ||
               (action === 'FLAT' && (quantDir === 'FLAT' || quantDir === 'HOLD'));
    }, [isPositionMgmt, action, quantDir]);

    // Visual Action Pill Config (Dual Role)
    const actionConfig = useMemo(() => {
        if (action === 'HOLD') {
            return {
                badge: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/15 shadow-[0_0_12px_rgba(16,185,129,0.25)]',
                icon: <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />,
                label: 'HOLD (TREND INTACT)',
            };
        }
        if (action === 'TIGHTEN_SL') {
            return {
                badge: 'text-cyan-300 border-cyan-500/40 bg-cyan-500/15 shadow-[0_0_12px_rgba(6,182,212,0.25)]',
                icon: <Lock className="w-3.5 h-3.5 text-cyan-400" />,
                label: 'TIGHTEN SL (RISK-ZERO)',
            };
        }
        if (action === 'TAKE_PROFIT') {
            return {
                badge: 'text-amber-300 border-amber-500/40 bg-amber-500/15 shadow-[0_0_12px_rgba(245,158,11,0.25)]',
                icon: <Target className="w-3.5 h-3.5 text-amber-400" />,
                label: 'TAKE PROFIT (SCALE OUT)',
            };
        }
        if (action === 'EXIT') {
            return {
                badge: 'text-rose-300 border-rose-500/40 bg-rose-500/15 shadow-[0_0_12px_rgba(244,63,94,0.25)]',
                icon: <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />,
                label: 'EXIT (ADVERSE FLOW)',
            };
        }
        if (action.includes('LONG') || action === 'BUY') {
            return {
                badge: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/15 shadow-[0_0_15px_rgba(16,185,129,0.3)]',
                icon: <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />,
                label: 'ENTER LONG',
            };
        }
        if (action.includes('SHORT') || action === 'SELL') {
            return {
                badge: 'text-rose-300 border-rose-500/40 bg-rose-500/15 shadow-[0_0_15px_rgba(244,63,94,0.3)]',
                icon: <TrendingDown className="w-3.5 h-3.5 text-rose-400" />,
                label: 'ENTER SHORT',
            };
        }
        return {
            badge: 'text-slate-300 border-slate-700/60 bg-slate-800/40',
            icon: <Minus className="w-3.5 h-3.5 text-slate-400" />,
            label: 'FLAT (NO EDGE)',
        };
    }, [action]);

    return (
        <div className="p-3.5 rounded-xl border border-cyan-500/30 bg-gradient-to-br from-cyan-950/40 via-slate-950/85 to-black/95 backdrop-blur-md shadow-[0_0_25px_rgba(6,182,212,0.15)] space-y-2.5 font-sans overflow-hidden flex flex-col">
            {/* Header: Title + Metal Badge + Dynamic Role Pill + Latency */}
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500"></span>
                    </span>
                    <span className="text-[10px] font-extrabold uppercase tracking-wider text-cyan-200 flex items-center gap-1">
                        <Zap className="w-3.5 h-3.5 text-cyan-400" />
                        Laya-MLX Neural Edge
                    </span>

                    {/* Apple Silicon Metal Badge */}
                    <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-mono font-bold uppercase tracking-wider border bg-cyan-500/15 text-cyan-300 border-cyan-500/35 shadow-[0_0_8px_rgba(6,182,212,0.2)]"
                        title="Native Apple MLX Metal Bidirectional Inference on Apple Silicon"
                    >
                        <Cpu className="w-2.5 h-2.5 text-cyan-400" />
                        Apple MLX Metal
                    </span>

                    {/* Dynamic Role Badge (Auction Scanner vs Position Manager) */}
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-mono font-bold uppercase tracking-wider border ${
                        isPositionMgmt
                            ? 'bg-amber-500/15 text-amber-300 border-amber-500/35 shadow-[0_0_8px_rgba(245,158,11,0.2)]'
                            : 'bg-cyan-500/15 text-cyan-300 border-cyan-500/35 shadow-[0_0_8px_rgba(6,182,212,0.2)]'
                    }`}>
                        {isPositionMgmt ? <Crosshair className="w-2.5 h-2.5 text-amber-400" /> : <Radar className="w-2.5 h-2.5 text-cyan-400" />}
                        Role: {isPositionMgmt ? 'Position Manager' : 'Auction Scanner'}
                    </span>
                </div>

                <div className="flex items-center gap-1.5 ml-auto">
                    {/* Latency badge */}
                    <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold border border-cyan-500/30 bg-cyan-500/10 text-cyan-300"
                        title="Median end-to-end forward pass latency on Apple Silicon"
                    >
                        <Gauge className="w-2.5 h-2.5 text-cyan-400" />
                        {latency.toFixed(1)}ms
                    </span>

                    {collapsible && (
                        <button
                            onClick={() => setIsExpanded(!isExpanded)}
                            className="p-1 rounded hover:bg-white/5 text-slate-400 hover:text-white transition-colors"
                            aria-label={isExpanded ? 'Collapse card' : 'Expand card'}
                        >
                            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                        </button>
                    )}
                </div>
            </div>

            {/* Main Action & Setup Display */}
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-mono font-bold uppercase tracking-wide ${actionConfig.badge}`}>
                        {actionConfig.icon}
                        {actionConfig.label}
                    </span>
                    <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded border border-white/10 bg-white/5 text-slate-300 uppercase">
                        {setup}
                    </span>
                </div>

                {/* Quant Engine Alignment Pill */}
                <div className="text-[9px] font-mono flex items-center gap-1">
                    {isAligned ? (
                        <span className="text-emerald-400 flex items-center gap-0.5 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                            <CheckCircle2 className="w-2.5 h-2.5" /> Aligned
                        </span>
                    ) : (
                        <span className="text-amber-400 flex items-center gap-0.5 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
                            <AlertTriangle className="w-2.5 h-2.5" /> Divergent
                        </span>
                    )}
                </div>
            </div>

            {/* Expandable Section */}
            {isExpanded && (
                <div className="space-y-2.5 pt-1 text-slate-300">
                    {/* Active Position Management Card */}
                    {isPositionMgmt && activePos && (
                        <div className="p-2 rounded-lg border border-amber-500/25 bg-amber-950/20 space-y-1.5 text-[10px] font-mono">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-1.5 font-bold">
                                    <span className={`px-1.5 py-0.5 rounded text-[8.5px] uppercase ${
                                        activePos.side === 'LONG'
                                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                            : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                    }`}>
                                        {activePos.side}
                                    </span>
                                    <span className="text-slate-200">
                                        Entry: {activePos.entryPrice ? activePos.entryPrice.toFixed(2) : '0.00'}
                                    </span>
                                </div>
                                <div className="flex items-center gap-1">
                                    <span className="text-slate-400 text-[9px]">uPnL:</span>
                                    <span className={`font-bold ${activePos.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {activePos.pnl >= 0 ? '+' : ''}{activePos.pnl?.toFixed(2)}
                                    </span>
                                </div>
                            </div>
                            <div className="flex items-center justify-between text-[9px] text-slate-400 pt-0.5 border-t border-white/5">
                                <span>SL: {activePos.stopLoss ? activePos.stopLoss.toFixed(2) : 'None'}</span>
                                {activePos.isRiskFree && (
                                    <span className="text-cyan-400 font-bold flex items-center gap-0.5">
                                        <Lock className="w-2.5 h-2.5" /> Risk-Free
                                    </span>
                                )}
                                <span>TP: {activePos.takeProfit ? activePos.takeProfit.toFixed(2) : 'Structure'}</span>
                            </div>
                        </div>
                    )}

                    {/* Softmax Probabilities Progress Bar */}
                    {isPositionMgmt ? (
                        <div className="space-y-1">
                            <div className="flex items-center justify-between text-[9px] font-mono font-bold uppercase text-slate-400">
                                <span>Management Decision Distribution</span>
                                <span>Direct Softmax Head</span>
                            </div>
                            <div className="w-full h-2.5 bg-slate-900 rounded-full overflow-hidden flex border border-white/10 p-0.5">
                                <div
                                    style={{ width: `${mgmtProbs.hold}%` }}
                                    className="h-full bg-emerald-500 rounded-l-full transition-all duration-300"
                                    title={`Hold: ${mgmtProbs.hold}%`}
                                />
                                <div
                                    style={{ width: `${mgmtProbs.tighten}%` }}
                                    className="h-full bg-cyan-400 transition-all duration-300"
                                    title={`Tighten SL: ${mgmtProbs.tighten}%`}
                                />
                                <div
                                    style={{ width: `${mgmtProbs.tp}%` }}
                                    className="h-full bg-amber-400 transition-all duration-300"
                                    title={`Take Profit: ${mgmtProbs.tp}%`}
                                />
                                <div
                                    style={{ width: `${mgmtProbs.exit}%` }}
                                    className="h-full bg-rose-500 rounded-r-full transition-all duration-300"
                                    title={`Exit: ${mgmtProbs.exit}%`}
                                />
                            </div>
                            <div className="flex justify-between text-[8.5px] font-mono font-medium pt-0.5">
                                <span className="text-emerald-400">HOLD: {mgmtProbs.hold}%</span>
                                <span className="text-cyan-400">TIGHTEN: {mgmtProbs.tighten}%</span>
                                <span className="text-amber-400">TP: {mgmtProbs.tp}%</span>
                                <span className="text-rose-400">EXIT: {mgmtProbs.exit}%</span>
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-1">
                            <div className="flex items-center justify-between text-[9px] font-mono font-bold uppercase text-slate-400">
                                <span>Scanning Action Distribution</span>
                                <span>Direct Softmax Head</span>
                            </div>
                            <div className="w-full h-2.5 bg-slate-900 rounded-full overflow-hidden flex border border-white/10 p-0.5">
                                <div
                                    style={{ width: `${scanningProbs.long}%` }}
                                    className="h-full bg-gradient-to-r from-emerald-600 to-emerald-400 rounded-l-full transition-all duration-300"
                                    title={`Long: ${scanningProbs.long}%`}
                                />
                                <div
                                    style={{ width: `${scanningProbs.flat}%` }}
                                    className="h-full bg-slate-600 transition-all duration-300"
                                    title={`Flat: ${scanningProbs.flat}%`}
                                />
                                <div
                                    style={{ width: `${scanningProbs.short}%` }}
                                    className="h-full bg-gradient-to-r from-rose-400 to-rose-600 rounded-r-full transition-all duration-300"
                                    title={`Short: ${scanningProbs.short}%`}
                                />
                            </div>
                            <div className="flex justify-between text-[9px] font-mono font-medium pt-0.5">
                                <span className="text-emerald-400 flex items-center gap-0.5">
                                    <TrendingUp className="w-2.5 h-2.5" /> P(LONG): {scanningProbs.long}%
                                </span>
                                <span className="text-slate-400 flex items-center gap-0.5">
                                    <Minus className="w-2.5 h-2.5" /> P(FLAT): {scanningProbs.flat}%
                                </span>
                                <span className="text-rose-400 flex items-center gap-0.5">
                                    <TrendingDown className="w-2.5 h-2.5" /> P(SHORT): {scanningProbs.short}%
                                </span>
                            </div>
                        </div>
                    )}

                    {/* Conviction Score Head (Continuous Expected Value) */}
                    <div className="p-2 rounded-lg border border-purple-500/20 bg-slate-900/60 space-y-1.5 text-[10px] font-mono">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5 text-purple-300 font-semibold">
                                <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                                <span>{isPositionMgmt ? 'Holding Conviction:' : 'Conviction Score:'}</span>
                            </div>
                            <div className="flex items-center gap-1">
                                <span className="text-purple-200 font-bold">
                                    {convictionScore.toFixed(2)} / {scoreMax.toFixed(1)}
                                </span>
                                <span className="text-slate-400 text-[9px]">
                                    ({scorePercent}%)
                                </span>
                            </div>
                        </div>
                        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                            <div
                                style={{ width: `${Math.min(100, Math.max(0, scorePercent))}%` }}
                                className="h-full bg-gradient-to-r from-purple-500 via-indigo-400 to-cyan-400 transition-all duration-300"
                            />
                        </div>
                    </div>

                    {/* Proposition Verification (Safety Gate Head) */}
                    <div className="p-2 rounded-lg border border-cyan-500/20 bg-slate-900/60 flex items-center justify-between text-[10px] font-mono">
                        <div className="flex items-center gap-1.5">
                            <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
                            <span className="text-slate-300">Execution Safety Gate:</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                            <span className={tradePermittedP >= 0.5 ? 'text-emerald-400 font-bold' : 'text-amber-400 font-bold'}>
                                {(tradePermittedP * 100).toFixed(0)}%
                            </span>
                            <span className={`px-1.5 py-0.2 rounded text-[8px] font-bold uppercase ${
                                tradePermittedP >= 0.5 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-400'
                            }`}>
                                {tradePermittedP >= 0.5 ? 'Permitted' : 'Gated'}
                            </span>
                        </div>
                    </div>

                    {/* Domain Synthesis Thesis */}
                    {Boolean(data.thesis) && (
                        <div className="p-2 rounded-lg border border-cyan-500/15 bg-black/40 text-[9.5px] text-slate-300 leading-relaxed font-mono">
                            <span className="text-cyan-400 font-bold mr-1">Thesis:</span>
                            {data.thesis}
                        </div>
                    )}

                    {/* Architecture & Specs Footer */}
                    <div className="flex items-center justify-between pt-1 border-t border-white/5 text-[8px] font-mono text-slate-500">
                        <span className="flex items-center gap-1">
                            <Layers className="w-2.5 h-2.5 text-cyan-400" />
                            {model}
                        </span>
                        <span className="text-cyan-400/80 font-bold">
                            Dual-Role MLX · &lt;700MB Unified RAM
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
});

LayaDecisionCard.displayName = 'LayaDecisionCard';
export default LayaDecisionCard;
