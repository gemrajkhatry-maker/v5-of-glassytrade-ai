import React, { useState, useEffect, useRef, useCallback } from 'react';
import GlassPanel from './GlassPanel';
import { RLTrainingStatus } from '../types_rl';
import { Brain, Play, Square, Zap, TrendingUp, Hash, Clock, BarChart2 } from 'lucide-react';

interface RLTrainingPanelProps {
    /** Live RL status from the gameloop state snapshot */
    liveStatus?: RLTrainingStatus | null;
}

const POLL_INTERVAL = 2000;
const API_BASE = '/api/rl';

const STATUS_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
    idle: { bg: 'bg-white/5', text: 'text-white/50', dot: 'bg-zinc-400' },
    training: { bg: 'bg-blue-500/10', text: 'text-blue-300', dot: 'bg-blue-400 animate-pulse' },
    done: { bg: 'bg-emerald-500/10', text: 'text-emerald-300', dot: 'bg-emerald-400' },
    error: { bg: 'bg-red-500/10', text: 'text-red-300', dot: 'bg-red-400' },
};

function formatTime(seconds: number): string {
    if (seconds < 60) return `${seconds.toFixed(0)}s`;
    if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
    return `${(seconds / 3600).toFixed(1)}h`;
}

const RLTrainingPanel: React.FC<RLTrainingPanelProps> = ({ liveStatus }) => {
    const [status, setStatus] = useState<RLTrainingStatus>({
        state: 'idle', modelLoaded: false, timestepsDone: 0, totalTimesteps: 0,
        episodeCount: 0, meanReward: 0, meanSharpe: 0, totalTrades: 0, elapsedSeconds: 0,
    });
    const [isStarting, setIsStarting] = useState(false);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Use live status from gameloop if available, else poll
    useEffect(() => {
        if (liveStatus) setStatus(liveStatus);
    }, [liveStatus]);

    // Poll during training
    const pollStatus = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/status`);
            if (res.ok) {
                const data = await res.json();
                setStatus(data);
                if (data.state !== 'training') {
                    if (pollRef.current) clearInterval(pollRef.current);
                    pollRef.current = null;
                }
            }
        } catch { /* ignore */ }
    }, []);

    useEffect(() => {
        if (status.state === 'training' && !pollRef.current) {
            pollRef.current = setInterval(pollStatus, POLL_INTERVAL);
        }
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, [status.state, pollStatus]);

    const handleStartTraining = async () => {
        setIsStarting(true);
        try {
            const res = await fetch(`${API_BASE}/train`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    total_timesteps: 100000,
                    data_source: 'synthetic',
                    verbose: 0,
                }),
            });
            if (res.ok) {
                const data = await res.json();
                setStatus(data);
                pollRef.current = setInterval(pollStatus, POLL_INTERVAL);
            }
        } catch { /* ignore */ }
        setIsStarting(false);
    };

    const stateStyle = STATUS_COLORS[status.state] || STATUS_COLORS.idle;
    const progress = status.totalTimesteps > 0
        ? Math.min(100, (status.timestepsDone / status.totalTimesteps) * 100)
        : 0;

    return (
        <GlassPanel>
            <div className="p-4 space-y-4">
                {/* Header */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Zap size={16} className="text-amber-400" />
                        <span className="text-xs font-bold tracking-widest uppercase text-white/80">
                            RL Agent
                        </span>
                    </div>
                    <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${stateStyle.bg} ${stateStyle.text}`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${stateStyle.dot}`} />
                        {status.state}
                    </div>
                </div>

                {/* Progress Bar (visible during training or after completion) */}
                {(status.state === 'training' || status.state === 'done') && (
                    <div className="space-y-1">
                        <div className="flex justify-between text-[10px] text-white/40">
                            <span>{status.timestepsDone.toLocaleString()} steps</span>
                            <span>{status.totalTimesteps.toLocaleString()} total</span>
                        </div>
                        <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                            <div
                                className="h-full rounded-full transition-all duration-500 bg-gradient-to-r from-blue-500 to-purple-500"
                                style={{ width: `${progress}%` }}
                            />
                        </div>
                    </div>
                )}

                {/* Metric Grid */}
                <div className="grid grid-cols-2 gap-2">
                    <MetricCard
                        icon={<TrendingUp size={12} />}
                        label="Mean Reward"
                        value={status.meanReward.toFixed(2)}
                        accent={status.meanReward > 0 ? 'text-emerald-400' : status.meanReward < 0 ? 'text-red-400' : 'text-white/60'}
                    />
                    <MetricCard
                        icon={<BarChart2 size={12} />}
                        label="Sharpe"
                        value={status.meanSharpe.toFixed(3)}
                        accent={status.meanSharpe > 1 ? 'text-emerald-400' : 'text-white/60'}
                    />
                    <MetricCard
                        icon={<Hash size={12} />}
                        label="Episodes"
                        value={status.episodeCount.toLocaleString()}
                    />
                    <MetricCard
                        icon={<Clock size={12} />}
                        label="Elapsed"
                        value={formatTime(status.elapsedSeconds)}
                    />
                </div>

                {/* Model Status */}
                <div className="flex items-center gap-2 text-[10px]">
                    <Brain size={12} className={status.modelLoaded ? 'text-purple-400' : 'text-white/20'} />
                    <span className={status.modelLoaded ? 'text-purple-300' : 'text-white/30'}>
                        {status.modelLoaded ? 'Model loaded — RL signals active' : 'No model loaded'}
                    </span>
                </div>

                {/* Train / Stop button */}
                {status.state !== 'training' && (
                    <button
                        onClick={handleStartTraining}
                        disabled={isStarting}
                        className="w-full flex items-center justify-center gap-2 py-2 rounded-xl text-xs font-semibold
              bg-gradient-to-r from-blue-600/20 to-purple-600/20 border border-white/10
              hover:from-blue-600/30 hover:to-purple-600/30 hover:border-white/20
              text-white/80 hover:text-white transition-all duration-200
              disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                        <Play size={14} />
                        {isStarting ? 'Starting…' : 'Start Training'}
                    </button>
                )}

                {status.state === 'training' && (
                    <div className="flex items-center justify-center gap-2 py-2 text-xs text-blue-300/60">
                        <div className="w-3 h-3 border-2 border-blue-400/40 border-t-blue-400 rounded-full animate-spin" />
                        Training in progress…
                    </div>
                )}
            </div>
        </GlassPanel>
    );
};

/* Small metric card subcomponent */
function MetricCard({
    icon, label, value, accent = 'text-white/60',
}: { icon: React.ReactNode; label: string; value: string; accent?: string; }) {
    return (
        <div className="bg-white/[0.03] rounded-xl p-2.5 space-y-1">
            <div className="flex items-center gap-1 text-[10px] text-white/30">
                {icon}
                {label}
            </div>
            <div className={`text-sm font-semibold ${accent}`}>{value}</div>
        </div>
    );
}

export default RLTrainingPanel;
