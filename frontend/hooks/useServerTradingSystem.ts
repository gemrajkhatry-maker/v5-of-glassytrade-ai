
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
    // Global event bus for streaming high-frequency data without React renders
    const tickBusRef = useRef<EventTarget>(new EventTarget());
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const heartbeatTimer = useRef<ReturnType<typeof setInterval> | null>(null);
    const lastPongRef = useRef<number>(Date.now());
    const latestFootprint = useRef<Record<string, FootprintCandle> | null>(null);
    const activeSymbolRef = useRef<string>(activeSymbol);
    const parseErrorCount = useRef<number>(0);
    const pendingSubscribeRef = useRef<string | null>(null);
    // Generation counter to prevent stale subscribe messages from racing with
    // rapid activeSymbol changes (e.g. user clicks multiple tabs quickly).
    const subscribeGenRef = useRef(0);

    // --- RAF-batched state updates ---
    // Queue multiple WS messages into a single React render per animation frame.
    // Without this, 9 symbols × ~7 generations/sec = ~60 separate setState calls/sec.
    const pendingUpdatesRef = useRef<Array<(prev: Record<string, InstrumentState>) => Record<string, InstrumentState>>>([]);
    const batchRafRef = useRef(0);

    const batchedSetInstruments = useCallback(
        (updater: (prev: Record<string, InstrumentState>) => Record<string, InstrumentState>) => {
            pendingUpdatesRef.current.push(updater);
            if (!batchRafRef.current) {
                batchRafRef.current = requestAnimationFrame(() => {
                    batchRafRef.current = 0;
                    const fns = pendingUpdatesRef.current.splice(0);
                    if (fns.length === 0) return;
                    setInstruments(prev => {
                        let state = prev;
                        for (const fn of fns) state = fn(state);
                        return state;
                    });
                });
            }
        },
        [],
    );

    // Helper: build URL directly to backend, bypassing Vite proxy.
    // Vite proxy (/api path) re-uses connections and can return 500 when overwhelmed.
    const backendUrl = (path: string) =>
        `${window.location.protocol}//${window.location.hostname}:9090${path}`;

    // ----------------------------------------------------------------
    // 0.  Fetch backend config on mount (retries if backend not ready)
    // ----------------------------------------------------------------
    useEffect(() => {
        let cancelled = false;
        let retryTimer: ReturnType<typeof setTimeout> | null = null;

        const fetchConfig = (attempt: number) => {
            fetch(backendUrl('/api/system/config'))
                .then(res => {
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    return res.json();
                })
                .then(cfg => {
                    if (cancelled) return;
                    console.log('[TradingSystem] Backend config:', cfg);
                    if (cfg.backendPort) backendPortRef.current = cfg.backendPort;
                    const symbols: string[] = cfg.activeSymbols || (cfg.defaultSymbol ? [cfg.defaultSymbol] : []);
                    if (symbols.length > 0) {
                        setInstruments(prev => {
                            const next = { ...prev };
                            for (const sym of symbols) {
                                if (!next[sym]) next[sym] = createInstrumentState(sym);
                            }
                            return next;
                        });
                        setActiveSymbol(symbols[0]);
                    }
                })
                .catch(() => {
                    if (cancelled) return;
                    const delay = Math.min(2000 * Math.pow(1.5, attempt), 10000);
                    console.warn(`[TradingSystem] Backend not available, retrying in ${Math.round(delay / 1000)}s (attempt ${attempt + 1})`);
                    setConnectionStatus('Waiting for backend...');
                    retryTimer = setTimeout(() => fetchConfig(attempt + 1), delay);
                });
        };

        fetchConfig(0);

        return () => {
            cancelled = true;
            if (retryTimer) clearTimeout(retryTimer);
        };
    }, []);

    // ----------------------------------------------------------------
    // 1.  Load persisted LLM decision history on mount
    // ----------------------------------------------------------------
    useEffect(() => {
        fetch(backendUrl('/api/ai/history'))
            .then(res => res.json())
            .then(data => {
                if (!data.decisions || data.decisions.length === 0) return;

                // Group entries by symbol
                const entriesBySymbol: Record<string, LLMHistoryEntry[]> = {};
                for (const d of data.decisions) {
                    const sym = d.symbol || 'UNKNOWN';
                    if (!entriesBySymbol[sym]) entriesBySymbol[sym] = [];

                    entriesBySymbol[sym].push({
                        timestamp: (() => {
                            // Try parsing as-is first; only append 'Z' if it yields
                            // NaN (handles strings that already contain timezone info).
                            let ts = new Date(d.created_at).getTime();
                            if (isNaN(ts)) {
                                ts = new Date(d.created_at + 'Z').getTime();
                            }
                            return ts;
                        })(),
                        direction: d.direction || 'FLAT',
                        confidence: d.confidence || 'Medium',
                        rationale: d.rationale || '',
                        inputPrompt: d.input_prompt || '',
                        rawOutput: d.raw_output || '',
                    });
                }

                setInstruments(prev => {
                    const next = { ...prev };
                    for (const sym of Object.keys(entriesBySymbol)) {
                        if (!next[sym]) next[sym] = createInstrumentState(sym);
                        // Sort by timestamp and keep last 20
                        const sorted = entriesBySymbol[sym].sort((a, b) => a.timestamp - b.timestamp);
                        next[sym] = { ...next[sym], llmHistory: sorted.slice(-20) };
                    }
                    return next;
                });
            })
            .catch(() => { }); // Silently fail if backend not ready
    }, []);

    // ----------------------------------------------------------------
    // 2.  WebSocket message handler
    // ----------------------------------------------------------------
    const handleWsMessage = useCallback((event: MessageEvent) => {
        try {
            const state = JSON.parse(event.data);

            // Any message from backend = connection alive (reset heartbeat)
            lastPongRef.current = Date.now();

            // Handle backend error messages
            if (state.error) {
                console.error('[TradingSystem] Backend error:', state.error);
                setConnectionStatus(state.error);
                return;
            }

            // Symbol switch acknowledgement (no-op, purely informational)
            if (state.status === 'symbol_switched') {
                console.log(`[TradingSystem] Symbol switched to ${state.symbol}`);
                return;
            }

            // Server mode init (multi-symbol)
            if (state.status === 'server_mode') {
                const symbols: string[] = state.activeSymbols || [state.symbol];
                console.log(`[TradingSystem] Server mode: ${symbols.length} symbols`, symbols);
                setInstruments(prev => {
                    const next = { ...prev };

                    // Add new symbols
                    for (const sym of symbols) {
                        if (!next[sym]) next[sym] = createInstrumentState(sym);
                    }

                    // Purge stale symbols (like Crude Oil from a previous session)
                    for (const existingSym of Object.keys(next)) {
                        if (!symbols.includes(existingSym)) {
                            console.log(`[TradingSystem] Purging stale symbol: ${existingSym}`);
                            delete next[existingSym];
                        }
                    }

                    return next;
                });

                setActiveSymbol(prev => {
                    if (prev && symbols.includes(prev)) return prev;
                    return symbols[0];
                });
                return;
            }

            // History loaded from server
            if (state.status === 'history_loaded') {
                if (state.history && state.symbol) {
                    const sym = state.symbol;
                    // CRITICAL: Ensure history is sorted by time to prevent Lightweight Charts crash
                    const sortedHistory = [...state.history].sort((a, b) => 
                        new Date(a.time).getTime() - new Date(b.time).getTime()
                    );
                    setInstruments(prev => {
                        const inst = prev[sym] || createInstrumentState(sym);
                        return {
                            ...prev,
                            [sym]: { ...inst, data: sortedHistory },
                        };
                    });
                }
                console.log(`[TradingSystem] History loaded: ${state.count} candles`);
                return;
            }

            // Handle stale-data notification from backend
            if (state._type === 'stale' && state._symbol) {
                setInstruments(prev => {
                    const existing = prev[state._symbol];
                    if (!existing) return prev;
                    return { ...prev, [state._symbol]: { ...existing, stale: true } };
                });
                return;
            }

            // Handle pong (heartbeat response)
            if (state.pong) {
                lastPongRef.current = Date.now();
                return;
            }

            // State update from backend (full or delta)
            const symbol: string = state._symbol;
            if (!symbol) return;

            // Delta compression: merge only changed fields into existing state
            if (state._type === 'delta') {
                // Dispatch tick event OUTSIDE React state updater
                if (state.tick) {
                    tickBusRef.current.dispatchEvent(new CustomEvent('tick', {
                        detail: { symbol, tick: state.tick }
                    }));
                }
                if (state.footprint) {
                    latestFootprint.current = state.footprint;
                }

                // Tick-only delta (no analytics) — skip React state update.
                // Chart already updated natively via tickBus; state syncs on next analytics delta (~500ms).
                const hasAnalytics = state.portfolio !== undefined ||
                    state.amt !== undefined ||
                    state.genAIAnalysis !== undefined ||
                    state.prediction !== undefined ||
                    state.riskState !== undefined ||
                    state.agentDecision !== undefined ||
                    state.overseerAction !== undefined ||
                    state.overseerReason !== undefined ||
                    state.depth !== undefined ||
                    state.depth20Active !== undefined ||
                    state.stats !== undefined ||
                    state.ltp !== undefined ||
                    state.oi !== undefined;

                if (!hasAnalytics) {
                    return;
                }

                // Analytics delta: batch into next animation frame
                batchedSetInstruments(prev => {
                    const existing = prev[symbol];
                    if (!existing) return prev;

                    const merged: any = { ...existing, lastUpdate: Date.now(), stale: false };

                    if (state.tick) {
                        const newData = [...existing.data];
                        const last = newData[newData.length - 1];
                        if (last && state.tick.time === last.time) {
                            newData[newData.length - 1] = state.tick;
                        } else if (!last || new Date(state.tick.time).getTime() > new Date(last.time).getTime()) {
                            // Only append if it's strictly newer to maintain ascending order
                            newData.push(state.tick);
                            if (newData.length > 1000) newData.shift();
                        }
                        merged.data = newData;
                    }

                    if (state.portfolio !== undefined) merged.portfolio = { ...existing.portfolio, ...state.portfolio };
                    if (state.amt !== undefined) {
                        merged.amtAnalysis = state.amt === null ? null : { ...existing.amtAnalysis, ...state.amt };
                    }
                    if (state.genAIAnalysis !== undefined) merged.genAIAnalysis = { ...existing.genAIAnalysis, ...state.genAIAnalysis };
                    if (state.prediction?.predictions !== undefined) merged.predictions = state.prediction.predictions;
                    if (state.prediction?.analysis !== undefined) merged.aiAnalysis = state.prediction.analysis;
                    if (state.modelWeights !== undefined) merged.modelWeights = { ...existing.modelWeights, ...state.modelWeights };
                    if (state.generation !== undefined) merged.generation = state.generation;
                    if (state.riskState !== undefined) merged.riskState = { ...existing.riskState, ...state.riskState };
                    if (state.agentDecision !== undefined) merged.agentDecision = state.agentDecision;
                    if (state.overseerAction !== undefined) merged.overseerAction = state.overseerAction;
                    if (state.overseerReason !== undefined) merged.overseerReason = state.overseerReason;
                    if (state.depth !== undefined) merged.orderBook = state.depth;
                    if (state.depth20Active !== undefined) merged.depth20Active = state.depth20Active;
                    if (state.stats !== undefined) merged.stats = { ...existing.stats, ...state.stats };
                    if (state.ltp !== undefined) merged.ltp = state.ltp;
                    if (state.oi !== undefined) merged.oi = state.oi;
                    if (state.rangeBars !== undefined) merged.rangeBars = state.rangeBars;

                    // History tracking: Listen for both standard generative AI and the new reasoning worker
                    const newAi = state.genAIAnalysis;
                    const hasNewReasoning = state.amt?.tradeDecision && state.amt?.tradeDecision !== 'FLAT';
                    
                    if (newAi?.inputPrompt || hasNewReasoning) {
                        const lastEntry = existing.llmHistory[existing.llmHistory.length - 1];
                        const newPrompt = newAi?.inputPrompt || "Reasoning Model Analysis";
                        
                        if (!lastEntry || lastEntry.inputPrompt !== newPrompt) {
                            merged.llmHistory = [...existing.llmHistory, {
                                timestamp: Date.now(),
                                direction: newAi?.direction || state.amt.tradeDecision,
                                confidence: newAi?.confidence || 'High',
                                rationale: newAi?.rationale || state.amt.llmThinking,
                                inputPrompt: newPrompt,
                                rawOutput: newAi?.rawOutput || state.amt.llmThinking,
                            }].slice(-20);
                        }
                    }

                    return { ...prev, [symbol]: merged };
                });
                return;
            }

            // Dispatch tick event OUTSIDE React state updater
            if (state.tick) {
                tickBusRef.current.dispatchEvent(new CustomEvent('tick', {
                    detail: { symbol, tick: state.tick }
                }));
            }
            if (state.footprint) {
                latestFootprint.current = state.footprint;
            }

            // Full state (_type === 'full' or no _type) — batch into next animation frame
            batchedSetInstruments(prev => {
                const inst = prev[symbol] || createInstrumentState(symbol);

                let newData = inst.data;
                if (state.tick) {
                    newData = [...inst.data];
                    const last = newData[newData.length - 1];
                    if (last && state.tick.time === last.time) {
                        newData[newData.length - 1] = state.tick;
                    } else if (!last || new Date(state.tick.time).getTime() > new Date(last.time).getTime()) {
                        newData.push(state.tick);
                        if (newData.length > 1000) newData.shift();
                    }
                }

                const newPortfolio = state.portfolio ?? inst.portfolio;
                // FIX: When backend sends explicit `amt: null`, clear stale value instead of
                // falling back to hours-old cached analysis. Only use cached value when the
                // key is absent from the message (meaning "no change" in delta protocol).
                const newAmtAnalysis = 'amt' in state
                    ? (state.amt ?? null)
                    : inst.amtAnalysis;
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
                        rangeBars: state.rangeBars ?? inst.rangeBars,
                        lastUpdate: Date.now(),
                    },
                };
            });
            // Successful parse — reset consecutive error counter
            parseErrorCount.current = 0;

            // Clear pending subscribe when we receive state for the subscribed symbol
            if (symbol && pendingSubscribeRef.current === symbol) {
                pendingSubscribeRef.current = null;
            }
        } catch (e) {
            console.error('[TradingSystem] WS parse error', e);
            parseErrorCount.current += 1;
            // If 3+ consecutive parse errors, connection is likely desynchronized
            if (parseErrorCount.current >= 3) {
                console.warn('[TradingSystem] 3+ consecutive parse errors, reconnecting WS');
                parseErrorCount.current = 0;
                wsRef.current?.close();
            }
        }
    }, []);

    // ----------------------------------------------------------------
    // 3.  WebSocket connection
    // ----------------------------------------------------------------
    const retryCountRef = useRef(0);
    // Default to 9090 so WS connects directly to backend even before config loads.
    // Config fetch may update this, but we never fall back to the Vite dev server port.
    const backendPortRef = useRef<number>(9090);

    const connect = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) return;

        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        // Always connect directly to backend port (default: 9090) — never route through Vite proxy.
        const wsHost = `${window.location.hostname}:${backendPortRef.current}`;
        const ws = new WebSocket(`${protocol}://${wsHost}/api/trading/ws/gameloop`);

        ws.onopen = () => {
            console.log('[TradingSystem] WS connected');
            retryCountRef.current = 0;
            setConnected(true);
            setConnectionStatus('');
            lastPongRef.current = Date.now();
            // Send initial subscribe for current activeSymbol
            if (activeSymbolRef.current) {
                if (pendingSubscribeRef.current) {
                    // Already subscribing, update the pending target
                    pendingSubscribeRef.current = activeSymbolRef.current;
                } else {
                    pendingSubscribeRef.current = activeSymbolRef.current;
                    ws.send(JSON.stringify({ subscribe: activeSymbolRef.current }));
                    console.log(`[TradingSystem] Initial subscribe: ${activeSymbolRef.current}`);
                }
            }
            // Start heartbeat: ping every 15s, detect dead connection if no pong in 20s
            if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
            heartbeatTimer.current = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ ping: true }));
                    // If no pong received within 45s (3x heartbeat interval), connection is dead
                    if (Date.now() - lastPongRef.current > 45_000) {
                        console.warn('[TradingSystem] Heartbeat timeout, closing WS');
                        ws.close();
                    }
                }
            }, 15_000);
        };

        ws.onmessage = handleWsMessage;

        ws.onclose = (e) => {
            setConnected(false);
            if (heartbeatTimer.current) {
                clearInterval(heartbeatTimer.current);
                heartbeatTimer.current = null;
            }
            if (e.code !== 1000 && wsRef.current) {
                retryCountRef.current += 1;
                const delay = Math.min(500 * Math.pow(2, retryCountRef.current), 5000);
                setConnectionStatus(`Disconnected — reconnecting in ${Math.round(delay / 1000)}s...`);
                console.warn(`[TradingSystem] WS disconnected, reconnecting in ${delay}ms…`);
                reconnectTimer.current = setTimeout(() => {
                    connect();
                }, delay);
            }
        };

        ws.onerror = () => { };

        wsRef.current = ws;
    }, [handleWsMessage]);

    // Connect once after config loads activeSymbol
    const hasConnected = useRef(false);
    useEffect(() => {
        if (!activeSymbol || hasConnected.current) return;
        hasConnected.current = true;
        connect();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeSymbol]);

    // Unmount cleanup ONLY
    useEffect(() => {
        return () => {
            if (batchRafRef.current) cancelAnimationFrame(batchRafRef.current);
            if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
            if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
            if (wsRef.current) {
                const ws = wsRef.current;
                wsRef.current = null;
                ws.close(1000, "Component Unmounted");
            }
        };
    }, []);

    // When activeSymbol changes, keep ref in sync and subscribe if connected.
    // Debounce by 80ms so rapid tab-clicks only emit one subscribe message.
    useEffect(() => {
        // Increment generation to invalidate any in-flight stale subscribes
        subscribeGenRef.current += 1;
        const gen = subscribeGenRef.current;

        // Keep ref in sync for use in onopen callback
        activeSymbolRef.current = activeSymbol;

        if (!connected || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !activeSymbol) {
            return;
        }

        const timer = setTimeout(() => {
            // Drop if a newer symbol was selected before the debounce fired
            if (subscribeGenRef.current !== gen) return;
            wsRef.current!.send(JSON.stringify({ subscribe: activeSymbol }));
            console.log(`[TradingSystem] Subscribed to symbol: ${activeSymbol} (gen=${gen})`);
        }, 80);

        return () => clearTimeout(timer);
    }, [activeSymbol, connected]);

    // ----------------------------------------------------------------
    // 4.  Derived state
    // ----------------------------------------------------------------
    const activeInstrument = instruments[activeSymbol];

    const footprintData = useMemo<Record<string, FootprintCandle> | null>(() => {
        return latestFootprint.current;
    }, [activeInstrument?.data?.length]);

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
        tickBus: tickBusRef.current,
    };
};
