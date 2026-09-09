/**
 * PHASE 0 — FRONTEND TEST HARNESS
 *
 * Provides:
 * 1. Realistic WebSocket mock that captures inbound payloads
 * 2. Fetch mock that returns deterministic backend responses
 * 3. Event handler test helpers
 * 4. DOM assertion utilities
 *
 * Usage in a test file:
 *   import { describe, it, expect, beforeEach, afterEach } from 'vitest';
 *   import { setupTransportHarness, flushTransport, clearTransport } from './setup_harness';
 *
 *   describe('WS ingestion', () => {
 *     setupTransportHarness();
 *     it('receives snapshot', async () => {
 *       const ws = new WebSocket('ws://localhost/gameloop');
 *       await flushTransport(); // wait for mock WS open
 *       expect(wsInboundMessages.length).toBeGreaterThan(0);
 *     });
 *   });
 */

import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

// ---------------------------------------------------------------------------
// In-memory inbound payload capture
// ---------------------------------------------------------------------------

export const wsInboundMessages: string[] = [];
export const wsOutboundMessages: string[] = [];
export const fetchInboundRequests: Request[] = [];

// ---------------------------------------------------------------------------
// Realistic WebSocket mock (captures frames, simulates latency, supports JSON)
// ---------------------------------------------------------------------------

type WsReadyState = 0 | 1 | 2 | 3;

class HarnessWebSocket {
  public url: string;
  public readyState: WsReadyState = HarnessWebSocket.CONNECTING;
  public onopen: (() => void) | null = null;
  public onclose: ((code: number, reason: string) => void) | null = null;
  public onmessage: ((evt: { data: string }) => void) | null = null;
  public onerror: ((err: Error) => void) | null = null;

  // Delay before "opening" (ms) — realistic async
  private _openDelay = 10;

  constructor(url: string) {
    this.url = url;
    // Simulate async connection
    setTimeout(() => this._open(), this._openDelay);
  }

  private _open() {
    this.readyState = HarnessWebSocket.OPEN;
    this.onopen?.();
  }

  send(data: string) {
    if (this.readyState !== HarnessWebSocket.OPEN) {
      throw new Error(`WebSocket.send while in state ${this.readyState}`);
    }
    wsOutboundMessages.push(data);
  }

  close(code = 1000, reason = 'Normal closure') {
    this.readyState = HarnessWebSocket.CLOSED;
    this.onclose?.(code, reason);
  }

  // Test helpers — inject inbound frames as if from the server
  static inject(ws: HarnessWebSocket, payload: unknown, { json = true } = {}) {
    const frame = json ? JSON.stringify(payload) : payload as string;
    ws.onmessage?.({ data: frame });
    wsInboundMessages.push(frame);
  }

  static injectJSON(ws: HarnessWebSocket, payload: unknown) {
    this.inject(ws, payload, { json: true });
  }

  static simulateDisconnect(ws: HarnessWebSocket) {
    ws.readyState = HarnessWebSocket.CLOSING;
    setTimeout(() => ws.close(1006, 'Abnormal closure'), 0);
  }

  static reset(ws: HarnessWebSocket) {
    ws.readyState = HarnessWebSocket.OPEN;
    ws.onopen?.();
  }
}

HarnessWebSocket.CONNECTING = 0 as const;
HarnessWebSocket.OPEN = 1 as const;
HarnessWebSocket.CLOSING = 2 as const;
HarnessWebSocket.CLOSED = 3 as const;

// ---------------------------------------------------------------------------
// Deterministic backend responses (shaped exactly like real payloads)
// ---------------------------------------------------------------------------

