import React from 'react';

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

const SystemStatusBar: React.FC<Props> = ({ status }) => {
    if (!status) return null;

    return (
        <div className="w-full bg-gray-900 border-b border-gray-700 px-4 py-1 flex items-center gap-4 flex-wrap">
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
    );
};

export default SystemStatusBar;
