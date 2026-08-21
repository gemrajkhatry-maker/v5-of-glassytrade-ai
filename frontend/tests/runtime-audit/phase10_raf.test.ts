/**
 * PHASE 10.6 — RAF queue backpressure audit.
 *
 * Drives the REAL useServerTradingSystem hook: pushes 15 WS frames in ONE
 * JS turn (no awaits between) so pendingUpdatesRef exceeds
 * MAX_RAF_QUEUE_SIZE=10, then flushes the RAF batch and counts which
 * symbols' updates actually landed in React state.
 *
 * Expected finding (useServerTradingSystem.ts ~114-117): when the queue
 * length >10 the splice keeps only MAX-2=8 oldest + pushes the new one —
 * older updaters are silently DROPPED, so their analytics deltas never
 * reach state and no counter/warning is emitted.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { act } from '@testing-library/react';
import { connectRealHook } from './harness';

let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
});

describe('PHASE 10: RAF batcher drop behavior', () => {
  it('silently drops queued updaters once the queue exceeds maxRafQueueSize=10', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    const N = 15; // > MAX_RAF_QUEUE_SIZE (10)
    // Each frame targets its own symbol with a unique ltp marker so we can
    // count exactly which updaters survived the splice.
    const symbols = Array.from({ length: N }, (_, i) => `NSE:RAFTEST${i}`);

    await act(async () => {
      for (let i = 0; i < N; i++) {
        ws.onmessage?.({
          data: JSON.stringify({
            _type: 'delta',
            _symbol: symbols[i],
            ltp: 1000 + i,
          }),
        } as any);
        // NO await — all 15 land in the same JS turn / same RAF window.
      }
      // Flush the RAF callback inside the act scope.
      await new Promise(r => setTimeout(r, 50));
    });

    const applied = symbols.filter(
      s => result.current.instruments[s]?.ltp !== undefined,
    );
    const dropped = symbols.filter(s => !applied.includes(s));

    console.log(
      `[raf] pushed=${N} applied=${applied.length} dropped=${dropped.length}` +
        `\n[raf] dropped symbols: ${dropped.join(', ')}`,
    );

    // FINDING: not all 15 updates survive. Prove the silent drop by execution.
    expect(applied.length).toBeLessThan(N);
    expect(dropped.length).toBeGreaterThan(0);
    // The OLDEST updates are the ones dropped (splice keeps the tail).
    expect(dropped).toContain(symbols[0]);
  });
});
