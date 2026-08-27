/**
 * PHASE 5 — ingestion audit.
 *
 * Finding (recorded up front): the delta/full merge logic lives INLINE in
 * useServerTradingSystem's handleWsMessage (frontend/hooks/useServerTradingSystem.ts:336-562)
 * and is NOT exported. It is nonetheless testable through the real import path:
 * we boot the real hook with a mocked WebSocket and push the real backend
 * fixture frames through the production onmessage handler. No logic is
 * replicated — every assertion below runs the actual production code path.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { FRAMES, FIXTURE_SYMBOLS, connectRealHook, pushAllFrames } from './harness';

let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
});

describe('PHASE 5: ingestion of real backend WS frames', () => {
  it('every fixture frame parses and lands in state via the real WS handler', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    expect(ws).toBeDefined();
    // All frames are valid JSON by construction; type-guard the essentials.
    for (const f of FRAMES) {
      expect(typeof f._symbol).toBe('string');
      expect(f._symbol.length).toBeGreaterThan(0);
    }

    await pushAllFrames(ws, FRAMES);

    // No parse-error status surfaced by the hook.
    expect(result.current.connectionStatus).toBe('');

    // Every distinct _symbol produced exactly one instrument slice.
    expect(Object.keys(result.current.instruments).sort()).toEqual(
      [...FIXTURE_SYMBOLS].sort(),
    );
  });

  it('event ordering preserved: chart candles ascend by tick.time in frame order', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    await pushAllFrames(ws, FRAMES);

    for (const sym of FIXTURE_SYMBOLS) {
      const framesForSym = FRAMES.filter(f => f._symbol === sym);
      const inst = result.current.instruments[sym];
      expect(inst).toBeDefined();

      // One candle per frame tick — none dropped, none duplicated.
      expect(inst.data).toHaveLength(framesForSym.length);
      expect(inst.data.map((c: any) => c.time)).toEqual(
        framesForSym.map(f => f.tick.time),
      );

      // Strictly ascending timestamps (no stale reordering).
      const ms = inst.data.map((c: any) => new Date(c.time).getTime());
      for (let i = 1; i < ms.length; i++) {
        expect(ms[i]).toBeGreaterThan(ms[i - 1]);
      }

      // Last candle equals last frame's tick verbatim.
      expect(inst.data[inst.data.length - 1]).toEqual(framesForSym[framesForSym.length - 1].tick);
    }
  });

  it('symbol identity preserved end-to-end: frame._symbol becomes the exact state key', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    await pushAllFrames(ws, FRAMES);

    for (const sym of FIXTURE_SYMBOLS) {
      const inst = result.current.instruments[sym];
      // Key exists verbatim (no trimming/renaming/case-folding).
      expect(inst).toBeDefined();
      expect(inst.symbol).toBe(sym);

      // Payload fields stayed attached to their own symbol only.
      const framesForSym = FRAMES.filter(f => f._symbol === sym);
      const lastFrame = framesForSym[framesForSym.length - 1];
      expect(inst.data[inst.data.length - 1].close).toBe(lastFrame.tick.close);
      expect(inst.amtAnalysis).toEqual(lastFrame.amt);
      expect(inst.riskState).toEqual(lastFrame.riskState);
      expect(inst.orderBook).toEqual(lastFrame.depth);
    }

    // Cross-check: NIFTY's values never appear under BANKNIFTY's key or vice versa.
    const [niftySym, bankSym] = FIXTURE_SYMBOLS;
    const niftyLast = FRAMES.filter(f => f._symbol === niftySym).at(-1)!;
    const bankLast = FRAMES.filter(f => f._symbol === bankSym).at(-1)!;
    expect(result.current.instruments[niftySym].data.at(-1).close).not.toBe(bankLast.tick.close);
    expect(result.current.instruments[bankSym].data.at(-1).close).not.toBe(niftyLast.tick.close);
  });

  it('full snapshots populate inst.ltp / inst.oi (delta path already did)', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    await pushAllFrames(ws, FRAMES);

    const inst = result.current.instruments[FIXTURE_SYMBOLS[0]];
    const lastFrame = FRAMES.filter(f => f._symbol === FIXTURE_SYMBOLS[0]).at(-1)!;
    // Backend explicitly sent non-zero ltp/oi on every frame; the full-state
    // merge path (useServerTradingSystem.ts:542-543) carries them via
    // state.ltp ?? inst.ltp, so downstream code does not fall back to
    // lastCandle.close. This is the regression check for the earlier FINDING
    // where full snapshots silently dropped ltp/oi.
    expect(lastFrame.ltp).toBeGreaterThan(0);
    expect(inst.ltp).toBe(lastFrame.ltp);
    expect(inst.oi).toBe(lastFrame.oi);
  });
});