export const mockBackendResponses = {
  // GET /api/health
  health: () => ({
    status: 'ok' as const,
    checks: {
      active_symbols: 'ok(2)',
      scanner_settings: 'ok',
      broker_runtime: 'ok',
      storage_runtime: 'ok',
      strategy_runtime: 'ok',
      position_close_contract: 'ok',
      reconciliation: 'ok',
    },
    contract_id: 'startup-contract:a1b2c3d4e5f6',
  }),

  // GET /api/system/config
  systemConfig: () => ({
    dataSource: 'DHAN' as const,
    serverDriven: true as const,
    defaultSymbol: 'CRUDEOIL SEP FUT',
    activeSymbols: ['CRUDEOIL SEP FUT', 'NATURALGAS SEP FUT'],
    probabilityReady: true,
    playbookGuardMaxRejections: 3,
    explainabilityAlertMinTrades: 12,
    explainabilityMinCoverageRate: 95,
    explainabilityMinAggressionRate: 80,
  }),

  // GET /api/market/history/{symbol}
  history: (symbol: string, n = 30) => {
    const candles = [];
    let price = symbol.includes('CRUDEOIL') ? 6200 : 200;
    for (let i = 0; i < n; i++) {
      const open = price;
      const close = price + (i % 5 === 0 ? (i % 10 === 0 ? 5 : -5) : 0);
      candles.push({
        time: `2026-08-${String(i + 1).padStart(2, '0')}T09:${String(i % 60).padStart(2, '0')}:00Z`,
        open,
        high: close + Math.abs(i % 3),
        low: close - Math.abs(i % 3),
        close,
        volume: 100 + i * 10,
        vwap: (open + close) / 2,
        takerBuyVolume: Math.floor((i + 1) * 6),
        delta: Math.floor((i + 1) * 2),
      });
      price = close;
    }
    return { data: candles };
  },

  // WS snapshot payload for a symbol
  snapshot: (symbol: string) => ({
    _symbol: symbol,
    _type: 'full' as const,
    ltp: symbol.includes('CRUDEOIL') ? 6210 : 205,
    pnl: symbol.includes('CRUDEOIL') ? 150 : -25,
    portfolio: {
      balance: 1000000,
      equity: 1000150,
      leverage: 10,
      positions: [
        {
          id: 'pos-1',
          symbol,
          side: 'LONG' as const,
          source: 'AMT' as const,
          entryPrice: symbol.includes('CRUDEOIL') ? 6200 : 200,
          size: 1,
          stopLoss: symbol.includes('CRUDEOIL') ? 6150 : 195,
          takeProfit: symbol.includes('CRUDEOIL') ? 6300 : 215,
          pnl: symbol.includes('CRUDEOIL') ? 150 : 25,
          status: 'OPEN' as const,
          entryTime: '2026-08-05T09:15:00Z',
          currentPrice: symbol.includes('CRUDEOIL') ? 6210 : 205,
        },
      ],
      closedTrades: [],
    },
    amtAnalysis: {
      marketState: 'TRENDING_UP' as const,
      poc: symbol.includes('CRUDEOIL') ? 6205 : 203,
      valueAreaHigh: symbol.includes('CRUDEOIL') ? 6215 : 208,
      valueAreaLow: symbol.includes('CRUDEOIL') ? 6195 : 198,
      lvns: [6198, 6202],
      hvns: [6205],
      aggression: 0.65,
      setup: 'TREND_MODEL' as const,
      profile: [
        { price: 6200, volume: 500, buyVolume: 300, sellVolume: 200 },
        { price: 6205, volume: 800, buyVolume: 500, sellVolume: 300 },
      ],
      aggressivePrints: [],
      legProfile: [],
      legLvns: [],
      legPoc: 0,
      legVah: 0,
      legVal: 0,
      hasDisplacement: true,
      deltaNormalizedOption: 0.72,
      vwapUpper1: symbol.includes('CRUDEOIL') ? 6212 : 206,
      vwapLower1: symbol.includes('CRUDEOIL') ? 6198 : 200,
      vwapUpper2: symbol.includes('CRUDEOIL') ? 6220 : 210,
      vwapLower2: symbol.includes('CRUDEOIL') ? 6190 : 196,
      vwapDeviationSigmas: 1.2,
      isExtremeDeviation: false,
    },
    agentDecision: {
      direction: 'LONG' as const,
      role: 'SCANNING' as const,
      action: 'ENTER_NOW' as const,
      setup: 'TREND_MODEL' as const,
      reason: 'Breakout above VAH with displacement',
      modelLabel: 'TimesFM-SCANNING',
      regime: 'TRENDING',
      timing: 'ENTER_NOW',
      sizeFraction: 0.5,
      latencyUs: 0,
      rationale: 'Strong bullish setup confirmed by volume profile',
      confidence: 'High',
      confidenceScore: 0.82,
      source: 'AMT_RULE',
    },
    quantDecisionAnalysis: {
      approved: true,
      reason: 'TREND_MODEL',
      phase: 'SIGNAL',
      modelLabel: 'Triple-A',
      signal: {
        type: 'LONG',
        entry: symbol.includes('CRUDEOIL') ? 6210 : 205,
        sl: symbol.includes('CRUDEOIL') ? 6190 : 200,
        tp: symbol.includes('CRUDEOIL') ? 6300 : 215,
        rr: 2.0,
        modelLabel: 'Triple-A',
      },
      isAdvisory: false,
    },
    riskState: {
      halted: false,
      haltReason: '',
      consecutiveLosses: 0,
      dailyPnl: 150,
    },
    ltp: symbol.includes('CRUDEOIL') ? 6210 : 205,
    lastUpdate: Date.now(),
  }),

  // WS delta payload
  delta: (symbol: string, field: string, value: number) => ({
    _symbol: symbol,
    _type: 'delta' as const,
    [field]: value,
    lastUpdate: Date.now(),
  }),
};

