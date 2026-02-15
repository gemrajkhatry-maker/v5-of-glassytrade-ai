
import { useState, useEffect, useRef, useCallback } from 'react';
import { OHLCData, OrderBook } from '../types';
import { 
    scanMarketCandidates, 
    fetchHistoricalData, 
    fetchOrderBook, 
    subscribeToCombinedTicker, 
    normalizeSymbol 
} from '../services/binanceService';

export interface MarketDataState {
    candidates: string[];
    isScanning: boolean;
    orderBooks: Record<string, OrderBook>;
}

export const useBinanceData = (interval: string) => {
    const [state, setState] = useState<MarketDataState>({
        candidates: [],
        isScanning: true,
        orderBooks: {}
    });

    const [tickStream, setTickStream] = useState<{symbol: string, tick: OHLCData} | null>(null);
    const [initialHistory, setInitialHistory] = useState<Record<string, OHLCData[]>>({});

    // 1. Scan and Fetch Initial History
    useEffect(() => {
        const init = async () => {
            const candidates = await scanMarketCandidates();
            const historyMap: Record<string, OHLCData[]> = {};
            const bookMap: Record<string, OrderBook> = {};

            await Promise.all(candidates.map(async (sym) => {
                historyMap[sym] = await fetchHistoricalData(sym, interval, 500);
                const book = await fetchOrderBook(sym);
                if (book) bookMap[sym] = book;
            }));

            setInitialHistory(historyMap);
            setState(prev => ({
                ...prev,
                candidates,
                isScanning: false,
                orderBooks: bookMap
            }));
        };

        init();
    }, [interval]);

    // 2. WebSocket Subscription
    useEffect(() => {
        if (state.candidates.length === 0) return;

        const cleanup = subscribeToCombinedTicker(state.candidates, interval, (rawSym, tick) => {
            const symbol = normalizeSymbol(rawSym);
            setTickStream({ symbol, tick });
        });

        // Polling Orderbooks
        const intervalId = setInterval(async () => {
            for (const sym of state.candidates) {
                const book = await fetchOrderBook(sym);
                if (book) {
                    setState(prev => ({
                        ...prev,
                        orderBooks: { ...prev.orderBooks, [sym]: book }
                    }));
                }
            }
        }, 10000);

        return () => {
            cleanup();
            clearInterval(intervalId);
        };
    }, [state.candidates, interval]);

    return {
        ...state,
        initialHistory,
        tickStream
    };
};
