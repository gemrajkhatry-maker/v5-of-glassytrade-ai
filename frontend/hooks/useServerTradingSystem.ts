import { useState, useEffect, useRef, useCallback } from 'react';
import {
    InstrumentState,
    ChartConfig,
    OHLCData,
    LLMHistoryEntry,
} from '../types';
import { NETWORK_CONFIG } from '../config';

/**
 * Append a deterministic quantDecision to the per-symbol decision history.
 * Dedupes consecutive identical decisions (same rationale+phase within 10s)
 * so the 0.5s delta stream doesn't spam the panel.
 */
const mergeDecisionHistory = (
    existing: LLMHistoryEntry[],
    qd: any,
): LLMHistoryEntry[] => {
    if (!qd) return existing;
    const signal = qd.signal || {};
    const entry: LLMHistoryEntry = {
        timestamp: Date.now(),
        direction: String(signal.type || 'FLAT').toUpperCase() as LLMHistoryEntry['direction'],
        confidence: signal.confidence?.toString() ?? 'Low',
        rationale: qd.reason || '',
        inputPrompt: qd.inputPrompt,
        rawOutput: qd.rawOutput,
    };
    const last = existing[existing.length - 1];
    if (
        last &&
        last.rationale === entry.rationale &&
        last.inputPrompt === entry.inputPrompt &&
        Date.now() - last.timestamp < 10_000
    ) {
        return existing;
    }
    return [...existing, entry].slice(-20);
};

/**
 * Creates a fresh instrument state.
 * Used on initialisation before the backend has responded.
 */
