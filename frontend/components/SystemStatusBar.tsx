import React, { useState, useEffect } from 'react';

export interface SystemStatus {
    feedConnected: boolean;
    llmReady: boolean;
    modelsLoaded: boolean;
    marketOpen: boolean;
    circuitBreakerTripped: boolean;
    haltReason: string;
    tradingMode: string;
}

interface Props {
    status: SystemStatus | null;
}

const Dot: React.FC<{ on: boolean; label: string }> = ({ on, label }) => (
    <div className="flex items-center gap-1 text-xs">
        <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ backgroundColor: on ? '#22c55e' : '#ef4444' }}
        />
        <span className="text-gray-300">{label}</span>
    </div>
);

const usePhaseTimer = () => {
    const [timeData, setTimeData] = useState({
        phase: 'CLOSED',
        label: 'MARKET CLOSED',
        progress: 0,
        phaseColor: 'bg-slate-600',
        textColor: 'text-slate-400',
        timeStr: '',
        nextPhaseIn: ''
    });

    useEffect(() => {
        const interval = setInterval(() => {
            const now = new Date();
            let hours = now.getHours();
            let mins = now.getMinutes();
            let secs = now.getSeconds();
            
            const hhmm = hours + mins / 100;
            
            let phase = 'CLOSED';
            let label = 'MARKET CLOSED';
            let phaseColor = 'bg-slate-600';
            let textColor = 'text-slate-400';
            let nextPhaseIn = '';
            
            const getRemaining = (targetHour: number, targetMin: number) => {
                const target = new Date();
                target.setHours(targetHour, targetMin, 0, 0);
                const diff = (target.getTime() - now.getTime()) / 1000;
                if (diff <= 0) return '';
                const h = Math.floor(diff / 3600);
                const m = Math.floor((diff % 3600) / 60);
                const s = Math.floor(diff % 60);
                return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
            };
            
            if (hhmm >= 9.15 && hhmm < 9.30) { 
                phase = 'PHASE 1'; label = 'OPENING NOISE'; phaseColor = 'bg-gray-500'; textColor = 'text-gray-300';
                nextPhaseIn = `PHASE 2 IN: ${getRemaining(9, 30)}`;
            }
            else if (hhmm >= 9.30 && hhmm < 11.30) { 
                phase = 'PHASE 2'; label = 'AAA WINDOW'; phaseColor = 'bg-green-500'; textColor = 'text-green-400';
                nextPhaseIn = `PHASE 3 IN: ${getRemaining(11, 30)}`;
            }
            else if (hhmm >= 11.30 && hhmm < 14.00) { 
                phase = 'PHASE 3'; label = 'MIDDAY CONSOLIDATION'; phaseColor = 'bg-amber-500'; textColor = 'text-amber-400';
                nextPhaseIn = `PHASE 4 IN: ${getRemaining(14, 0)}`;
            }
            else if (hhmm >= 14.00 && hhmm < 15.15) { 
                phase = 'PHASE 4'; label = 'POWER HOUR'; phaseColor = 'bg-green-500'; textColor = 'text-green-400';
                nextPhaseIn = `PHASE 5 IN: ${getRemaining(15, 15)}`;
            }
            else if (hhmm >= 15.15 && hhmm < 15.30) { 
                phase = 'PHASE 5'; label = 'CLOSE PROTECTION'; phaseColor = 'bg-red-500'; textColor = 'text-red-400';
                nextPhaseIn = `CLOSE IN: ${getRemaining(15, 30)}`;
            }
            else if (hhmm < 9.15) { 
                phase = 'PRE-MARKET'; label = 'WAITING FOR OPEN'; phaseColor = 'bg-slate-500'; textColor = 'text-slate-300';
                nextPhaseIn = `OPEN IN: ${getRemaining(9, 15)}`;
            } else {
                nextPhaseIn = `NEXT OPEN: TOMORROW`;
            }

            const currentMins = (hours * 60 + mins) - (9 * 60 + 15);
            const progress = Math.max(0, Math.min(100, (currentMins / 375) * 100));
            const timeStr = `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;

            setTimeData({ phase, label, progress, phaseColor, textColor, timeStr, nextPhaseIn });
        }, 1000);
        return () => clearInterval(interval);
    }, []);
    return timeData;
};

const SystemStatusBar: React.FC<Props> = ({ status }) => {
    const timeData = usePhaseTimer();

    if (!status) return null;

    return (
        <div className="w-full bg-gray-900 border-b border-gray-700 px-4 py-1 flex items-center justify-between">
            <div className="flex items-center gap-4 flex-wrap">
                <Dot on={status.feedConnected} label="Feed" />
                <Dot on={status.llmReady} label="LLM" />
                <Dot on={status.modelsLoaded} label="Models" />
                <Dot on={status.marketOpen} label="Market" />

                <span
                    className="text-xs font-semibold px-2 py-0.5 rounded"
                    style={{
                        backgroundColor: status.tradingMode === 'LIVE' ? '#dc2626' : '#2563eb',
                        color: '#fff',
                    }}
                >
                    {status.tradingMode}
                </span>

                {status.circuitBreakerTripped && (
                    <span className="text-xs font-bold text-red-400 ml-2">
                        ⚠ CIRCUIT BREAKER: {status.haltReason}
                    </span>
                )}
            </div>
            
            <div className="flex items-center gap-4 font-mono text-[10px] bg-black/40 px-3 py-1 rounded border border-white/5">
                <div className={`font-bold ${timeData.textColor}`}>[ {timeData.phase} — {timeData.label} ]</div>
                <div className="text-white/40">[ {timeData.nextPhaseIn} ]</div>
                <div className="flex items-center gap-2">
                    <span className="text-white/30">09:15</span>
                    <div className="w-32 h-1.5 bg-white/10 rounded-full relative overflow-hidden flex">
                        <div className={`h-full ${timeData.phaseColor} transition-all duration-1000`} style={{ width: `${timeData.progress}%`, opacity: 0.8 }}></div>
                        <div className="absolute top-0 left-0 w-full h-full border-x border-white/20 px-[20%] border-dashed opacity-20"></div>
                    </div>
                    <span className="text-white/30">15:30</span>
                </div>
            </div>
        </div>
    );
};

export default SystemStatusBar;
