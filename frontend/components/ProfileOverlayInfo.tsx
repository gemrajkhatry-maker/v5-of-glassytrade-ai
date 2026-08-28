import React from 'react';
import { AMTAnalysis } from '../types';
import { buildProfileSummary, ProfileSummary } from '../utils/profileInfo';

interface ProfileOverlayInfoProps {
    amt: AMTAnalysis | null;
    mode: 'session' | 'leg' | 'combined' | 'off';
    symbol: string;
}

const MODE_CHIP: Record<ProfileSummary['mode'], { label: string; cls: string }> = {
    session: { label: 'SESSION', cls: 'border-blue-400/40 bg-blue-500/10 text-blue-300' },
    leg: { label: 'LEG', cls: 'border-orange-400/40 bg-orange-500/10 text-orange-300' },
    combined: { label: 'COMBINED', cls: 'border-purple-400/40 bg-purple-500/10 text-purple-300' },
};

const CONFLUENCE_CHIP: Record<string, { label: string; cls: string }> = {
    CONFLUENCE: { label: '✓ CONFLUENCE', cls: 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300' },
    DIVERGENCE: { label: '⚠ DIVERGENCE', cls: 'border-amber-400/40 bg-amber-500/10 text-amber-300' },
    NEUTRAL: { label: '· NEUTRAL', cls: 'border-white/10 bg-white/5 text-white/50' },
};

/**
 * Compact context strip under the profile overlay toggles: which profile is
 * active, its session hours, and the current POC/VA levels — all from the AMT
 * stream the backend already sends. No new state, no backend changes.
 */
export const ProfileOverlayInfo: React.FC<ProfileOverlayInfoProps> = React.memo(({ amt, mode, symbol }) => {
    const s = buildProfileSummary(amt, mode, symbol);
    if (!s) return null;

    const chip = MODE_CHIP[s.mode];
    const fmt = (v: number) => (v > 0 ? v.toFixed(2) : '—');

    return (
        <div className="flex flex-col gap-1 mt-1.5 px-1 text-[9px] font-mono">
            <div className="flex items-center gap-1.5 flex-wrap">
                <span className={`px-1.5 py-0.5 rounded-sm border text-[8px] font-bold tracking-widest ${chip.cls}`}>
                    {chip.label}
                </span>
                <span className="text-glassy-text-tertiary">Session: {s.hours}</span>
                {s.mode === 'leg' && (
                    <span className="text-orange-300/70">Displacement leg</span>
                )}
                {s.confluence && (
                    <span className={`px-1.5 py-0.5 rounded-sm border text-[8px] font-bold tracking-widest ${CONFLUENCE_CHIP[s.confluence].cls}`}>
                        {CONFLUENCE_CHIP[s.confluence].label}
                    </span>
                )}
            </div>
            <div className="text-glassy-text-tertiary">
                POC <span className="text-glassy-text-primary font-bold">{fmt(s.poc)}</span>
                <span className="mx-1 text-glassy-text-disabled">·</span>
                VA <span className="text-glassy-text-primary">{fmt(s.val)}–{fmt(s.vah)}</span>
                <span className="mx-1 text-glassy-text-disabled">·</span>
                <span className="text-glassy-text-disabled">Auto-reset daily</span>
            </div>
            {amt?.valueMigration?.hasMigration && <ValueMigrationLine vm={amt.valueMigration} />}
            {amt?.gex && (amt.gex.callWallStrike > 0 || amt.gex.zeroFlipLevel > 0) && (
                <div className="text-glassy-text-tertiary flex items-center gap-1.5 flex-wrap">
                    <span className={`px-1 py-0.5 rounded-sm text-[8px] font-bold ${
                        amt.gex.regime === 'POSITIVE_GAMMA' ? 'text-emerald-400 bg-emerald-500/10' :
                        amt.gex.regime === 'NEGATIVE_GAMMA' ? 'text-rose-400 bg-rose-500/10' : 'text-amber-400 bg-amber-500/10'
                    }`}>
                        {amt.gex.regime === 'POSITIVE_GAMMA' ? '+GEX' : amt.gex.regime === 'NEGATIVE_GAMMA' ? '-GEX' : '±GEX'} ({amt.gex.netGexCrores >= 0 ? `+₹${amt.gex.netGexCrores.toFixed(1)}Cr` : `-₹${Math.abs(amt.gex.netGexCrores).toFixed(1)}Cr`})
                    </span>
                    <span>Flip <strong className="text-amber-300">{amt.gex.zeroFlipLevel.toFixed(1)}</strong></span>
                    <span className="text-glassy-text-disabled">·</span>
                    <span>Call Wall <strong className="text-rose-300">{amt.gex.callWallStrike.toFixed(0)}</strong></span>
                    <span className="text-glassy-text-disabled">·</span>
                    <span>Put Wall <strong className="text-emerald-300">{amt.gex.putWallStrike.toFixed(0)}</strong></span>
                </div>
            )}
        </div>
    );
});

const DIR_STYLE: Record<string, { arrow: string; cls: string }> = {
    MIGRATING_UP: { arrow: '▲', cls: 'text-emerald-300' },
    MIGRATING_DOWN: { arrow: '▼', cls: 'text-red-400' },
    EXPANDING: { arrow: '⇔', cls: 'text-amber-300' },
    CONTRACTING: { arrow: '↔', cls: 'text-sky-300' },
    FLAT: { arrow: '·', cls: 'text-white/50' },
};

/** Session VA development — POC/VAH/VAL drift vs the previous 15-min window. */
const ValueMigrationLine: React.FC<{ vm: NonNullable<AMTAnalysis['valueMigration']> }> = ({ vm }) => {
    const st = DIR_STYLE[vm.direction] ?? DIR_STYLE.FLAT;
    const sgn = (v: number) => (v > 0 ? '+' : '') + v.toFixed(2);
    return (
        <div className="text-glassy-text-tertiary">
            <span className={`font-bold ${st.cls}`}>MIGRATION {st.arrow} {vm.direction}</span>
            <span className="mx-1 text-glassy-text-disabled">·</span>
            POC <span className={st.cls}>{sgn(vm.pocDrift)}</span>
            <span className="mx-1 text-glassy-text-disabled">·</span>
            VAH <span className={st.cls}>{sgn(vm.vahDrift)}</span>
            <span className="mx-1 text-glassy-text-disabled">·</span>
            VAL <span className={st.cls}>{sgn(vm.valDrift)}</span>
            <span className="mx-1 text-glassy-text-disabled">·</span>
            <span className="text-glassy-text-disabled">{vm.windowLabel}</span>
        </div>
    );
};

ProfileOverlayInfo.displayName = 'ProfileOverlayInfo';

export default ProfileOverlayInfo;