const createInstrumentState = (symbol: string): InstrumentState => ({
    symbol,
    data: [],
    orderBook: null,
    // Contract: these defaults MUST mirror the backend's portfolio DTO
    // (quant/state.py StateProjector._portfolio + quant/ws_adapter.py
    // view_state_to_ws) — the WS delta-merge treats the backend portfolio as
    // authoritative and replaces these values on the first snapshot.
    portfolio: {
        balance: 1_000_000,
        equity: 1_000_000,
        leverage: 10,
        positions: [],
        closedTrades: [],
    },
    aiAnalysis: null,
    genAIAnalysis: null,
    amtAnalysis: null,
    auctionAnalysis: null,
    quantDecisionAnalysis: null,
    riskState: null,
    agentDecision: null,
    llmHistory: [],
    overseerAction: '',
    overseerReason: '',
    runtimeSafety: {
        brokerBound: false,
        feedStale: false,
        unsafeToTrade: false,
    },
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
    const activeSymbolRef = useRef<string>(activeSymbol);
    const parseErrorCount = useRef<number>(0);
    const pendingSubscribeRef = useRef<string | null>(null);
    // Generation counter to prevent stale subscribe messages from racing with
    // rapid activeSymbol changes (e.g. user clicks multiple tabs quickly).
    const subscribeGenRef = useRef(0);
    // RAF-batched state updates
    // Queue multiple WS messages into a single React render per animation frame.
    // Without this, 9 symbols × ~7 generations/sec = ~60 separate setState calls/sec.
    const pendingUpdatesRef = useRef<Array<(prev: Record<string, InstrumentState>) => Record<string, InstrumentState>>>([]);
    const batchRafRef = useRef(0);
    const MAX_RAF_QUEUE_SIZE = NETWORK_CONFIG.maxRafQueueSize; // Backpressure: drop updates if queue grows too large

    const batchedSetInstruments = useCallback(
        (updater: (prev: Record<string, InstrumentState>) => Record<string, InstrumentState>) => {
            // Backpressure: drop intermediate updates if queue is too large
            if (pendingUpdatesRef.current.length >= MAX_RAF_QUEUE_SIZE) {
                // Remove oldest update, keep latest
                pendingUpdatesRef.current.splice(0, pendingUpdatesRef.current.length - 1);
            }
            
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

    // REST/WS targets:
    // - VITE_BACKEND_URL: full origin (e.g. http://127.0.0.1:9090) for prod / custom setups
    // - Dev: same-origin `/api/...` so Vite's proxy (vite.config) reaches the backend
    // - Else: direct host:PORT (default9090)
    const explicitBackend = (import.meta.env.VITE_BACKEND_URL as string | undefined)?.trim();
    const defaultPort = Number(import.meta.env.VITE_BACKEND_PORT) || 9090;
    const backendPortRef = useRef<number>(defaultPort);
    const backendUrl = (path: string) => {
        if (explicitBackend) {
            return `${explicitBackend.replace(/\/$/, '')}${path}`;
        }
        if (import.meta.env.DEV) {
            return path;
        }
        return `${window.location.protocol}//${window.location.hostname}:${backendPortRef.current}${path}`;
    };
    const websocketUrl = (path: string) => {
        const isSecure = window.location.protocol === 'https:';
        const wsScheme = isSecure ? 'wss' : 'ws';
        if (explicitBackend) {
            const base = explicitBackend.replace(/\/$/, '');
            const origin = base.startsWith('https://')
                ? 'wss://' + base.slice('https://'.length)
                : base.startsWith('http://')
                  ? 'ws://' + base.slice('http://'.length)
                  : base;
            return `${origin}${path}`;
        }
        if (import.meta.env.DEV) {
            return `${wsScheme}://${window.location.host}${path}`;
        }
        return `${wsScheme}://${window.location.hostname}:${backendPortRef.current}${path}`;
    };

    // ----------------------------------------------------------------
    // 0.  Fetch backend config on mount (retries if backend not ready)
    // ----------------------------------------------------------------
    useEffect(() => {
        let cancelled = false;
        let retryTimer: ReturnType<typeof setTimeout> | null = null;

        // Lifespan option scan can block HTTP for minutes — avoid aborting too early.
        const configTimeoutMs = NETWORK_CONFIG.configTimeoutMs;
        const fetchOpts: RequestInit =
            typeof AbortSignal !== 'undefined' && 'timeout' in AbortSignal
                ? { signal: AbortSignal.timeout(configTimeoutMs) }
                : {};

        const configUrls = (): string[] => {
            if (explicitBackend) {
                return [`${explicitBackend.replace(/\/$/, '')}/api/system/config`];
            }
            if (import.meta.env.DEV) {
                return [
                    '/api/system/config',
                    `http://127.0.0.1:${defaultPort}/api/system/config`,
                ];
            }
            return [`${window.location.protocol}//${window.location.hostname}:${backendPortRef.current}/api/system/config`];
        };

        const applyConfig = (cfg: Record<string, unknown>) => {
            if (cancelled) return;
            console.log('[TradingSystem] Backend config:', cfg);
            const bp = cfg.backendPort;
            if (typeof bp === 'number' && bp > 0) backendPortRef.current = bp;
            let symbols: string[] =
                (cfg.activeSymbols as string[]) ||
                (cfg.defaultSymbol ? [String(cfg.defaultSymbol)] : []);
            symbols = symbols.map((s) => String(s).trim()).filter(Boolean);
            if (symbols.length === 0) {
                symbols = ['CRUDEOIL', 'NATURALGAS'];
                console.warn('[TradingSystem] API returned no symbols; using MCX defaults');
            }
            setConnectionStatus('');
            setInstruments(prev => {
                const next = { ...prev };
                for (const sym of symbols) {
                    if (!next[sym]) next[sym] = createInstrumentState(sym);
                }
                return next;
            });
            setActiveSymbol(symbols[0]);
            warmHistoryForSymbols(symbols, String(cfg.interval || '1m'));
        };

        const fetchConfig = async (attempt: number) => {
            if (cancelled) return;
            setConnectionStatus(
                attempt === 0
                    ? 'Loading server config (first start can take 1–2 min while the API scans contracts)…'
                    : `Retrying server config (attempt ${attempt + 1})…`,
            );

            let lastHttp = 0;
            let sawNetworkError = false;
            for (const url of configUrls()) {
                if (cancelled) return;
                try {
                    const res = await fetch(url, fetchOpts);
                    lastHttp = res.status;
                    if (res.status === 503) {
                        setConnectionStatus('API is starting (trading session not ready yet). Retrying…');
                        break;
                    }
                    if (!res.ok) continue;
                    const cfg = await res.json();
                    applyConfig(cfg);
                    return;
                } catch {
                    sawNetworkError = true;
                }
            }

            if (cancelled) return;
            const delay = Math.min(2000 * Math.pow(1.5, attempt), 10000);
            const hint =
                import.meta.env.DEV && !explicitBackend
                    ? ` No response from proxy or http://127.0.0.1:${defaultPort}. Run: cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port ${defaultPort}`
                    : '';
            console.warn(
                `[TradingSystem] Config fetch failed (last HTTP ${lastHttp || 'n/a'}, networkError=${sawNetworkError}). Retry in ${Math.round(delay / 1000)}s.${hint}`,
            );
            setConnectionStatus(
                lastHttp === 503
                    ? 'Backend still starting… will retry.'
                    : `Cannot load /api/system/config (HTTP ${lastHttp || 'error'}). Is uvicorn on port ${defaultPort}?`,
            );
            retryTimer = setTimeout(() => void fetchConfig(attempt + 1), delay);
        };

        void fetchConfig(0);

        return () => {
            cancelled = true;
            if (retryTimer) clearTimeout(retryTimer);
        };
    }, []);

    // ----------------------------------------------------------------
    // 2a. Warm chart history from REST /api/market/history/{symbol}
    // ----------------------------------------------------------------
    // The greenfield backend streams live bars over the WS but keeps no OHLC
    // ring buffer server-side. Fetch the Dhan history REST endpoint once per
    // symbol after server_mode so the chart has a warm background of real
    // candles instead of starting empty and filling in tick-by-tick.
    // Candles are merged with any live ticks that already streamed in.
    const warmHistoryForSymbols = useCallback((symbols: string[], interval: string) => {
        for (const sym of symbols) {
            const path = `/api/market/history/${encodeURIComponent(sym)}`;
            const url = `${backendUrl(path)}?interval=${encodeURIComponent(interval || '1m')}&limit=500`;
            fetch(url)
                .then(res => (res.ok ? res.json() : null))
                .then(body => {
                    const candles = body?.data;
                    if (!Array.isArray(candles) || candles.length === 0) return;
                    const history: OHLCData[] = candles.map((c: any) => ({
                        time: String(c.time),
                        open: Number(c.open),
                        high: Number(c.high),
                        low: Number(c.low),
                        close: Number(c.close),
                        volume: Number(c.volume ?? 0),
                        vwap: Number(c.vwap ?? 0),
                        takerBuyVolume: Number(c.takerBuyVolume ?? 0),
                        delta: Number(c.delta ?? 0),
                    }));
                    setInstruments(prev => {
                        const inst = prev[sym] || createInstrumentState(sym);
                        // Union warm history + any already-streamed live bars,
                        // sorted ascending and deduped by time.
                        const byTime = new Map<string, OHLCData>();
                        for (const c of history) byTime.set(c.time, c);
                        for (const c of inst.data) byTime.set(c.time, c);
                        const merged = [...byTime.values()].sort(
                            (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime(),
                        );
                        return { ...prev, [sym]: { ...inst, data: merged } };
                    });
                })
                .catch(() => {
                    // Backend not ready or symbol unsupported — chart warms from live ticks.
                });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
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

                // Phase 2: warm the chart with REST history for every symbol.
                // The WS tick stream only carries the live bar; this fills the
                // background with real Dhan candles matching the live interval.
                warmHistoryForSymbols(symbols, String(state.interval || ''));
                return;
            }

            // History loaded from server
            if (state.status === 'history_loaded') {
                if (state.history && state.symbol) {
                    const sym = state.symbol;

                    // Initial history load: replace data.
                    // gap_fill messages are handled identically — the backend's gap-fill
                    // history contains real candles; no candles are fabricated client-side.
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

                // Tick-only delta (no analytics) — skip React state update.
                // Chart already updated natively via tickBus; state syncs on next analytics delta (~500ms).
                const hasAnalytics = state.portfolio !== undefined ||
                    state.amt !== undefined ||
                    state.auction !== undefined ||
                    state.quantDecision !== undefined ||
                    state.riskState !== undefined ||
                    state.agentDecision !== undefined ||
                    state.depth !== undefined ||
                    state.ltp !== undefined ||
                    state.oi !== undefined;

                if (!hasAnalytics) {
                    return;
                }

                // Analytics delta: batch into next animation frame
                batchedSetInstruments(prev => {
                    const existing = prev[symbol] || createInstrumentState(symbol);

                    const merged: any = { ...existing, lastUpdate: Date.now() };

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
                    if (state.auction !== undefined) merged.auctionAnalysis = { ...existing.auctionAnalysis, ...state.auction };
                    if (state.quantDecision !== undefined) {
                        merged.quantDecisionAnalysis = { ...existing.quantDecisionAnalysis, ...state.quantDecision };
                        merged.llmHistory = mergeDecisionHistory(existing.llmHistory, state.quantDecision);
                    }
                    if (state.riskState !== undefined) merged.riskState = { ...existing.riskState, ...state.riskState };
                    if (state.agentDecision !== undefined) merged.agentDecision = state.agentDecision;
                    if (state.depth !== undefined) merged.orderBook = state.depth;
                    if (state.ltp !== undefined) merged.ltp = state.ltp;
                    if (state.oi !== undefined) merged.oi = state.oi;

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
                const newAuctionAnalysis = 'auction' in state
                    ? (state.auction ?? null)
                    : inst.auctionAnalysis;
                const newQuantDecisionAnalysis = 'quantDecision' in state
                    ? (state.quantDecision ?? null)
                    : inst.quantDecisionAnalysis;
                const newRiskState = state.riskState ?? inst.riskState;
                const newAgentDecision = state.agentDecision ?? inst.agentDecision;

                return {
                    ...prev,
                    [symbol]: {
                        ...inst,
                        data: newData,
                        portfolio: newPortfolio,
                        amtAnalysis: newAmtAnalysis,
                        auctionAnalysis: newAuctionAnalysis,
                        quantDecisionAnalysis: newQuantDecisionAnalysis,
                        llmHistory: mergeDecisionHistory(inst.llmHistory, state.quantDecision),
                        riskState: newRiskState,
                        agentDecision: newAgentDecision,
                        orderBook: state.depth ?? inst.orderBook,
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

    const connect = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) return;

        const ws = new WebSocket(websocketUrl('/api/trading/ws/gameloop'));

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
                // Backoff: 1s → 2s → 5s (max)
                const delay = Math.min(1000 * Math.pow(2, retryCountRef.current - 1), 5000);
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
        if (!activeSymbol) return;
        // React StrictMode double-mounts: first mount opens WS, cleanup closes it.
        // On second mount, hasConnected is true but wsRef was nulled — must reconnect.
        const wsStillAlive = wsRef.current?.readyState === WebSocket.OPEN;
        if (hasConnected.current && wsStillAlive) return;
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

    return {
        instruments,
        activeSymbol,
        setActiveSymbol,
        activeInstrument,
        connected,
        connectionStatus,
        tickBus: tickBusRef.current,
    };
};
