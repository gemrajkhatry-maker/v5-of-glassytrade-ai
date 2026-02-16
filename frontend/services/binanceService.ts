

import { OHLCData, OrderBook } from '../types';

const BASE_URL = 'https://api.binance.com';
const WS_URL = 'wss://stream.binance.com:9443/ws';
const STREAM_URL = 'wss://stream.binance.com:9443/stream';

/** Calculate delta from volume and taker buy volume: (2 * takerBuyVolume) - volume */
const calculateDelta = (volume: number, takerBuyVolume: number): number =>
    (2 * takerBuyVolume) - volume;

// Normalize symbol to Binance format (e.g. "BTC" -> "BTCUSDT")
export const normalizeSymbol = (symbol: string): string => {
  // Remove slash and spaces, uppercase
  let s = symbol.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
  
  // Common mappings if user just types "BTC" or "ETH"
  if (['BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOGE', 'BNB'].includes(s)) {
    return s + 'USDT';
  }
  
  // If it doesn't look like a pair, assume USDT pair
  if (s.length <= 4 && !s.endsWith('USDT') && !s.endsWith('BTC')) {
     return s + 'USDT';
  }
  
  return s;
};

export const scanMarketCandidates = async (_limit: number = 6): Promise<string[]> => {
  // Locked to BTCUSDT only for focused LLM testing
  return ['BTCUSDT'];
};

export const fetchHistoricalData = async (symbol: string, interval: string = '1h', limit: number = 1000): Promise<OHLCData[]> => {
  try {
    const cleanSymbol = normalizeSymbol(symbol);
    const res = await fetch(`${BASE_URL}/api/v3/klines?symbol=${cleanSymbol}&interval=${interval}&limit=${limit}`);
    
    if (!res.ok) throw new Error('Symbol not found');
    
    const data = await res.json();
    
    return data.map((d: any) => {
        const volume = parseFloat(d[5]);
        const quoteVolume = parseFloat(d[7]);
        const takerBuyVolume = parseFloat(d[9]); // Aggressive Buy Volume
        
        // Approximate VWAP
        const vwap = volume > 0 ? quoteVolume / volume : (parseFloat(d[1]) + parseFloat(d[4])) / 2;
        
        // Delta Approximation
        const delta = calculateDelta(volume, takerBuyVolume);

        return {
            time: new Date(d[0]).toISOString(),
            open: parseFloat(d[1]),
            high: parseFloat(d[2]),
            low: parseFloat(d[3]),
            close: parseFloat(d[4]),
            volume: volume,
            vwap: vwap,
            takerBuyVolume: takerBuyVolume,
            delta: delta
        };
    });
  } catch (err) {
    console.error(`Binance fetch error for ${symbol}:`, err);
    return [];
  }
};

export const fetchOrderBook = async (symbol: string): Promise<OrderBook | null> => {
  try {
    const cleanSymbol = normalizeSymbol(symbol);
    const res = await fetch(`${BASE_URL}/api/v3/depth?symbol=${cleanSymbol}&limit=50`);
    
    if (!res.ok) throw new Error('Orderbook not found');
    
    const data = await res.json();
    
    return {
      bids: data.bids.map((b: any) => ({ price: parseFloat(b[0]), quantity: parseFloat(b[1]) })),
      asks: data.asks.map((a: any) => ({ price: parseFloat(a[0]), quantity: parseFloat(a[1]) }))
    };
  } catch (err) {
    console.warn("Orderbook fetch error:", err);
    return null;
  }
};

/**
 * Subscribes to multiple symbols via a single Combined Stream
 */
export const subscribeToCombinedTicker = (
  symbols: string[], 
  interval: string, 
  onUpdate: (symbol: string, data: OHLCData) => void
) => {
  // Format: <symbol>@kline_<interval>
  const streams = symbols.map(s => `${normalizeSymbol(s).toLowerCase()}@kline_${interval}`).join('/');
  const url = `${STREAM_URL}?streams=${streams}`;
  
  const ws = new WebSocket(url);
  
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      // msg.data contains the payload, msg.stream contains stream name
      if (msg.data && msg.data.e === 'kline') {
        const { s, k } = msg.data; // s is symbol, k is kline
        const { t, o, h, l, c, v, q, V } = k;
        
        const volume = parseFloat(v);
        const quoteVolume = parseFloat(q);
        const takerBuyVolume = parseFloat(V);
        const vwap = volume > 0 ? quoteVolume / volume : (parseFloat(o) + parseFloat(c)) / 2;
        const delta = calculateDelta(volume, takerBuyVolume);

        onUpdate(s, {
          time: new Date(t).toISOString(),
          open: parseFloat(o),
          high: parseFloat(h),
          low: parseFloat(l),
          close: parseFloat(c),
          volume: volume,
          vwap: vwap,
          takerBuyVolume: takerBuyVolume,
          delta: delta
        });
      }
    } catch (e) {
      console.error("WS Parse Error", e);
    }
  };
  
  ws.onerror = (e) => {
      console.error("WebSocket error", e);
  };

  return () => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
  };
};

// Kept for backward compat if needed, but updated to use normalize
export const subscribeToTicker = (symbol: string, interval: string = '1h', onUpdate: (data: OHLCData) => void) => {
  const cleanSymbol = normalizeSymbol(symbol).toLowerCase();
  const ws = new WebSocket(`${WS_URL}/${cleanSymbol}@kline_${interval}`);
  
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.e === 'kline') {
        const { t, o, h, l, c, v, q, V } = msg.k;
        onUpdate({
            time: new Date(t).toISOString(),
            open: parseFloat(o),
            high: parseFloat(h),
            low: parseFloat(l),
            close: parseFloat(c),
            volume: parseFloat(v),
            vwap: (parseFloat(o) + parseFloat(c)) / 2, // simplified
            takerBuyVolume: parseFloat(V),
            delta: calculateDelta(parseFloat(v), parseFloat(V))
        });
      }
    } catch (e) { console.error(e); }
  };
  return () => { if (ws.readyState === WebSocket.OPEN) ws.close(); };
};