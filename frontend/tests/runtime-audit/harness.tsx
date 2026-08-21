import { renderHook, act } from '@testing-library/react';
import { vi } from 'vitest';
import { useServerTradingSystem } from '../../hooks/useServerTradingSystem';
import type { ChartConfig } from '../../types';
import fixtureFrames from '../../../runtime_audit/fixtures/ws_payloads.json';

export const FRAMES = fixtureFrames as Array<Record<string, any>>;

export const FIXTURE_SYMBOLS = Array.from(new Set(FRAMES.map(f => f._symbol)));

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: ((error: Event) => void) | null = null;

  constructor(public url: string) {}

  send(data: string) {}
  close(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code });
  }
}

const DEFAULT_CONFIG: ChartConfig = {
  symbol: 'NSE:NIFTY',
  bullColor: '#22c55e',
  bearColor: '#ef4444',
  showVolumeProfile: false,
  vpMode: 'session',
};

/**
 * Boots the REAL useServerTradingSystem hook with a mocked config fetch
 * (activeSymbols taken from the real fixture) and a mocked WebSocket,
 * then returns the live socket so raw backend frames can be pushed through
 * the production handleWsMessage -> batchedSetInstruments path.
 */
export const connectRealHook = async () => {
  const instances: MockWebSocket[] = [];
  class TrackingWS extends MockWebSocket {
    constructor(url: string) {
      super(url);
      instances.push(this);
    }
  }
  const realFetch = global.fetch;
  const realWs = global.WebSocket;
  global.fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ activeSymbols: FIXTURE_SYMBOLS }),
  })) as any;
  global.WebSocket = TrackingWS as any;

  const rendered = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));

  // Let the config fetch resolve and the WS connect effect run.
  for (let i = 0; i < 3; i++) {
    await act(async () => {
      await new Promise(r => setTimeout(r, 20));
    });
  }

  const restore = () => {
    global.fetch = realFetch;
    global.WebSocket = realWs;
  };

  return { ...rendered, ws: instances[0], restore };
};

/** Push one raw frame (as the backend would over WS) and flush the RAF batch. */
export const pushFrame = async (
  ws: MockWebSocket,
  frame: Record<string, unknown>,
) => {
  await act(async () => {
    ws.onmessage?.({ data: JSON.stringify(frame) } as any);
    await new Promise(r => setTimeout(r, 30));
  });
};

export const pushAllFrames = async (
  ws: MockWebSocket,
  frames: Array<Record<string, unknown>>,
) => {
  for (const f of frames) await pushFrame(ws, f);
};

/**
 * Deterministic snapshot of an instrument slice: strips wall-clock fields
 * (lastUpdate) that the merge stamps with Date.now().
 */
export const snapshotInstrument = (inst: any): string => {
  if (!inst) return 'null';
  const clone = JSON.parse(JSON.stringify(inst));
  delete clone.lastUpdate;
  return JSON.stringify(clone);
};

export const snapshotInstruments = (instruments: Record<string, any>): string =>
  JSON.stringify(
    Object.fromEntries(
      Object.entries(instruments).map(([k, v]) => [k, JSON.parse(snapshotInstrument(v))]),
    ),
  );
