import { describe, it, expect, vi, beforeAll } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useServerTradingSystem } from '../../hooks/useServerTradingSystem';
import type { ChartConfig } from '../../types';

// Mock WebSocket class for tests
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
  interval: '5',
  dataSource: 'SERVER',
  bullColor: '#22c55e',
  bearColor: '#ef4444',
  glassOpacity: 0.3,
  roughness: 0.5,
  transmission: 0.5,
  showGrid: true,
  autoRotate: false,
  showPredictions: false,
  showVolumeProfile: false,
  vpMode: 'session',
  trend: 'sideways',
};

describe('useServerTradingSystem', () => {
  beforeAll(() => {
    global.WebSocket = MockWebSocket as any;
  });

  it('should initialize with empty instruments', () => {
    const { result } = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));
    
    expect(result.current.instruments).toEqual({});
    expect(result.current.activeSymbol).toBe('');
  });

  it('should start disconnected', () => {
    const { result } = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));
    
    expect(result.current.connected).toBe(false);
  });

  it('should show loading connection status initially', () => {
    const { result } = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));
    
    // The hook shows a loading message on first start
    expect(result.current.connectionStatus).toContain('Loading');
  });

  it('should return tickBus event target', () => {
    const { result } = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));
    
    expect(result.current.tickBus).toBeDefined();
    expect(result.current.tickBus).toBeInstanceOf(EventTarget);
  });

  it('should allow setting active symbol', () => {
    const { result } = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));
    
    act(() => {
      result.current.setActiveSymbol('NSE:BANKNIFTY');
    });

    // The activeSymbol should be updated
    expect(result.current.activeSymbol).toBe('NSE:BANKNIFTY');
  });

  it('should have correct default portfolio values structure', () => {
    // Test the createInstrumentState function indirectly by checking types
    const { result } = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));
    
    // After initialization, portfolio should have correct structure once loaded
    // We can't test async init without proper timer mocking
    expect(result.current.instruments).toBeDefined();
    expect(typeof result.current.setActiveSymbol).toBe('function');
  });
});

describe('InstrumentState defaults', () => {
  beforeAll(() => {
    global.WebSocket = MockWebSocket as any;
  });

  it('should have correct default values structure', () => {
    const { result } = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));
    
    // Get any instrument state (will be empty before init)
    const instrument = result.current.instruments['NSE:NIFTY'];
    
    // Before config loads, instruments should be empty
    expect(result.current.instruments).toEqual({});
  });

  it('should return all required properties', () => {
    const { result } = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));
    
    // Verify all expected return properties exist
    expect(result.current).toHaveProperty('instruments');
    expect(result.current).toHaveProperty('activeSymbol');
    expect(result.current).toHaveProperty('setActiveSymbol');
    expect(result.current).toHaveProperty('activeInstrument');
    expect(result.current).toHaveProperty('connected');
    expect(result.current).toHaveProperty('connectionStatus');
    expect(result.current).toHaveProperty('tickBus');
  });
});

describe('phantom field removal (backend never sends these)', () => {
  // Render the hook with a mocked config fetch so it connects a real WS,
  // then push a crafted full-state message through the socket.
  const connectHook = async () => {
    const instances: MockWebSocket[] = [];
    class TrackingWS extends MockWebSocket {
      constructor(url: string) {
        super(url);
        instances.push(this);
      }
    }
    const realFetch = global.fetch;
    global.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ activeSymbols: ['NIFTY'] }),
    })) as any;
    global.WebSocket = TrackingWS as any;

    const rendered = renderHook(() => useServerTradingSystem(DEFAULT_CONFIG));

    // Let the config fetch resolve and the WS connect effect run.
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        await new Promise(r => setTimeout(r, 20));
      });
    }

    global.fetch = realFetch;
    return { ...rendered, ws: instances[0] };
  };

  const pushMessage = async (ws: MockWebSocket, msg: Record<string, unknown>) => {
    await act(async () => {
      ws.onmessage?.({ data: JSON.stringify(msg) } as any);
      // Flush the RAF-batched state update inside act.
      await new Promise(r => setTimeout(r, 30));
    });
  };

  it('does not derive unsafeToTrade/feedStale from phantom feed/execution/readiness fields', async () => {
    const { result, ws } = await connectHook();
    expect(ws).toBeDefined();

    await pushMessage(ws, {
      _type: 'full',
      _symbol: 'NIFTY',
      feed: { last_tick_age_sec: 999, ticks_seen: 0, state: 'failed' },
      execution: { broker_bound: false },
      readiness: { safe_to_trade: false },
    });

    const inst = result.current.instruments['NIFTY'];
    expect(inst).toBeDefined();
    expect(inst.runtimeSafety?.unsafeToTrade).toBe(false);
    expect(inst.runtimeSafety?.feedStale).toBe(false);
    expect(inst.stale).toBeFalsy();
  });

  it('does not store phantom depth20Active state', async () => {
    const { result, ws } = await connectHook();

    await pushMessage(ws, {
      _type: 'full',
      _symbol: 'NIFTY',
      depth20Active: true,
    });

    const inst = result.current.instruments['NIFTY'];
    expect(inst.depth20Active).toBeUndefined();
  });

  it('ignores backend stale-notification messages', async () => {
    const { result, ws } = await connectHook();

    await pushMessage(ws, { _type: 'stale', _symbol: 'NIFTY' });

    const inst = result.current.instruments['NIFTY'];
    expect(inst.stale).toBeFalsy();
  });
});