import {
  detectExchange,
  sessionHoursForExchange,
  computeConfluence,
  buildProfileSummary,
} from '../utils/profileInfo';
import { AMTAnalysis } from '../types';

const baseAmt = (overrides: Partial<AMTAnalysis> = {}): AMTAnalysis => ({
  marketState: 'BALANCED',
  poc: 100,
  valueAreaHigh: 105,
  valueAreaLow: 95,
  lvns: [],
  hvns: [],
  aggression: 0,
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

describe('detectExchange', () => {
  it('maps MCX underlyings to MCX', () => {
    for (const s of ['CRUDEOIL 17 AUG 7950 CALL', 'GOLDM 28 AUG 152000 PUT', 'SILVERM 24 AUG 233000 PUT', 'NATURALGAS 25 AUG 300 CALL', 'COPPER 29 AUG 810 CALL']) {
      expect(detectExchange(s)).toBe('MCX');
    }
  });
  it('maps NSE underlyings to NSE', () => {
    for (const s of ['NIFTY 18 AUG 24550 CALL', 'BANKNIFTY 27 AUG 61000 PE', 'FINNIFTY 28 AUG 23500 CE']) {
      expect(detectExchange(s)).toBe('NSE');
    }
  });
  it('defaults unknown symbols to NSE', () => {
    expect(detectExchange('SYM 1 JAN 100 CALL')).toBe('NSE');
  });
});

describe('sessionHoursForExchange', () => {
  it('uses 09:00 open for MCX', () => {
    expect(sessionHoursForExchange('MCX').open).toBe('09:00');
  });
  it('uses 09:15 open for NSE', () => {
    expect(sessionHoursForExchange('NSE').open).toBe('09:15');
  });
});

describe('computeConfluence', () => {
  it('flags confluence within 0.1%', () => {
    expect(computeConfluence(100, 100.05)).toBe('CONFLUENCE');
    expect(computeConfluence(100, 100.09)).toBe('CONFLUENCE');
  });
  it('flags divergence beyond 0.5%', () => {
    expect(computeConfluence(100, 100.6)).toBe('DIVERGENCE');
    expect(computeConfluence(100, 98)).toBe('DIVERGENCE');
  });
  it('returns NEUTRAL in between', () => {
    expect(computeConfluence(100, 100.3)).toBe('NEUTRAL');
  });
  it('returns null without a leg POC', () => {
    expect(computeConfluence(100, 0)).toBeNull();
    expect(computeConfluence(0, 100)).toBeNull();
  });
});

describe('buildProfileSummary', () => {
  it('renders session profile with session hours for MCX', () => {
    const s = buildProfileSummary(baseAmt({ poc: 103.93, valueAreaHigh: 105.04, valueAreaLow: 94.61 }), 'session', 'CRUDEOIL 17 AUG 7950 CALL');
    expect(s.mode).toBe('session');
    expect(s.exchange).toBe('MCX');
    expect(s.hours).toBe('09:00-23:30 IST');
    expect(s.poc).toBeCloseTo(103.93);
    expect(s.vah).toBeCloseTo(105.04);
    expect(s.val).toBeCloseTo(94.61);
  });

  it('uses 09:15 for NSE session', () => {
    const s = buildProfileSummary(baseAmt(), 'session', 'NIFTY 18 AUG 24550 CALL');
    expect(s.hours).toBe('09:15-15:30 IST');
  });

  it('renders leg profile from leg fields', () => {
    const s = buildProfileSummary(baseAmt({ legPoc: 103.75, legVah: 105, legVal: 103.3 }), 'leg', 'NIFTY 18 AUG 24550 CALL');
    expect(s.mode).toBe('leg');
    expect(s.poc).toBeCloseTo(103.75);
    expect(s.vah).toBeCloseTo(105);
    expect(s.val).toBeCloseTo(103.3);
  });

  it('computes confluence badge in combined mode', () => {
    const s = buildProfileSummary(baseAmt({ poc: 100, legPoc: 100.05 }), 'combined', 'NIFTY 18 AUG 24550 CALL');
    expect(s.confluence).toBe('CONFLUENCE');
  });

  it('returns null for off mode', () => {
    expect(buildProfileSummary(baseAmt(), 'off', 'NIFTY 18 AUG 24550 CALL')).toBeNull();
  });

  it('returns null without AMT data', () => {
    expect(buildProfileSummary(null, 'session', 'NIFTY 18 AUG 24550 CALL')).toBeNull();
  });
});
