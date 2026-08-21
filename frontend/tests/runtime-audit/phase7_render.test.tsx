/**
 * PHASE 7 — render audit.
 *
 * Component chosen: MarketSidebar (frontend/components/MarketSidebar.tsx) —
 * DOM-renderable, consumes the verified `instruments` state directly
 * (one SymbolCard per symbol, price derived from inst.ltp ?? lastCandle.close).
 * ChartScene is deliberately avoided (lightweight-charts canvas).
 *
 * State is produced by the REAL hook fed with the REAL fixture frames —
 * no hand-built fixtures for the render assertions.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import MarketSidebar from '../../components/MarketSidebar';
import {
  FRAMES,
  FIXTURE_SYMBOLS,
  connectRealHook,
  pushAllFrames,
  pushFrame,
} from './harness';

let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
  render && screen;
});

const [niftySym, bankSym] = FIXTURE_SYMBOLS;

/** Expected displayed change% exactly as SymbolCard computes it. */
const expectedPctText = (inst: any): string => {
  const lastCandle = inst.data[inst.data.length - 1];
  const prevCandle = inst.data[inst.data.length - 2];
  const price = inst.ltp ?? (lastCandle?.close || 0);
  const prevPrice = prevCandle?.close || price;
  const percentChange =
    price > 0 && prevPrice > 0 ? ((price - prevPrice) / prevPrice) * 100 : 0;
  return `${percentChange >= 0 ? '+' : ''}${percentChange.toFixed(1)}%`;
};

const getRow = (sym: string) => {
  // shortSymbol("NIFTY 27 AUG 25000 CALL") -> name "NIFTY 25000", tag CE
  const parts = sym.split(' ');
  const shortName = `${parts[0]} ${parts[parts.length - 2]}`;
  return screen.getByText(shortName).closest('button')!;
};

describe('PHASE 7: render of real components from verified state', () => {
  it('renders one row per symbol with correct count and names', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;
    await pushAllFrames(ws, FRAMES);

    render(
      <MarketSidebar
        instruments={result.current.instruments}
        activeSymbol={niftySym}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText('2 of 2')).toBeInTheDocument();
    expect(screen.getByText('NIFTY 25000')).toBeInTheDocument();
    expect(screen.getByText('BANKNIFTY 55000')).toBeInTheDocument();
    // Exactly two symbol-card buttons.
    const rows = screen.getAllByRole('button').filter(b => b.querySelector('span'));
    expect(getRow(niftySym)).toBeDefined();
    expect(getRow(bankSym)).toBeDefined();
  });

  it('displayed values match state exactly (change% derived from merged candles)', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;
    await pushAllFrames(ws, FRAMES);

    render(
      <MarketSidebar
        instruments={result.current.instruments}
        activeSymbol={niftySym}
        onSelect={() => {}}
      />,
    );

    for (const sym of FIXTURE_SYMBOLS) {
      const row = getRow(sym);
      const expected = expectedPctText(result.current.instruments[sym]);
      expect(row.textContent).toContain(expected);
    }
  });

  it('no cross-symbol leakage: BANKNIFTY values never appear in the NIFTY row', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;
    await pushAllFrames(ws, FRAMES);

    render(
      <MarketSidebar
        instruments={result.current.instruments}
        activeSymbol={niftySym}
        onSelect={() => {}}
      />,
    );

    const niftyRow = getRow(niftySym);
    const bankRow = getRow(bankSym);
    const bankInst = result.current.instruments[bankSym];
    const niftyInst = result.current.instruments[niftySym];

    const bankPct = expectedPctText(bankInst);
    const niftyPct = expectedPctText(niftyInst);

    expect(within(niftyRow).getByText(niftyPct)).toBeTruthy();
    expect(niftyRow.textContent).not.toContain('BANKNIFTY');
    expect(niftyRow.textContent).not.toContain('55000');
    if (bankPct !== niftyPct) {
      expect(niftyRow.textContent).not.toContain(bankPct);
    }

    expect(within(bankRow).getByText(bankPct)).toBeTruthy();
    // "BANKNIFTY" legitimately contains "NIFTY" — assert no STANDALONE NIFTY token.
    expect(bankRow.textContent).not.toMatch(/(^|[^A-Z])NIFTY/);
    expect(bankRow.textContent).not.toContain('25000');
  });

  it('re-renders when state changes: newer frame updates the displayed value', async () => {
    const { result, ws, restore } = await connectRealHook();
    cleanup = restore;

    // Feed all but the final NIFTY frame first.
    const niftyFrames = FRAMES.filter(f => f._symbol === niftySym);
    await pushAllFrames(ws, [...FRAMES.filter(f => f._symbol === bankSym), ...niftyFrames.slice(0, -1)]);

    const { rerender } = render(
      <MarketSidebar
        instruments={result.current.instruments}
        activeSymbol={niftySym}
        onSelect={() => {}}
      />,
    );
    const beforeText = getRow(niftySym).textContent;

    // Push the final (newer) NIFTY frame and re-render with fresh state.
    await pushFrame(ws, niftyFrames.at(-1)!);
    rerender(
      <MarketSidebar
        instruments={result.current.instruments}
        activeSymbol={niftySym}
        onSelect={() => {}}
      />,
    );

    const afterText = getRow(niftySym).textContent;
    expect(afterText).not.toBe(beforeText);
    expect(afterText).toContain(expectedPctText(result.current.instruments[niftySym]));
  });
});
