import React from 'react';
import { Settings } from 'lucide-react';
import { VARSState } from '../../types';

interface MarketStateCardProps {
    marketState: string;
    isImbalanced: boolean;
    statusColor: string;
    statusBg: string;
    hasDisplacement?: boolean;
    legPoc?: number;
    legVah?: number;
    legVal?: number;
    vars?: VARSState;
}

/** 01. STATE — session & leg market regime badge. */
const MarketStateCard = React.memo<MarketStateCardProps>(({ marketState, isImbalanced, statusColor, statusBg, hasDisplacement, legPoc, legVah, legVal, vars }) => {
    const hasVarsSignal = vars?.bullishReclaim || vars?.bearishReclaim;
    const varsIsBuy = vars?.bullishReclaim;
    const varsSrc = vars?.signalSource || 'VA';

    return (
        <div className="flex flex-col gap-2 relative">
            <div className="flex justify-between items-center text-[9px] text-glassy-text-tertiary uppercase tracking-wider absolute -top-2 right-1 z-10 bg-glassy-bg-tertiary px-1">
                <Settings className="w-3 h-3 hover:text-glassy-text-secondary transition-colors cursor-pointer" />
            </div>
            <div className={`p-3 rounded-md bg-glassy-bg-elevated/50 border border-glassy-border-default relative overflow-hidden flex flex-col gap-2`}>
                <div className={`absolute top-0 left-0 w-0.5 h-full ${statusBg.replace('20', '50').replace('bg-', 'bg-')}`} />

                <div className="flex items-center justify-between ml-2">
                    <span className="text-[9px] text-glassy-text-tertiary uppercase tracking-wider font-bold">Session & Leg</span>
                    <div className="flex flex-wrap items-center gap-1.5 justify-end">
                        {hasVarsSignal && (
                            <div className={`px-2 py-0.5 rounded-sm text-[8px] font-bold tracking-wide flex items-center gap-1.5 ${varsIsBuy ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'}`}>
                                <span className="text-glassy-text-tertiary font-normal">VARS</span>
                                <div className={`w-1.5 h-1.5 rounded-full ${varsIsBuy ? 'bg-emerald-400' : 'bg-rose-400'} animate-pulse`} />
                                {varsSrc} {varsIsBuy ? 'RECLAIM BUY' : 'RECLAIM SELL'}
                            </div>
                        )}
                        {marketState === 'DEAD' ? (
                            <div className="px-2 py-0.5 rounded-sm text-[8px] font-bold tracking-wide flex items-center gap-1.5 bg-glassy-regime-dead/20 text-glassy-bear-primary border border-glassy-bear-primary/30">
                                <span className="text-glassy-text-tertiary font-normal">SESSION</span>
                                <div className="w-1.5 h-1.5 rounded-full bg-glassy-bear-primary animate-pulse" />
                                DEAD MARKET
                            </div>
                        ) : (
                            <div className={`px-2 py-0.5 rounded-sm text-[8px] font-bold tracking-wide flex items-center gap-1.5 ${statusBg} ${statusColor}`}>
                                <span className="text-glassy-text-tertiary font-normal">SESSION</span>
                                <div className={`w-1.5 h-1.5 rounded-full ${isImbalanced ? 'bg-glassy-warning' : marketState === 'PROBING' ? 'bg-glassy-neutral-cool' : 'bg-glassy-neutral-warm'}`} />
                                {marketState.toUpperCase()}
                            </div>
                        )}
                        <div title={hasDisplacement ? "DISPLACEMENT — Strong directional move from value, new auction beginning" : "BALANCED — Price rotating within accepted value"}
                             className={`px-2 py-0.5 rounded-sm text-[8px] font-bold tracking-wide flex items-center gap-1.5 cursor-help ${hasDisplacement ? 'bg-glassy-warning/20 text-glassy-warning border border-glassy-warning/30' : 'bg-glassy-neutral-warm/20 text-glassy-neutral-warm border border-glassy-neutral-warm/30'}`}>
                                <span className="text-glassy-text-tertiary font-normal">LEG</span>
                                <div className={`w-1.5 h-1.5 rounded-full ${hasDisplacement ? 'bg-glassy-warning' : 'bg-glassy-neutral-warm'}`} />
                                {hasDisplacement ? 'DISPLACEMENT' : 'BALANCED'}
                        </div>
                    </div>
                </div>

                {(legPoc ?? 0) > 0 && (
                    <div className="flex items-center justify-between text-[8px] font-mono text-glassy-text-tertiary border-t border-glassy-border-default/40 pt-1.5 ml-2">
                        <span className="text-glassy-text-secondary font-medium">Leg Profile</span>
                        <div className="flex items-center gap-2">
                            <span>POC <span className="text-glassy-text-primary font-semibold">{legPoc?.toFixed(1)}</span></span>
                            {(legVah ?? 0) > 0 && (
                                <span>VA <span className="text-glassy-text-primary font-semibold">{legVal?.toFixed(1)}–{legVah?.toFixed(1)}</span></span>
                            )}
                        </div>
                    </div>
                )}

            </div>
        </div>
    );
});

MarketStateCard.displayName = 'MarketStateCard';

export default MarketStateCard;
