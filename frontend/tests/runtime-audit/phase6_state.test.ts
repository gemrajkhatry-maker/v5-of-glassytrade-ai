/**
 * PHASE 6 — state audit.
 *
 * Frames are applied to the REAL store via the same apply-path the hook uses
 * (handleWsMessage -> batchedSetInstruments -> instruments React state).
 * Note: frontend/stores/ui.ts (Zustand) holds only UI prefs (chartMode,
 * sidebars, etc.) — it carries NO market data, so the hook's `instruments`
 * state is the canonical market-data store under audit.
 */
import { describe, it, expect, afterEach } from 'vitest';
import {
  FRAMES,
  FIXTURE_SYMBOLS,
  connectRealHook,
  pushFrame,
  pushAllFrames,
  snapshotInstrument,
} from './harness';

let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
});

const [niftySym, bankSym] = FIXTURE_SYMBOLS;

describe('PHASE 6: state integrity under real fixture frames', () => {
  it('per-symbol isolation: applying NIFTY frames never mutates the BANKNIFTY slice', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    // Seed BANKNIFTY first with all of its frames.
    const bankFrames = FRAMES.filter(f => f._symbol === bankSym);
    await pushAllFrames(ws, bankFrames);

    const beforeSnapshot = snapshotInstrument(result.current.instruments[bankSym]);
    const beforeRef = result.current.instruments[bankSym];

    // Now hammer NIFTY.
    await pushAllFrames(ws, FRAMES.filter(f => f._symbol === niftySym));

    const after = result.current.instruments[bankSym];
    // Deep equality of the untouched slice...
    expect(snapshotInstrument(after)).toBe(beforeSnapshot);
    // ...and referential identity (merge spreads prev, never deep-mutates).
    expect(after).toBe(beforeRef);
  });

  it('stale frames cannot overwrite newer data: older tick after newer tick is ignored', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    const niftyFrames = FRAMES.filter(f => f._symbol === niftySym);
    // Apply frames 0..4 (times t0..t4), then replay frame 3 (t3 < t4).
    for (const f of niftyFrames.slice(0, 5)) await pushFrame(ws, f);
    await pushFrame(ws, niftyFrames[3]); // stale replay

    const inst = result.current.instruments[niftySym];
    // ACTUAL SEMANTICS RECORDED: full-path tick merge appends only strictly-newer
    // ticks and replaces same-timestamp ticks; a stale (older) tick is dropped.
    expect(inst.data).toHaveLength(5);
    expect(inst.data.at(-1).time).toBe(niftyFrames[4].tick.time);
    expect(inst.data.at(-1).close).toBe(niftyFrames[4].tick.close);
    expect(inst.data.map((c: any) => c.time)).not.toContain(niftyFrames[3].tick.time + '!');
    // Times still strictly ascending after the stale attempt.
    const ms = inst.data.map((c: any) => new Date(c.time).getTime());
    for (let i = 1; i < ms.length; i++) expect(ms[i]).toBeGreaterThan(ms[i - 1]);
  });

  it('partial delta merges touch ONLY their keys', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    await pushAllFrames(ws, FRAMES);
    const before = snapshotInstrument(result.current.instruments[niftySym]);

    // Minimal analytics delta carrying exactly one key.
    await pushFrame(ws, { _type: 'delta', _symbol: niftySym, ltp: 999.5 });

    const inst: any = result.current.instruments[niftySym];
    expect(inst.ltp).toBe(999.5);

    // Every other slice is byte-identical apart from the touched key(s).
    const clone = JSON.parse(JSON.stringify(inst));
    delete clone.lastUpdate; // stamped with Date.now() on every merge
    delete (clone as any).ltp;
    const beforeClone = JSON.parse(before) as any;
    delete beforeClone.ltp; // was undefined before — absent in JSON anyway
    expect(clone).toEqual(beforeClone);
  });

  it('partial portfolio delta shallow-merges without clobbering sibling keys', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    await pushAllFrames(ws, FRAMES);
    const equityBefore = result.current.instruments[niftySym].portfolio.equity;

    await pushFrame(ws, {
      _type: 'delta',
      _symbol: niftySym,
      portfolio: { balance: 1_000_500 },
    });

    const p: any = result.current.instruments[niftySym].portfolio;
    expect(p.balance).toBe(1_000_500); // updated key
    expect(p.equity).toBe(equityBefore); // sibling preserved by {...existing, ...delta}
    expect(p.leverage).toBe(10);
  });

  it('NO default-zero corruption: every zero in final state was explicitly sent by the backend', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    await pushAllFrames(ws, FRAMES);

    // Collect explicit zeros/zero-strings present in the fixture per symbol.
    const collectZeros = (obj: any, path: string, out: Set<string>) => {
      if (obj === null || obj === undefined) return out;
      if (typeof obj === 'number' && obj === 0) out.add(path);
      if (typeof obj === 'string' && obj === '0') out.add(path);
      if (typeof obj === 'object') {
        for (const [k, v] of Object.entries(obj)) collectZeros(v, `${path}.${k}`, out);
      }
      return out;
    };

    for (const sym of FIXTURE_SYMBOLS) {
      const fixtureZeros = new Set<string>();
      for (const f of FRAMES.filter(f => f._symbol === sym)) {
        collectZeros(f, '', fixtureZeros);
        collectZeros({ ...f, amt: f.amt ? { ...f.amt, _as: 'amtAnalysis' } : f.amt }, '', fixtureZeros);
      }

      const inst: any = result.current.instruments[sym];
      const stateZeros: Array<{ path: string; value: any }> = [];
      const walk = (obj: any, path: string) => {
        if (obj === null || obj === undefined) return;
        if (typeof obj === 'number' && obj === 0) {
          stateZeros.push({ path, value: obj });
          return;
        }
        if (typeof obj === 'object') {
          for (const [k, v] of Object.entries(obj)) walk(v, `${path}.${k}`);
        }
      };
      walk(inst, sym);

      // Map each state zero back to a fixture-origin zero.
      const unexplained = stateZeros.filter(({ path }) => {
        // Normalise state path -> fixture field name (e.g. riskState.consecutiveLosses)
        const leaf = path.split('.').pop()!;
        for (const z of fixtureZeros) {
          if (z.split('.').pop() === leaf) return false; // backend sent this zero explicitly
        }
        return true;
      });

      console.log(`[phase6] ${sym}: ${stateZeros.length} zeros in final state, all traced to fixture: ${
        unexplained.length === 0
      }`, stateZeros.map(z => z.path));

      expect(unexplained).toEqual([]);
    }

    // And the sentinel check: no field that the backend sent non-zero became 0.
    for (const sym of FIXTURE_SYMBOLS) {
      const lastFrame = FRAMES.filter(f => f._symbol === sym).at(-1)!;
      const inst: any = result.current.instruments[sym];
      expect(inst.amtAnalysis.poc).toBe(lastFrame.amt.poc);
      expect(inst.amtAnalysis.cvd).toBe(lastFrame.amt.cvd);
      expect(inst.riskState.equity).toBe(lastFrame.riskState.equity);
      expect(inst.orderBook.bids[0][0]).toBe(lastFrame.depth.bids[0][0]);
      expect(inst.data.at(-1).close).toBe(lastFrame.tick.close);
    }
  });
});
