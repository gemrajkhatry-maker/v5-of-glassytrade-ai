import React from 'react';
import { Zap, ShieldCheck, Clock, CheckCircle2, XCircle, Database, Activity } from 'lucide-react';
import { QuantDecisionAnalysis } from '../../types';

interface QuantDecisionCardProps {
    quantDecision: QuantDecisionAnalysis | null;
}

const formatReason = (reason?: string | null): string => {
    if (!reason) return 'Scanning for 3A setup';
    switch (reason) {
        case 'NO_EDGE':
            return 'Scanning for 3A Edge (Absorption / Aggression)';
        case 'POSITION_COOLDOWN':
            return 'Position Cooldown Active';
        case 'SESSION_WARMUP':
            return 'Session Warmup in Progress';
        case 'SESSION_CLOSED':
            return 'Market Session Closed';
        case 'RISK_LIMIT':
            return 'Daily Risk Limit Reached';
        case 'PORTFOLIO_EXPOSURE':
            return 'Max Portfolio Exposure Reached';
        case 'WAITING':
            return 'Waiting for 3A Trigger';
        default:
            return reason.replace(/_/g, ' ');
    }
};

/** PRIMARY decision card — renders the quant decision with clean metrics and gate grid. */
const QuantDecisionCard = React.memo<QuantDecisionCardProps>(({ quantDecision }) => {
    if (!quantDecision) return null;

    const isApproved = quantDecision.approved && !!quantDecision.signal;
    const isHalted = quantDecision.reason === 'HALTED';
    const humanReason = formatReason(quantDecision.reason);
    const gates = quantDecision.gateResults || [];
    const passedGatesCount = gates.filter(g => g.passed).length;
    const totalGatesCount = gates.length || 7;
    const overallProgressPct = gates.length > 0 ? Math.round((passedGatesCount / totalGatesCount) * 100) : 0;

    // Primary blocker string — first block reason or halt reason
    const blockReasons: string[] = (quantDecision as any).blockReasons || [];
    const primaryBlocker = isHalted
        ? `HALTED: ${blockReasons[0] || 'session risk limit reached'}`
        : !isApproved && blockReasons.length > 0
        ? blockReasons[0]
        : null;

    const modelLabel: string = (quantDecision as any).modelLabel
        || (quantDecision.signal as any)?.modelLabel
        || '';

    return (
        <div className={`p-3.5 rounded-xl border transition-all duration-200 ${
            isHalted
                ? 'border-rose-500/50 bg-rose-950/20 shadow-[0_0_16px_rgba(239,68,68,0.12)]'
                : isApproved 
                ? 'border-emerald-500/50 bg-emerald-950/20 shadow-[0_0_16px_rgba(16,185,129,0.15)]' 
                : 'border-white/8 bg-slate-900/60 backdrop-blur-md'
        }`}>

            {/* 0. Top blocker banner — overrides all visual "enter" language */}
            {primaryBlocker && (
                <div className={`mb-2.5 px-2.5 py-1.5 rounded-lg border flex items-start gap-2 ${
                    isHalted
                        ? 'border-rose-500/40 bg-rose-900/30 text-rose-300'
                        : 'border-amber-500/30 bg-amber-900/20 text-amber-300'
                }`}>
                    <span className={`mt-0.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                        isHalted ? 'bg-rose-400 animate-pulse' : 'bg-amber-400'
                    }`} />
                    <span className="text-[9px] font-mono font-bold uppercase leading-tight tracking-wide">
                        {primaryBlocker}
                    </span>
                </div>
            )}
            {/* 1. Header Bar */}
            <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-300 flex items-center gap-1.5">
                    <Zap className={`w-3.5 h-3.5 ${isApproved ? 'text-emerald-400 fill-emerald-400/20' : isHalted ? 'text-rose-400' : 'text-amber-400/80'}`} /> 
                    Quant Decision
                </span>
                <span className={`px-2 py-0.5 rounded text-[8px] font-bold tracking-wider uppercase border ${
                    isHalted
                        ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                        : isApproved 
                        ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-[0_0_8px_rgba(52,211,153,0.3)]' 
                        : 'bg-slate-800 text-slate-400 border-white/10'
                }`}>
                    {isHalted ? 'Halted' : isApproved ? 'Approved' : 'Standing By'}
                </span>
            </div>

            {/* 2. Main Signal or Standing-By Status */}
            {isApproved && quantDecision.signal ? (
                <div className="mt-2.5 pt-2 border-t border-emerald-500/20">
                    <div className="flex items-center justify-between">
                        <div className={`text-base font-extrabold tracking-wide ${
                            quantDecision.signal.type === 'LONG' ? 'text-emerald-400' : 'text-rose-400'
                        }`}>
                            {quantDecision.signal.type} @ {quantDecision.signal.entry.toFixed(2)}
                        </div>
                        <span className="px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-[10px] font-mono text-slate-300 font-bold">
                            RR {quantDecision.signal.rr.toFixed(1)}
                        </span>
                    </div>

                    {/* Metric Grid — SL / TP / Model */}
                    <div className="mt-2 bg-black/20 p-2.5 rounded-lg border border-white/5">
                        <div className="grid grid-cols-3 gap-2 text-[10px] font-mono">
                            <div>
                                <div className="text-[8px] uppercase tracking-wider text-slate-400">SL</div>
                                <div className="font-bold text-rose-400">{quantDecision.signal.sl.toFixed(2)}</div>
                            </div>
                            <div>
                                <div className="text-[8px] uppercase tracking-wider text-slate-400">TP</div>
                                <div className="font-bold text-emerald-400">{quantDecision.signal.tp.toFixed(2)}</div>
                            </div>
                            <div>
                                <div className="text-[8px] uppercase tracking-wider text-slate-400">Model</div>
                                <div className="font-bold text-slate-200 text-[8px] truncate" title={modelLabel}>
                                    {modelLabel || '—'}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            ) : (
                <div className="mt-2.5 pt-2 border-t border-white/5">
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-300 min-w-0">
                            <Clock className="w-3.5 h-3.5 text-amber-400/80 shrink-0" />
                            <span className="truncate">{humanReason}</span>
                        </div>
                        {quantDecision.reason && (
                            <span className="text-[8px] font-mono text-slate-500 uppercase px-1 py-0.5 rounded bg-white/5 shrink-0">
                                {quantDecision.reason}
                            </span>
                        )}
                    </div>
                </div>
            )}

            {/* 3. Phase Details */}
            {quantDecision.phase && (
                <div className="mt-2 text-[9px] font-mono text-slate-400 flex items-center gap-1.5">
                    <span className="text-slate-500 uppercase tracking-wider">Phase: {quantDecision.phase}</span>
                    {quantDecision.reason && isApproved && (
                        <span className="text-slate-400 font-sans">· {quantDecision.reason}</span>
                    )}
                </div>
            )}

            {/* 4. Triple-A Gates */}
            {gates.length > 0 && (
                <div className="mt-3 pt-2.5 border-t border-white/5 space-y-2">
                    {/* Overall Progress Header */}
                    <div className="space-y-1">
                        <div className="flex items-center justify-between text-[9px]">
                            <span className="font-bold uppercase tracking-widest text-slate-300 flex items-center gap-1">
                                <ShieldCheck className="w-3.5 h-3.5 text-slate-400" /> Triple-A Gates
                            </span>
                            <span className="font-mono font-bold text-slate-300">
                                {passedGatesCount}/{totalGatesCount} Passed ({overallProgressPct}%)
                            </span>
                        </div>
                        {/* Overall Progress Bar */}
                        <div className="w-full bg-slate-800/80 rounded-full h-2 overflow-hidden p-0.5 border border-white/5">
                            <div 
                                className={`h-full rounded-full transition-all duration-300 ${
                                    isApproved 
                                        ? 'bg-gradient-to-r from-emerald-500 to-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]' 
                                        : 'bg-gradient-to-r from-amber-500/70 to-emerald-500/70'
                                }`}
                                style={{ width: `${overallProgressPct}%` }}
                            />
                        </div>
                    </div>

                    {/* Vertical Gate Rows */}
                    <div className="space-y-1.5 pt-1">
                        {gates.map(g => (
                            <div 
                                key={g.gate}
                                title={`Gate ${g.gate}${g.name ? ` (${g.name})` : ''}: ${g.reason || (g.passed ? 'passed' : 'blocked')}`}
                                className={`p-1.5 rounded-lg border transition-colors ${
                                    g.passed 
                                        ? 'border-emerald-500/20 bg-emerald-950/15' 
                                        : 'border-white/5 bg-slate-800/30'
                                }`}
                            >
                                <div className="flex items-center justify-between text-[9px]">
                                    <div className="flex items-center gap-1.5 min-w-0">
                                        {g.passed ? (
                                            <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                                        ) : (
                                            <XCircle className="w-3 h-3 text-slate-500 shrink-0" />
                                        )}
                                        <span className={`font-mono font-semibold truncate ${g.passed ? 'text-slate-200' : 'text-slate-400'}`}>
                                            {g.name ?? `Gate ${g.gate}`}
                                        </span>
                                    </div>
                                    <span className={`px-1.5 py-0.2 rounded text-[8px] font-black font-mono leading-tight tracking-wider uppercase border ${
                                        g.passed 
                                            ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' 
                                            : 'bg-slate-800 text-slate-400 border-slate-700/50'
                                    }`}>
                                        {g.passed ? 'PASS' : 'BLOCK'}
                                    </span>
                                </div>

                                {/* Gate Mini Progress Bar & Reason */}
                                <div className="mt-1 flex items-center gap-2">
                                    <div className="flex-1 bg-slate-800/60 rounded-full h-1 overflow-hidden">
                                        <div 
                                            className={`h-full rounded-full ${g.passed ? 'bg-emerald-400 w-full' : 'bg-slate-600 w-1/5'}`}
                                        />
                                    </div>
                                    {g.reason && (
                                        <span className="text-[7.5px] font-mono text-slate-500 truncate max-w-[120px]">
                                            {g.reason}
                                        </span>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* 5. Model Context Transparency */}
            {(() => {
                const d = quantDecision as any;
                const ctxBars: number | undefined = d.contextBarsUsed ?? d.signal?.contextBarsUsed;
                const evtProc: number | undefined = d.eventsProcessed ?? d.signal?.eventsProcessed;
                const infWin: number | undefined = d.inferenceWindow ?? d.signal?.inferenceWindow ?? 32;
                if (ctxBars == null && evtProc == null) return null;
                const warmPct = ctxBars != null ? Math.min(100, Math.round((ctxBars / 512) * 100)) : 0;
                const isWarm = (ctxBars ?? 0) >= 32;
                return (
                    <div className="mt-3 pt-2.5 border-t border-white/5">
                        <div className="flex items-center gap-1 mb-1.5">
                            <Database className="w-3 h-3 text-slate-400" />
                            <span className="text-[9px] font-bold uppercase tracking-widest text-slate-400">Model Context</span>
                        </div>
                        <div className="grid grid-cols-3 gap-1.5 text-[9px] font-mono">
                            <div className={`p-1.5 rounded-lg border ${isWarm ? 'border-emerald-500/20 bg-emerald-950/10' : 'border-amber-500/20 bg-amber-950/10'}`}>
                                <div className="text-[7.5px] uppercase tracking-wider text-slate-500 mb-0.5">Hist Bars</div>
                                <div className={`font-bold text-[10px] ${isWarm ? 'text-emerald-400' : 'text-amber-400'}`}>
                                    {ctxBars != null ? ctxBars.toLocaleString() : '—'}
                                </div>
                                <div className="text-[7px] text-slate-600">of 512 buf</div>
                            </div>
                            <div className="p-1.5 rounded-lg border border-white/5 bg-slate-800/30">
                                <div className="text-[7.5px] uppercase tracking-wider text-slate-500 mb-0.5">Live Events</div>
                                <div className="font-bold text-[10px] text-sky-400">
                                    {evtProc != null ? evtProc.toLocaleString() : '—'}
                                </div>
                                <div className="text-[7px] text-slate-600">bars processed</div>
                            </div>
                            <div className="p-1.5 rounded-lg border border-white/5 bg-slate-800/30">
                                <div className="text-[7.5px] uppercase tracking-wider text-slate-500 mb-0.5">Infer Win</div>
                                <div className="font-bold text-[10px] text-violet-400">{infWin ?? 32}</div>
                                <div className="text-[7px] text-slate-600">steps fwd</div>
                            </div>
                        </div>
                        {/* Warmup progress bar */}
                        {ctxBars != null && (
                            <div className="mt-1.5">
                                <div className="flex justify-between text-[7.5px] font-mono mb-0.5">
                                    <span className="text-slate-500">Context warmup</span>
                                    <span className={isWarm ? 'text-emerald-400' : 'text-amber-400'}>{warmPct}%</span>
                                </div>
                                <div className="w-full bg-slate-800/80 rounded-full h-1 overflow-hidden">
                                    <div
                                        className={`h-full rounded-full transition-all duration-500 ${isWarm ? 'bg-gradient-to-r from-emerald-600 to-emerald-400' : 'bg-gradient-to-r from-amber-600 to-amber-400'}`}
                                        style={{ width: `${warmPct}%` }}
                                    />
                                </div>
                                {!isWarm && (
                                    <div className="mt-1 text-[7px] text-amber-400/80 font-mono">
                                        ⚠ Warming up — model using padded context ({ctxBars ?? 0}/32 bars)
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                );
            })()}
        </div>
    );
});

QuantDecisionCard.displayName = 'QuantDecisionCard';
export default QuantDecisionCard;
