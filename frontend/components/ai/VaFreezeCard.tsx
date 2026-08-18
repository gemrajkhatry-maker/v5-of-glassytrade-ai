import React from 'react';
import { Lock, Unlock, Snowflake, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { AuctionAnalysis, VaSnapshot } from '../../types';
import { VA_FREEZE_CONFIG } from '../../config';

interface VaFreezeCardProps {
    auction: AuctionAnalysis | null;
}

function _expansionDir(snaps: VaSnapshot[]): 'LONG' | 'SHORT' | '' {
    if (snaps.length < VA_FREEZE_CONFIG.minSnapshots) return '';
    const prev = snaps[snaps.length - 2];
    const curr = snaps[snaps.length - 1];
    if (curr.vah > prev.vah) return 'LONG';
    if (curr.val < prev.val) return 'SHORT';
    return '';
}

function _shortTime(time: string): string {
    try {
        const t = time.includes('T') ? time.split('T')[1] : time;
        return t.slice(0, 5);
    } catch {
        return time;
    }
}

/** Fabio freeze discipline — IB lock + frozen VA snapshot checkpoints.
 *
 * The developing VA recalculates every bar and always looks "balanced"; the
 * edge gate compares FROZEN checkpoints to detect real expansion. This card
 * surfaces that state so the trader can see whether the engine is measuring
 * change (expansion) or standing down (stable range). */
const VaFreezeCard = React.memo<VaFreezeCardProps>(({ auction }) => {
    const ibFrozen = Boolean(auction?.ibFrozen);
    const vaReliable = Boolean(auction?.vaReliable);
    const snaps: VaSnapshot[] = (auction?.vaSnapshots ?? []) as VaSnapshot[];
    const ibHigh = auction?.location?.ibHigh ?? 0;
    const ibLow = auction?.location?.ibLow ?? 0;
    const dir = _expansionDir(snaps);

    if (snaps.length < VA_FREEZE_CONFIG.minSnapshots && !vaReliable) return null;

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>Fabio Freeze — IB / VA</span>
                <Snowflake className="w-3 h-3 hover:text-white/80 transition-colors" />
            </div>
            <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                {/* IB Freeze Status */}
                <div className="flex justify-between items-center">
                    <span className="text-[10px] text-white/40">IB Lock</span>
                    <div className="flex items-center gap-2">
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wider flex items-center gap-1 ${
                            ibFrozen
                                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                                : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
                        }`}>
                            {ibFrozen
                                ? <><Lock className="w-2.5 h-2.5" /> FROZEN</>
                                : <><Unlock className="w-2.5 h-2.5" /> BUILDING</>}
                        </span>
                        {ibHigh > 0 && ibLow > 0 && (
                            <span className="text-[10px] font-mono text-white/60">
                                {ibLow.toFixed(1)} – {ibHigh.toFixed(1)}
                            </span>
                        )}
                    </div>
                </div>

                {/* VA Reliability */}
                <div className="flex justify-between items-center">
                    <span className="text-[10px] text-white/40">VA Reliable</span>
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wider ${
                        vaReliable
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : 'bg-yellow-500/10 text-yellow-400'
                    }`}>
                        {vaReliable ? '≥ 30 min — TRUSTED' : 'Early session — prior-day anchor'}
                    </span>
                </div>

                {/* Expansion read between frozen checkpoints */}
                {snaps.length >= VA_FREEZE_CONFIG.minSnapshots && (
                    <div className="flex justify-between items-center pt-1 border-t border-white/5">
                        <span className="text-[10px] text-white/40">Expansion (chk→chk)</span>
                        {dir === 'LONG' && (
                            <span className="px-1.5 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-[9px] font-bold font-mono text-cyan-400 flex items-center gap-1">
                                <TrendingUp className="w-2.5 h-2.5" /> EXPANDING UP — imbalance forming
                            </span>
                        )}
                        {dir === 'SHORT' && (
                            <span className="px-1.5 py-0.5 rounded bg-orange-500/10 border border-orange-500/30 text-[9px] font-bold font-mono text-orange-400 flex items-center gap-1">
                                <TrendingDown className="w-2.5 h-2.5" /> EXPANDING DOWN — imbalance forming
                            </span>
                        )}
                        {dir === '' && (
                            <span className="px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-[9px] font-bold font-mono text-white/50 flex items-center gap-1">
                                <Minus className="w-2.5 h-2.5" /> RANGE HELD — balanced
                            </span>
                        )}
                    </div>
                )}

                {/* Frozen snapshot checkpoints */}
                {snaps.length > 0 && (
                    <div className="pt-1 border-t border-white/5 space-y-1">
                        <div className="text-[9px] text-white/40 font-bold tracking-wide">
                            FROZEN VA SNAPSHOTS ({snaps.length})
                        </div>
                        {snaps.slice(-4).map((s, i) => {
                            const isLatest = s === snaps[snaps.length - 1];
                            const arrow = isLatest && dir
                                ? (dir === 'LONG' ? '▲' : '▼')
                                : '';
                            return (
                                <div key={`${s.time}-${i}`} className={`flex justify-between items-center px-1.5 py-0.5 rounded ${isLatest ? 'bg-white/5 border border-white/10' : ''}`}>
                                    <span className="text-[9px] font-mono text-white/40">
                                        {_shortTime(s.time)}
                                        {arrow && <span className={`ml-1 ${dir === 'LONG' ? 'text-cyan-400' : 'text-orange-400'}`}>{arrow}</span>}
                                    </span>
                                    <span className="text-[9px] font-mono text-white/70">
                                        <span className="text-white/30">VAL</span> {s.val.toFixed(1)}
                                        <span className="mx-1 text-white/20">·</span>
                                        <span className="text-white/30">POC</span> {s.poc.toFixed(1)}
                                        <span className="mx-1 text-white/20">·</span>
                                        <span className="text-white/30">VAH</span> {s.vah.toFixed(1)}
                                    </span>
                                </div>
                            );
                        })}
                        {(() => {
                            const prev = snaps[snaps.length - 2];
                            const curr = snaps[snaps.length - 1];
                            if (!prev) return null;
                            return (
                                <div className="text-[8px] font-mono text-white/30 px-1.5">
                                    Δ VAH {prev.vah.toFixed(1)} → {curr.vah.toFixed(1)} ({((curr.vah - prev.vah) >= 0 ? '+' : '')}{(curr.vah - prev.vah).toFixed(1)})
                                    {'  |  '}
                                    Δ VAL {prev.val.toFixed(1)} → {curr.val.toFixed(1)} ({((curr.val - prev.val) >= 0 ? '+' : '')}{(curr.val - prev.val).toFixed(1)})
                                </div>
                            );
                        })()}
                    </div>
                )}
            </div>
        </div>
    );
});

VaFreezeCard.displayName = 'VaFreezeCard';

export default VaFreezeCard;