// ---------------------------------------------------------------------------
// Transport harness setup / teardown
// ---------------------------------------------------------------------------

export function setupTransportHarness() {
  beforeEach(() => {
    wsInboundMessages.length = 0;
    wsOutboundMessages.length = 0;
    fetchInboundRequests.length = 0;
  });

  afterEach(() => {
    wsInboundMessages.length = 0;
    wsOutboundMessages.length = 0;
    fetchInboundRequests.length = 0;
  });
}

export function clearTransport() {
  wsInboundMessages.length = 0;
  wsOutboundMessages.length = 0;
  fetchInboundRequests.length = 0;
}

/**
 * Wait for pending microtasks + a small delay to let async WS open settle.
 * Used to synchronize test with mock WebSocket lifecycle.
 */
export async function flushTransport(delayMs = 20) {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

// ---------------------------------------------------------------------------
// DOM assertion helpers (for render tests)
// ---------------------------------------------------------------------------

export function assertTextInDocument(text: string, container?: Element) {
  const el = container?.querySelector(`[data-testid="${text}"]`) ?? document.body;
  const found = document.body.textContent?.includes(text) ?? false;
  expect(found).toBe(true);
  return found;
}

export function assertElementCount(selector: string, expected: number, container?: Element) {
  const nodes = (container ?? document).querySelectorAll(selector);
  expect(nodes.length).toBe(expected);
  return nodes;
}

// ---------------------------------------------------------------------------
// Mock fetch (used by useServerTradingSystem and REST calls)
// ---------------------------------------------------------------------------

export function installMockFetch() {
  const originalFetch = globalThis.fetch;

  // Only replace if not already mocked (idempotent)
  if (globalThis.fetch !== originalFetch) return;

  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const req = new Request(input as string, init);
    fetchInboundRequests.push(req);

    const url = typeof input === 'string' ? input : (input as Request).url;

    if (url.includes('/api/health')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockBackendResponses.health()),
        headers: new Headers({ 'content-type': 'application/json' }),
      } as Response);
    }

    if (url.includes('/api/system/config')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockBackendResponses.systemConfig()),
        headers: new Headers({ 'content-type': 'application/json' }),
      } as Response);
    }

    if (url.includes('/api/market/history/')) {
      const symbol = url.split('/').pop() ?? 'UNKNOWN';
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockBackendResponses.history(symbol)),
        headers: new Headers({ 'content-type': 'application/json' }),
      } as Response);
    }

    if (url.includes('/api/market/lot-size/')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            symbol: url.split('/').pop(),
            lotSize: 100,
          }),
        headers: new Headers({ 'content-type': 'application/json' }),
      } as Response);
    }

    // Default: empty success
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
      headers: new Headers({ 'content-type': 'application/json' }),
    } as Response);
  }) as typeof originalFetch;

  Object.defineProperty(global, 'fetch', {
    value: globalThis.fetch,
    writable: true,
    configurable: true,
  });
}

// ---------------------------------------------------------------------------
// Mock WebSocket global (used by useServerTradingSystem)
// ---------------------------------------------------------------------------

export function installMockWebSocket() {
  if ((globalThis as any).WebSocket instanceof Function) return; // already mocked

  (globalThis as any).WebSocket = HarnessWebSocket as any;
}

// Auto-install when this module loads (test setup runs before imports)
installMockFetch();
installMockWebSocket();
