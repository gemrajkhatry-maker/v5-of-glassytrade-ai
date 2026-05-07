import React from 'react';
import { Settings } from 'lucide-react';

interface StateTabProps {
  marketState: string;
  hasDisplacement: boolean;
  legPoc?: number;
  legVah?: number;
  legVal?: number;
  gapType?: string;
  openingBias?: string;
}

/**
 * StateTab displays market regime information including:
 * - Session market state (DEAD, IMBALANCED, TRENDING, BALANCED, PROBING)
 * - Leg state (DISPLACEMENT vs BALANCED)
 * - Session gap information
 * - Opening bias indicators
 */
const StateTab: React.FC<StateTabProps> = ({
  marketState,
  hasDisplacement,
  legPoc,
  legVah,
  legVal,
  gapType,
  openingBias,
}) => {
  const isImbalanced = marketState === 'IMBALANCED';
  const statusColor = isImbalanced ? "text-orange-400" : "text-blue-300";
  const statusBg = isImbalanced ? "bg-orange-500/20" : "bg-blue-500/20";

  return (
    <div className="flex flex-col gap-2 relative">
      <div className="flex justify-between items-center text-[9px] text-glassy-text-tertiary uppercase tracking-wider absolute -top-2 right-1 z-10 bg-glassy-bg-tertiary px-1">
        <Settings className="w-3 h-3 hover:text-glassy-text-secondary transition-colors cursor-pointer" />
      </div>
      <div className={`p-3 rounded-md bg-glassy-bg-elevated/50 border border-glassy-border-default relative overflow-hidden flex flex-col gap-2`}>
        <div className={`absolute top-0 left-0 w-0.5 h-full ${statusBg.replace('20', '50').replace('bg-', 'bg-')}`} />
        
        <div className="flex items-center justify-between ml-2">
          <span className="text-[9px] text-glassy-text-tertiary uppercase tracking-wider font-bold">Session & Leg</span>
          <div className="flex items-center gap-2">
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
              {(legPoc ?? 0) > 0 && (
                <span className="text-[7px] font-mono text-glassy-text-tertiary font-normal">
                  POC {legPoc?.toFixed(1)}
                  {(legVah ?? 0) > 0 && ` | ${legVal?.toFixed(1)}–${legVah?.toFixed(1)}`}
                </span>
              )}
            </div>
          </div>
        </div>
        
        {/* Session Gap Info */}
        {(() => {
          if (!gapType && !openingBias) return null;
          
          return (
            <div className="flex items-center gap-2 px-2 pt-1 border-t border-glassy-border-subtle">
              {gapType && (
                <div className={`px-1.5 py-0.5 rounded-sm text-[7px] font-bold tracking-wide ${
                  gapType.includes('UP') || gapType.includes('BULL') ? 'bg-glassy-bull-primary/15 text-glassy-bull-primary border border-glassy-bull-primary/30' :
                  gapType.includes('DOWN') || gapType.includes('BEAR') ? 'bg-glassy-bear-primary/15 text-glassy-bear-primary border border-glassy-bear-primary/30' :
                  'bg-glassy-bg-elevated text-glassy-text-tertiary border border-glassy-border-subtle'
                }`}>
                  GAP: {gapType}
                </div>
              )}
              {openingBias && (
                <div className={`px-1.5 py-0.5 rounded-sm text-[7px] font-bold tracking-wide ${
                  openingBias.includes('BULL') || openingBias.includes('UP') ? 'bg-glassy-bull-primary/15 text-glassy-bull-primary border border-glassy-bull-primary/30' :
                  openingBias.includes('BEAR') || openingBias.includes('DOWN') ? 'bg-glassy-bear-primary/15 text-glassy-bear-primary border border-glassy-bear-primary/30' :
                  'bg-glassy-bg-elevated text-glassy-text-tertiary border border-glassy-border-subtle'
                }`}>
                  OPEN: {openingBias}
                </div>
              )}
            </div>
          );
        })()}
      </div>
    </div>
  );
};

export default StateTab;
