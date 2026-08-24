import React from 'react';
import { AMTAnalysis, AgentDecision } from '../../types';

interface DiagnosticsPanelProps {
    amtResult: AMTAnalysis | null;
    currentLtp: number;
    agentDecision: AgentDecision | null;
}

/** DIAGNOSTICS TIER — collapsed market-structure / VWAP-event / rule-checklist details. */
const DiagnosticsPanel = React.memo<DiagnosticsPanelProps>(({ amtResult, currentLtp, agentDecision }) => {
    return (
        <details className="mt-2 group rounded-md bg-white/5 border border-white/5 cursor-pointer">
            <summary className="list-none flex justify-between items-center px-3 py-2 text-[10px] text-white/40 uppercase tracking-widest font-bold">
                <span>Diagnostics</span>
                <span className="group-open:hidden">Expand</span>
                <span className="hidden group-open:block">Collapse</span>
            </summary>
            <div className="px-3 pb-3 pt-1 flex flex-col gap-2">
                {/* Market Structure */}
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

                {/* POC Signal / POC vs Price / Prior POC-VA */}
                {(amtResult?.pocSignal || amtResult?.pocVsPrice || (amtResult?.priorPoc ?? 0) > 0) && (
                    <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-1.5">
                        {amtResult?.pocSignal && (
                            <div className="flex justify-between items-center">
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
                        {(amtResult?.priorPoc ?? 0) > 0 && (
                            <>
                                <div className="flex justify-between items-center pt-1.5 border-t border-white/5">
                                    <span className="text-white/40">Prior POC</span>
                                    <span className="font-mono text-yellow-400/70">{amtResult?.priorPoc?.toFixed(2)}</span>
                                </div>
                                <div className="flex justify-between items-center">
                                    <span className="text-white/30">Prior VA</span>
                                    <span className="font-mono text-white/30">
                                        {amtResult?.priorVal?.toFixed(2)} — {amtResult?.priorVah?.toFixed(2)}
                                    </span>
                                </div>
                            </>
                        )}
                    </div>
                )}

                {/* VWAP Events & AVWAP Detection */}
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

                {/* 05. RULE CHECKLIST */}
                <div className="flex flex-col gap-2 mt-2">
                    {(() => {
                        let passedCount = 0;
                        const distThreshold = 0.25;
                        if (amtResult?.marketState !== 'DEAD') passedCount++;
                        if (currentLtp && amtResult?.valueAreaLow && Math.abs(currentLtp - (currentLtp > amtResult.sessionVwap! ? amtResult.valueAreaHigh! : amtResult.valueAreaLow!)) < distThreshold) passedCount++;
                        if (agentDecision?.timing === 'ENTER_NOW') passedCount++;
                        const totalRules = 3;
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
                                            const timingColor = timing === 'ENTER_NOW' ? 'text-emerald-400' :
                                                                timing === 'WAIT' ? 'text-yellow-400' : 'text-white/40';
                                            return <span className={`font-mono text-[9px] font-bold ${timingColor}`}>{timing}</span>;
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
            </div>
        </details>
    );
});

DiagnosticsPanel.displayName = 'DiagnosticsPanel';

export default DiagnosticsPanel;
