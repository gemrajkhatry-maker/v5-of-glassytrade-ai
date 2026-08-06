import React from 'react';
import { Eye } from 'lucide-react';

interface OverseerCardProps {
    overseerAction?: string;
    overseerReason?: string;
    hasPositions: boolean;
}

/** 04b. OVERSEER — risk overseer action & reason. */
const OverseerCard = React.memo<OverseerCardProps>(({ overseerAction, overseerReason, hasPositions }) => {
    if (!overseerAction && !hasPositions) return null;

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between items-center text-[10px] text-white/40 uppercase tracking-widest">
                <span>04b. Overseer</span>
                <Eye className="w-3 h-3 hover:text-white/80 transition-colors" />
            </div>
            <div className="p-3 rounded-lg bg-white/5 border border-white/5 space-y-2">
                {overseerAction ? (
                    <>
                        <div className="flex justify-between items-center">
                            <span className="text-[10px] text-white/40">Action</span>
                            <span className={`text-xs font-bold uppercase ${overseerAction === 'HOLD' ? 'text-blue-300' :
                                overseerAction === 'TIGHTEN' ? 'text-yellow-400' :
                                    overseerAction === 'FULL_EXIT' ? 'text-red-400' :
                                        overseerAction === 'PARTIAL' ? 'text-orange-400' :
                                            overseerAction === 'ADD' ? 'text-green-400' :
                                                'text-white/60'
                                }`}>{overseerAction}</span>
                        </div>
                        {overseerReason && (
                            <div className="text-[9px] text-white/40 font-mono leading-relaxed">
                                {overseerReason}
                            </div>
                        )}
                    </>
                ) : (
                    <div className="text-[10px] text-white/30 text-center">No overseer decision yet</div>
                )}
            </div>
        </div>
    );
});

OverseerCard.displayName = 'OverseerCard';

export default OverseerCard;
