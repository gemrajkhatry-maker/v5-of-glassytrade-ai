import React from 'react';
import { ArrowUpDown } from 'lucide-react';
import { AMTAnalysis } from '../../types';

interface LvnPlayCardProps {
    lvnPlay: NonNullable<AMTAnalysis['lvnPlay']> | null | undefined;
}

/** 03e. LVN VELOCITY PLAY — low-volume node reversal signal. */
const LvnPlayCard = React.memo<LvnPlayCardProps>(({ lvnPlay }) => {
    if (!lvnPlay) return null;

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>03e. LVN Play</span>
                <ArrowUpDown className="w-3 h-3 text-amber-400" />
            </div>
            <div className="p-3 rounded-lg bg-amber-500/5 border border-amber-500/20 space-y-1.5">
                <div className="flex justify-between items-center">
                    <span className={`text-xs font-bold ${lvnPlay.direction === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>
                        {lvnPlay.direction} @ LVN {lvnPlay.lvn_price.toFixed(2)}
                    </span>
                    <span className="text-[9px] font-mono text-white/40">
                        Vol: {lvnPlay.velocity_ratio.toFixed(1)}x
                    </span>
                </div>
                <div className="flex justify-between text-[9px]">
                    <span className="text-white/40">Target: <span className="text-yellow-400 font-mono">{lvnPlay.target.toFixed(2)}</span></span>
                    <div className="flex gap-1.5">
                        {lvnPlay.has_rejection && <span className="text-orange-400">Rejection</span>}
                        {lvnPlay.has_delta_flip && <span className="text-purple-400">Delta Flip</span>}
                    </div>
                </div>
            </div>
        </div>
    );
});

LvnPlayCard.displayName = 'LvnPlayCard';

export default LvnPlayCard;
