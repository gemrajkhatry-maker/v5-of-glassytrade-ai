
import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
    InstrumentState,
    ChartConfig,
    OHLCData,
    FootprintCandle,
    OrderBook,
    ModelWeights,
    LLMHistoryEntry,
} from '../types';

const DEFAULT_WEIGHTS: ModelWeights = {
    trend: 0.40,
    momentum: 0.25,
    delta: 0.15,
    orderBook: 0.15,
    volatility: 0.05,
};

/**
 * Creates a fresh instrument state.
 * Used on initialisation before the backend has responded.
 */
const createInstrumentState = (symbol: string): InstrumentState => ({
    symbol,
    data: [],
    orderBook: null,
    portfolio: {
        balance: 10_000_000,
        equity: 10_000_000,
        leverage: 10,
        positions: [],
        closedTrades: [],
        history: [],
    },
    modelWeights: DEFAULT_WEIGHTS,
    generation: 0,
    aiAnalysis: null,
    genAIAnalysis: null,
    amtAnalysis: null,
    riskState: null,
    agentDecision: null,
    llmHistory: [],
    predictions: [],
    overseerAction: '',
    overseerReason: '',
    stats: null,
    depth20Active: false,
    lastUpdate: Date.now(),
});

/**
 * Server-driven trading system hook.
 *
 * Backend streams ticks from Dhan, processes them, and pushes state.
 * Frontend is a pure renderer — no market data fetching, no business logic.
 */
