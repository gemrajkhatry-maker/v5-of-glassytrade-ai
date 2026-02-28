import React from 'react';
import { RiskState } from '../../types';
import { AlertTriangle } from 'lucide-react';

interface RiskStateDisplayProps {
    riskState?: RiskState | null;
}

/** Displays trading halt warnings and consecutive loss counters. */
const RiskStateDisplay = React.memo<RiskStateDisplayProps>(({ riskState }) => {
    if (!riskState) return null;

    return (
        <>
            {riskState.halted && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
                    <div>
                        <div className="text-[10px] uppercase tracking-widest text-red-400 font-bold">Trading Halted</div>
                        <div className="text-[10px] text-red-300/70">{riskState.haltReason}</div>
                    </div>
                </div>
            )}
            {!riskState.halted && riskState.consecutiveLosses > 0 && (
                <div className="flex justify-between text-[10px] px-1">
                    <span className="text-white/40">Consecutive Losses: <span className="text-yellow-400 font-bold">{riskState.consecutiveLosses}</span></span>
                    <span className="text-white/40">Daily P&L: <span className={riskState.dailyPnl >= 0 ? 'text-green-400' : 'text-red-400'}>{'\u20B9'}{riskState.dailyPnl.toFixed(2)}</span></span>
                </div>
            )}
        </>
    );
});

RiskStateDisplay.displayName = 'RiskStateDisplay';

export default RiskStateDisplay;
