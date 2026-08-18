import { computeThreeA, ThreeAScore } from '../utils/threeA';
import { AMTAnalysis } from '../types';

const baseAmt = (overrides: Partial<AMTAnalysis> = {}): AMTAnalysis => ({
  marketState: 'BALANCED',
  poc: 100,
  valueAreaHigh: 105,
  valueAreaLow: 95,
  lvns: [99, 98],
  hvns: [],
  aggression: 1.0,
  setup: null,
  profile: [],
  aggressivePrints: [],
  legProfile: [],
  legLvns: [],
  legPoc: 0,
  legVah: 0,
  legVal: 0,
  hasDisplacement: false,
  ...overrides,
});

describe('computeThreeA', () => {
  it('returns a full-zeros score for null input', () => {
    const s = computeThreeA(null);
    expect(s).toEqual({
      auction: false, area: false, action: false, score: 0, verdict: 'SKIP',
    });
  });

  describe('Auction (market state)', () => {
    it('passes on BALANCED', () => {
      expect(computeThreeA(baseAmt()).auction).toBe(true);
    });
    it('passes on IMBALANCED', () => {
      expect(computeThreeA(baseAmt({ marketState: 'IMBALANCED' })).auction).toBe(true);
    });
    it('fails on DEAD', () => {
      expect(computeThreeA(baseAmt({ marketState: 'DEAD' })).auction).toBe(false);
    });
    it('fails when market state is missing', () => {
      expect(computeThreeA(baseAmt({ marketState: '' })).auction).toBe(false);
    });
  });

  describe('Area (location at a level)', () => {
    it('passes with a POC and an LVN present', () => {
      expect(computeThreeA(baseAmt()).area).toBe(true);
    });
    it('passes with a POC and an LVN play', () => {
      expect(computeThreeA(baseAmt({
        lvns: [],
        lvnPlay: { lvn_price: 99, direction: 'UP', target: 103, velocity_ratio: 1.2, has_rejection: false, has_delta_flip: false },
      })).area).toBe(true);
    });
    it('fails with no POC', () => {
      expect(computeThreeA(baseAmt({ poc: 0, lvns: [] })).area).toBe(false);
    });
    it('fails with no levels at all', () => {
      expect(computeThreeA(baseAmt({ lvns: [], lvnPlay: null })).area).toBe(false);
    });
  });

  describe('Action (aggression / order flow)', () => {
    it('passes on high aggression score', () => {
      expect(computeThreeA(baseAmt({ aggression: 2.5 })).action).toBe(true);
    });
    it('passes on absorption side', () => {
      expect(computeThreeA(baseAmt({ aggression: 0, absorptionSide: 'BUY' })).action).toBe(true);
    });
    it('passes on strong CVD slope', () => {
      expect(computeThreeA(baseAmt({ aggression: 0, cvdSlope: 2.0 })).action).toBe(true);
    });
    it('passes on aggressive prints', () => {
      expect(computeThreeA(baseAmt({
        aggression: 0,
        aggressivePrints: [{ price: 100, time: 't', side: 'BUY', volume: 500, delta: 10 }],
      })).action).toBe(true);
    });
    it('fails with no aggression evidence', () => {
      expect(computeThreeA(baseAmt({ aggression: 0.5 })).action).toBe(false);
    });
  });

  describe('Score and verdict', () => {
    it('gives score 3 and ENTER when all pass', () => {
      const s = computeThreeA(baseAmt({ aggression: 2.5 }));
      expect(s.score).toBe(3);
      expect(s.verdict).toBe('ENTER');
    });
    it('gives score 2 and MONITOR when two pass', () => {
      const s = computeThreeA(baseAmt({ aggression: 0.5 }));
      expect(s.score).toBe(2);
      expect(s.verdict).toBe('MONITOR');
    });
    it('gives score 1 and SKIP when only one passes', () => {
      // DEAD auction + no action evidence; only the Area (POC/LVN) passes.
      const s = computeThreeA(baseAmt({ marketState: 'DEAD', aggression: 0 }));
      expect(s.auction).toBe(false);
      expect(s.area).toBe(true);
      expect(s.action).toBe(false);
      expect(s.score).toBe(1);
      expect(s.verdict).toBe('SKIP');
    });
    it('gives score 0 and SKIP when none pass', () => {
      const s = computeThreeA(baseAmt({ marketState: 'DEAD', poc: 0, lvns: [], aggression: 0 }));
      expect(s.score).toBe(0);
      expect(s.verdict).toBe('SKIP');
    });
  });
});