export const useServerTradingSystem = (config: ChartConfig) => {
    const [instruments, setInstruments] = useState<Record<string, InstrumentState>>({});
    const [activeSymbol, setActiveSymbol] = useState<string>('');
    const [connected, setConnected] = useState(false);
    const [connectionStatus, setConnectionStatus] = useState<string>('');
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const latestFootprint = useRef<Record<string, FootprintCandle> | null>(null);

    // ----------------------------------------------------------------
    // 0.  Fetch backend config on mount
    // ----------------------------------------------------------------
    useEffect(() => {
        fetch('/api/system/config')
            .then(res => res.json())
            .then(cfg => {
                console.log('[TradingSystem] Backend config:', cfg);
                if (cfg.defaultSymbol) {
                    const sym = cfg.defaultSymbol;
                    setInstruments(prev => ({
                        ...prev,
                        [sym]: createInstrumentState(sym),
                    }));
                    setActiveSymbol(sym);
                }
            })
            .catch(() => {
                console.warn('[TradingSystem] Backend not available');
            });
    }, []);

    // ----------------------------------------------------------------
    // 1.  Load persisted LLM decision history on mount
    // ----------------------------------------------------------------
    useEffect(() => {
        fetch('/api/ai/history')
            .then(res => res.json())
            .then(data => {
                if (!data.decisions || data.decisions.length === 0) return;
                const entries: LLMHistoryEntry[] = data.decisions.map((d: any) => ({
                    timestamp: new Date(d.created_at + 'Z').getTime(),
                    direction: d.direction || 'FLAT',
                    confidence: d.confidence || 'Medium',
                    rationale: d.rationale || '',
                    inputPrompt: d.input_prompt || '',
                    rawOutput: d.raw_output || '',
                }));
                setInstruments(prev => {
                    const next = { ...prev };
                    for (const sym of Object.keys(next)) {
                        next[sym] = { ...next[sym], llmHistory: entries.slice(-20) };
                    }
                    return next;
                });
            })
            .catch(() => {}); // Silently fail if backend not ready
    }, []);

    // ----------------------------------------------------------------
    // 2.  WebSocket message handler
    // ----------------------------------------------------------------
    const handleWsMessage = useCallback((event: MessageEvent) => {
        try {
            const state = JSON.parse(event.data);

            // Handle backend error messages
            if (state.error) {
                console.error('[TradingSystem] Backend error:', state.error);
                setConnectionStatus(state.error);
                return;
            }

            // Server mode init
            if (state.status === 'server_mode') {
                console.log(`[TradingSystem] Server mode: symbol=${state.symbol}`);
                const sym = state.symbol;
                setInstruments(prev => ({
                    ...prev,
                    [sym]: prev[sym] || createInstrumentState(sym),
                }));
                setActiveSymbol(sym);
                return;
            }

            // History loaded from server
            if (state.status === 'history_loaded') {
                if (state.history && state.symbol) {
                    const sym = state.symbol;
                    setInstruments(prev => {
                        const inst = prev[sym] || createInstrumentState(sym);
                        return {
                            ...prev,
                            [sym]: { ...inst, data: state.history },
                        };
                    });
                }
                console.log(`[TradingSystem] History loaded: ${state.count} candles`);
                return;
            }

            // Full state snapshot from backend
            const symbol: string = state._symbol;
            if (!symbol) return;

            setInstruments(prev => {
                const inst = prev[symbol] || createInstrumentState(symbol);

                // Update chart data from tick if present
                let newData = inst.data;
                if (state.tick) {
                    newData = [...inst.data];
                    const last = newData[newData.length - 1];
                    if (last && state.tick.time === last.time) {
                        newData[newData.length - 1] = state.tick;
                    } else {
                        newData.push(state.tick);
                        if (newData.length > 1000) newData.shift();
                    }
                }

                const newPortfolio = state.portfolio ?? inst.portfolio;
                const newAmtAnalysis = state.amt ?? inst.amtAnalysis;
                const newGenAIAnalysis = state.genAIAnalysis ?? inst.genAIAnalysis;
                const newPredictions = state.prediction?.predictions ?? inst.predictions;
                const newModelWeights = state.modelWeights ?? inst.modelWeights;
                const newGeneration = state.generation ?? inst.generation;
                const newRiskState = state.riskState ?? inst.riskState;
                const newAgentDecision = state.agentDecision ?? inst.agentDecision;
                const newOverseerAction = state.overseerAction ?? inst.overseerAction;
                const newOverseerReason = state.overseerReason ?? inst.overseerReason;
                const newStats = state.stats ?? inst.stats;

                return {
                    ...prev,
                    [symbol]: {
                        ...inst,
                        data: newData,
                        portfolio: newPortfolio,
                        amtAnalysis: newAmtAnalysis,
                        aiAnalysis: state.prediction?.analysis ?? inst.aiAnalysis,
                        genAIAnalysis: newGenAIAnalysis,
                        llmHistory: (() => {
                            const newAi = state.genAIAnalysis;
                            if (!newAi || !newAi.inputPrompt) return inst.llmHistory;
                            const lastEntry = inst.llmHistory[inst.llmHistory.length - 1];
                            if (lastEntry && lastEntry.inputPrompt === newAi.inputPrompt) return inst.llmHistory;
                            const entry: LLMHistoryEntry = {
                                timestamp: Date.now(),
                                direction: newAi.direction,
                                confidence: newAi.confidence,
                                rationale: newAi.rationale,
                                inputPrompt: newAi.inputPrompt,
                                rawOutput: newAi.rawOutput,
                            };
                            return [...inst.llmHistory, entry].slice(-20);
                        })(),
                        predictions: newPredictions,
                        modelWeights: newModelWeights,
                        generation: newGeneration,
                        riskState: newRiskState,
                        agentDecision: newAgentDecision,
                        overseerAction: newOverseerAction,
                        overseerReason: newOverseerReason,
                        orderBook: state.depth ?? inst.orderBook,
                        depth20Active: state.depth20Active ?? inst.depth20Active,
                        stats: newStats,
                        lastUpdate: Date.now(),
                    },
                };
            });

            if (state.footprint) {
                latestFootprint.current = state.footprint;
            }
        } catch (e) {
            console.error('[TradingSystem] WS parse error', e);
        }
    }, []);

    // ----------------------------------------------------------------
    // 3.  WebSocket connection
    // ----------------------------------------------------------------
    const [retryCount, setRetryCount] = useState(0);

    const connect = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) return;

        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${protocol}://${window.location.host}/api/trading/ws/gameloop`);

        ws.onopen = () => {
            console.log('[TradingSystem] WS connected');
            setRetryCount(0);
            setConnected(true);
            setConnectionStatus('');

            // Subscribe to server-driven stream
            if (activeSymbol) {
                ws.send(JSON.stringify({ subscribe: activeSymbol }));
                console.log(`[TradingSystem] Subscribed to ${activeSymbol}`);
            }
        };

        ws.onmessage = handleWsMessage;

        ws.onclose = (e) => {
            setConnected(false);
            if (e.code !== 1000 && wsRef.current) {
                const delay = Math.min(500 * Math.pow(2, retryCount), 5000);
                setConnectionStatus(`Disconnected — reconnecting in ${Math.round(delay / 1000)}s...`);
                console.warn(`[TradingSystem] WS disconnected, reconnecting in ${delay}ms…`);
                reconnectTimer.current = setTimeout(() => {
                    setRetryCount(c => c + 1);
                    connect();
                }, delay);
            }
        };

        ws.onerror = () => {};

        wsRef.current = ws;
    }, [activeSymbol, retryCount, handleWsMessage]);

    useEffect(() => {
        if (!activeSymbol) return; // Wait for config to load
        connect();
        return () => {
            if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
            if (wsRef.current) {
                const ws = wsRef.current;
                wsRef.current = null;
                ws.close(1000, "Component Unmounted");
            }
        };
    }, [activeSymbol]);

    // ----------------------------------------------------------------
    // 4.  Derived state
    // ----------------------------------------------------------------
    const activeInstrument = instruments[activeSymbol];

    const footprintData = useMemo<Record<string, FootprintCandle> | null>(() => {
        return latestFootprint.current;
    }, [activeInstrument?.lastUpdate]);

    const cumulativeDeltas = useMemo(() => {
        if (!activeInstrument) return [];
        let runningDelta = 0;
        return activeInstrument.data.map(d => {
            runningDelta += d.delta;
            return runningDelta;
        });
    }, [activeInstrument?.data?.length, activeInstrument?.data?.[activeInstrument?.data?.length - 1]?.delta]);

    return {
        instruments,
        activeSymbol,
        setActiveSymbol,
        activeInstrument,
        activeFootprint: {
            data: footprintData,
            cumulativeDeltas,
        },
        connected,
        connectionStatus,
    };
};
