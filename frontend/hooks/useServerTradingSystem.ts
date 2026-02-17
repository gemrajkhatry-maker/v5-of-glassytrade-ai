
import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
    InstrumentState,
    ChartConfig,
    OHLCData,
    FootprintCandle,
    OrderBook,
    Portfolio,
    AMTAnalysis,
    AIAnalysis,
    ModelWeights,
    RiskState,
    LLMHistoryEntry,
    StrategyStats,
} from '../types';
import { normalizeSymbol } from '../services/binanceService';

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
const createInstrumentState = (
    symbol: string,
    initialData: OHLCData[] = [],
    orderBook: OrderBook | null = null,
): InstrumentState => ({
    symbol,
    data: initialData,
    orderBook,
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
    llmHistory: [],
    predictions: [],
    overseerAction: '',
    overseerReason: '',
    stats: null,
    lastUpdate: Date.now(),
});

/**
 * Server-side trading system hook.
 *
 * Opens a WebSocket to the backend game-loop and forwards every
 * incoming tick.  The server runs the full DDD pipeline and returns
 * a state snapshot that the frontend renders.
 */
export const useServerTradingSystem = (
    config: ChartConfig,
    marketData: {
        candidates: string[];
        initialHistory: Record<string, OHLCData[]>;
        tickStream: { symbol: string; tick: OHLCData } | null;
        orderBooks: Record<string, OrderBook>;
    },
) => {
    const [instruments, setInstruments] = useState<Record<string, InstrumentState>>({});
    const [activeSymbol, setActiveSymbol] = useState<string>('');
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const latestFootprint = useRef<Record<string, FootprintCandle> | null>(null);
    const historySentRef = useRef<Set<string>>(new Set());

    // ----------------------------------------------------------------
    // 1.  Initialise instrument slots when candidates arrive
    // ----------------------------------------------------------------
    useEffect(() => {
        if (marketData.candidates.length === 0 || Object.keys(instruments).length > 0) return;

        const init: Record<string, InstrumentState> = {};
        marketData.candidates.forEach(sym => {
            init[sym] = createInstrumentState(
                sym,
                marketData.initialHistory[sym] || [],
                marketData.orderBooks[sym] || null,
            );
        });

        setInstruments(init);
        if (!activeSymbol && marketData.candidates.length > 0) {
            setActiveSymbol(marketData.candidates[0]);
        }
    }, [marketData.candidates, marketData.initialHistory]);

    // ----------------------------------------------------------------
    // 1b. Load persisted LLM decision history on mount
    // ----------------------------------------------------------------
    useEffect(() => {
        fetch(`${window.location.protocol}//${window.location.host}/api/ai/history`)
            .then(res => res.json())
            .then(data => {
                if (!data.decisions || data.decisions.length === 0) return;
                const entries: LLMHistoryEntry[] = data.decisions.map((d: any) => ({
                    timestamp: new Date(d.created_at).getTime(),
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
    // 2.  Keep orderbooks in sync
    // ----------------------------------------------------------------
    useEffect(() => {
        setInstruments(prev => {
            const next = { ...prev };
            let changed = false;
            Object.entries(marketData.orderBooks).forEach(([sym, book]) => {
                if (next[sym] && next[sym].orderBook !== book) {
                    next[sym] = { ...next[sym], orderBook: book };
                    changed = true;
                }
            });
            return changed ? next : prev;
        });
    }, [marketData.orderBooks]);

    // ----------------------------------------------------------------
    // 3.  WebSocket connection to backend game-loop
    // ----------------------------------------------------------------
    const [retryCount, setRetryCount] = useState(0);

    // ----------------------------------------------------------------
    // 3.  WebSocket connection to backend game-loop
    // ----------------------------------------------------------------
    const connect = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) return;

        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${protocol}://${window.location.host}/api/trading/ws/gameloop`);

        ws.onopen = () => {
            console.log('[ServerTradingSystem] WS connected');
            setRetryCount(0); // Reset backoff on success
            historySentRef.current.clear(); // Re-send history on reconnect
        };

        ws.onmessage = (event) => {
            try {
                const state = JSON.parse(event.data);
                const symbol: string = state._symbol;
                if (!symbol) return;

                setInstruments(prev => {
                    const inst = prev[symbol];
                    if (!inst) return prev;

                    // Resolve new values, falling back to existing if not provided
                    const newPortfolio = state.portfolio ?? inst.portfolio;
                    const newAmtAnalysis = state.amt ?? inst.amtAnalysis;
                    const newAiAnalysis = state.prediction?.analysis ?? inst.aiAnalysis;
                    const newGenAIAnalysis = state.genAIAnalysis ?? inst.genAIAnalysis;
                    const newPredictions = state.prediction?.predictions ?? inst.predictions;
                    const newModelWeights = state.modelWeights ?? inst.modelWeights;
                    const newGeneration = state.generation ?? inst.generation;
                    const newRiskState = state.riskState ?? inst.riskState;
                    const newOverseerAction = state.overseerAction ?? inst.overseerAction;
                    const newOverseerReason = state.overseerReason ?? inst.overseerReason;
                    const newStats = state.stats ?? inst.stats;

                    return {
                        ...prev,
                        [symbol]: {
                            ...inst,
                            portfolio: newPortfolio,
                            amtAnalysis: newAmtAnalysis,
                            aiAnalysis: newAiAnalysis,
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
                            overseerAction: newOverseerAction,
                            overseerReason: newOverseerReason,
                            stats: newStats,
                            lastUpdate: Date.now(),
                        },
                    };
                });

                if (state.footprint) {
                    latestFootprint.current = state.footprint;
                }
            } catch (e) {
                console.error('[ServerTradingSystem] WS parse error', e);
            }
        };

        ws.onclose = (e) => {
            // Only reconnect if not 1000 (Normal Closure) and ref still exists
            if (e.code !== 1000 && wsRef.current) {
                const delay = Math.min(500 * Math.pow(2, retryCount), 5000);
                console.warn(`[ServerTradingSystem] WS disconnected, reconnecting in ${delay}ms…`);
                reconnectTimer.current = setTimeout(() => {
                    setRetryCount(c => c + 1);
                    connect();
                }, delay);
            }
        };

        ws.onerror = (e) => {
            // Quietly handle errors, let onclose handle reconnect
            // console.debug('[ServerTradingSystem] WS error', e);
        };

        wsRef.current = ws;
    }, [activeSymbol, retryCount]);

    useEffect(() => {
        connect();
        return () => {
            if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
            // Mark as intentionally closed to prevent reconnect loop
            if (wsRef.current) {
                const ws = wsRef.current;
                wsRef.current = null; // Detach ref first
                ws.close(1000, "Component Unmounted");
            }
        };
    }, []); // Only run once on mount (depend on internal recursion for retries)

    // ----------------------------------------------------------------
    // 4.  Forward ticks to the backend
    // ----------------------------------------------------------------
    useEffect(() => {
        if (!marketData.tickStream) return;
        const { symbol, tick } = marketData.tickStream;
        const ws = wsRef.current;

        // Update local data buffer (for chart rendering while backend responds)
        setInstruments(prev => {
            const inst = prev[symbol];
            if (!inst) return prev;

            let newData = [...inst.data];
            const last = newData[newData.length - 1];
            if (last && new Date(tick.time).getTime() === new Date(last.time).getTime()) {
                newData[newData.length - 1] = tick;
            } else {
                newData.push(tick);
                if (newData.length > 1000) newData.shift();
            }

            return { ...prev, [symbol]: { ...inst, data: newData } };
        });

        // Send to backend
        if (ws && ws.readyState === WebSocket.OPEN) {
            // Send historical candles once per symbol to seed backend VP
            if (!historySentRef.current.has(symbol) && marketData.initialHistory[symbol]?.length > 0) {
                const history = marketData.initialHistory[symbol];
                console.log(`[ServerTradingSystem] Sending ${history.length} historical candles for ${symbol}`);
                ws.send(JSON.stringify({ symbol, history }));
                historySentRef.current.add(symbol);
            }
            const orderBook = marketData.orderBooks[symbol] || null;
            ws.send(JSON.stringify({ symbol, tick, orderBook }));
        }
    }, [marketData.tickStream]);

    // ----------------------------------------------------------------
    // 5.  Derived state
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
    }, [activeInstrument?.data]);

    return {
        instruments,
        activeSymbol,
        setActiveSymbol,
        activeInstrument,
        activeFootprint: {
            data: footprintData,
            cumulativeDeltas,
        },
    };
};
