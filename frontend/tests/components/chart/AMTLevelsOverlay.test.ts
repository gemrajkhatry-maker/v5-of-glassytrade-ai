import { describe, it, expect } from 'vitest';
import {
  generateAMTPriceLines,
  calculateVWAPColor,
  PriceLineConfig,
  AMTLevelsOverlayOptions,
} from '../../../components/chart/AMTLevelsOverlay';
import { AMTAnalysis, OHLCData } from '../../../types';

describe('AMTLevelsOverlay', () => {
  const defaultAmt: AMTAnalysis = {
    poc: 50000,
    valueAreaHigh: 50500,
    valueAreaLow: 49500,
    sessionVwap: 50000,
    vwapUpper1: 50200,
    vwapLower1: 49800,
    vwapUpper2: 50400,
    vwapLower2: 49600,
    ibHigh: 50300,
    ibLow: 49700,
    breakDirection: 'UP',
    lvns: [50100, 50200],
    hvns: [49900, 50000],
    priorVah: 50600,
    priorVal: 49400,
    priorPoc: 50000,
    legPoc: 50050,
    legVah: 50550,
    legVal: 49450,
    profile: [],
    aggressivePrints: [],
  } as any;

  const defaultOptions: AMTLevelsOverlayOptions = {
    mode: 'STANDARD',
    showVolumeProfile: true,
    vpMode: 'combined',
  };

  const defaultData: OHLCData[] = [
    { time: '2024-01-01', open: 50000, high: 50100, low: 49900, close: 50050, volume: 1000, vwap: 50000 },
    { time: '2024-01-02', open: 50050, high: 50150, low: 49950, close: 50100, volume: 1100, vwap: 50025 },
    { time: '2024-01-03', open: 50100, high: 50200, low: 50000, close: 50150, volume: 1200, vwap: 50050 },
    { time: '2024-01-04', open: 50150, high: 50250, low: 50050, close: 50200, volume: 1300, vwap: 50075 },
    { time: '2024-01-05', open: 50200, high: 50300, low: 50100, close: 50250, volume: 1400, vwap: 50100 },
  ] as any;

  describe('generateAMTPriceLines - Session Levels', () => {
    it('generates S-POC line with correct style', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'session' });
      const pocLine = lines.find(l => l.title === 'S-POC');
      
      expect(pocLine).toBeDefined();
      expect(pocLine?.price).toBe(50000);
      expect(pocLine?.color).toBe('#facc15');
      expect(pocLine?.lineWidth).toBe(2);
      expect(pocLine?.lineStyle).toBe('Solid');
    });

    it('generates S-VAH line with correct style', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'session' });
      const vahLine = lines.find(l => l.title === 'S-VAH');
      
      expect(vahLine).toBeDefined();
      expect(vahLine?.price).toBe(50500);
      expect(vahLine?.color).toBe('#3b82f6');
      expect(vahLine?.lineStyle).toBe('Dashed');
    });

    it('generates S-VAL line with correct style', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'session' });
      const valLine = lines.find(l => l.title === 'S-VAL');
      
      expect(valLine).toBeDefined();
      expect(valLine?.price).toBe(49500);
      expect(valLine?.color).toBe('#3b82f6');
      expect(valLine?.lineStyle).toBe('Dashed');
    });

    it('generates LVN lines with amber dotted style', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'session' });
      const lvnLines = lines.filter(l => l.title === 'LVN');
      
      expect(lvnLines).toHaveLength(2);
      expect(lvnLines[0].price).toBe(50100);
      expect(lvnLines[1].price).toBe(50200);
      expect(lvnLines[0].color).toBe('#fb923c');
      expect(lvnLines[0].lineStyle).toBe('Dotted');
    });

    it('generates HVN lines with emerald dashed style', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'session' });
      const hvnLines = lines.filter(l => l.title === 'HVN');
      
      expect(hvnLines).toHaveLength(2);
      expect(hvnLines[0].price).toBe(49900);
      expect(hvnLines[1].price).toBe(50000);
      expect(hvnLines[0].color).toBe('#34d399');
      expect(hvnLines[0].lineStyle).toBe('Dashed');
    });

    it('generates IB HIGH with break direction indicator', () => {
      const lines = generateAMTPriceLines(
        { ...defaultAmt, breakDirection: 'UP' },
        { ...defaultOptions, vpMode: 'session' }
      );
      const ibHighLine = lines.find(l => l.title.includes('IB HIGH'));
      
      expect(ibHighLine).toBeDefined();
      expect(ibHighLine?.price).toBe(50300);
      expect(ibHighLine?.title).toBe('IB HIGH [BROKEN ↑]');
    });

    it('generates IB LOW with break direction indicator', () => {
      const lines = generateAMTPriceLines(
        { ...defaultAmt, breakDirection: 'DOWN' },
        { ...defaultOptions, vpMode: 'session' }
      );
      const ibLowLine = lines.find(l => l.title.includes('IB LOW'));
      
      expect(ibLowLine).toBeDefined();
      expect(ibLowLine?.price).toBe(49700);
      expect(ibLowLine?.title).toBe('IB LOW [BROKEN ↓]');
    });
  });

  describe('generateAMTPriceLines - VWAP', () => {
    it('generates VWAP line with default cyan color', () => {
      const lines = generateAMTPriceLines(defaultAmt, defaultOptions, []);
      const vwapLine = lines.find(l => l.title === 'VWAP');
      
      expect(vwapLine).toBeDefined();
      expect(vwapLine?.color).toBe('#06b6d4');
    });

    it('generates VWAP with green color when slope is rising', () => {
      const risingData: OHLCData[] = [
        { time: '1', vwap: 50000 },
        { time: '2', vwap: 50050 },
        { time: '3', vwap: 50100 },
        { time: '4', vwap: 50150 },
        { time: '5', vwap: 50200 },
      ] as any;
      
      const lines = generateAMTPriceLines(defaultAmt, defaultOptions, risingData);
      const vwapLine = lines.find(l => l.title === 'VWAP ↑');
      
      expect(vwapLine).toBeDefined();
      expect(vwapLine?.color).toBe('#22c55e');
    });

    it('generates VWAP with red color when slope is declining', () => {
      const decliningData: OHLCData[] = [
        { time: '1', vwap: 50200 },
        { time: '2', vwap: 50150 },
        { time: '3', vwap: 50100 },
        { time: '4', vwap: 50050 },
        { time: '5', vwap: 50000 },
      ] as any;
      
      const lines = generateAMTPriceLines(defaultAmt, defaultOptions, decliningData);
      const vwapLine = lines.find(l => l.title === 'VWAP ↓');
      
      expect(vwapLine).toBeDefined();
      expect(vwapLine?.color).toBe('#ef4444');
    });

    it('generates +1σ and -1σ bands', () => {
      const lines = generateAMTPriceLines(defaultAmt, defaultOptions);
      const upper1 = lines.find(l => l.title === '+1σ');
      const lower1 = lines.find(l => l.title === '-1σ');
      
      expect(upper1).toBeDefined();
      expect(upper1?.price).toBe(50200);
      expect(upper1?.lineStyle).toBe('Dashed');
      
      expect(lower1).toBeDefined();
      expect(lower1?.price).toBe(49800);
      expect(lower1?.lineStyle).toBe('Dashed');
    });

    it('generates +2σ and -2σ FADE bands', () => {
      const lines = generateAMTPriceLines(defaultAmt, defaultOptions);
      const upper2 = lines.find(l => l.title === '+2σ FADE');
      const lower2 = lines.find(l => l.title === '-2σ FADE');
      
      expect(upper2).toBeDefined();
      expect(upper2?.price).toBe(50400);
      expect(upper2?.lineStyle).toBe('Dotted');
      
      expect(lower2).toBeDefined();
      expect(lower2?.price).toBe(49600);
      expect(lower2?.lineStyle).toBe('Dotted');
    });
  });

  describe('generateAMTPriceLines - Prior Day Levels', () => {
    it('generates prior VAH/VAL/POC lines', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'session' });
      
      const priorVAH = lines.find(l => l.title === 'Prior VAH');
      const priorVAL = lines.find(l => l.title === 'Prior VAL');
      const priorPOC = lines.find(l => l.title === 'Prior POC');
      
      expect(priorVAH).toBeDefined();
      expect(priorVAH?.price).toBe(50600);
      expect(priorVAH?.color).toBe('#6b7280');
      
      expect(priorVAL).toBeDefined();
      expect(priorVAL?.price).toBe(49400);
      
      expect(priorPOC).toBeDefined();
      expect(priorPOC?.price).toBe(50000);
    });
  });

  describe('generateAMTPriceLines - Leg Levels', () => {
    it('generates leg POC/VAH/VAL in leg mode', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'leg' });
      
      expect(lines.find(l => l.title === 'L-POC')).toBeDefined();
      expect(lines.find(l => l.title === 'L-VAH')).toBeDefined();
      expect(lines.find(l => l.title === 'L-VAL')).toBeDefined();
    });

    it('generates leg levels in combined mode', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'combined' });
      
      // Should have both session and leg levels
      expect(lines.find(l => l.title === 'S-POC')).toBeDefined();
      expect(lines.find(l => l.title === 'L-POC')).toBeDefined();
    });

    it('does not generate leg levels in session mode', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, vpMode: 'session' });
      
      expect(lines.find(l => l.title?.startsWith('L-'))).toBeUndefined();
    });
  });

  describe('generateAMTPriceLines - Mode Filtering', () => {
    it('returns empty array when showVolumeProfile is false', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, showVolumeProfile: false });
      expect(lines).toHaveLength(0);
    });

    it('generates lines in STANDARD mode', () => {
      const lines = generateAMTPriceLines(defaultAmt, { ...defaultOptions, mode: 'STANDARD' });
      expect(lines.length).toBeGreaterThan(0);
    });
  });

  describe('generateAMTPriceLines - Edge Cases', () => {
    it('handles missing POC gracefully', () => {
      const amtWithoutPOC = { ...defaultAmt, poc: undefined };
      const lines = generateAMTPriceLines(amtWithoutPOC, { ...defaultOptions, vpMode: 'session' });
      
      expect(lines.find(l => l.title === 'S-POC')).toBeUndefined();
    });

    it('handles zero POC value', () => {
      const amtWithZeroPOC = { ...defaultAmt, poc: 0 };
      const lines = generateAMTPriceLines(amtWithZeroPOC, { ...defaultOptions, vpMode: 'session' });
      
      expect(lines.find(l => l.title === 'S-POC')).toBeUndefined();
    });

    it('handles empty LVN/HVN arrays', () => {
      const amtWithoutLVN = { ...defaultAmt, lvns: [], hvns: [] };
      const lines = generateAMTPriceLines(amtWithoutLVN, { ...defaultOptions, vpMode: 'session' });
      
      expect(lines.filter(l => l.title === 'LVN')).toHaveLength(0);
      expect(lines.filter(l => l.title === 'HVN')).toHaveLength(0);
    });

    it('handles missing prior day levels', () => {
      const amtWithoutPrior = { ...defaultAmt, priorVah: undefined, priorVal: undefined, priorPoc: undefined };
      const lines = generateAMTPriceLines(amtWithoutPrior, { ...defaultOptions, vpMode: 'session' });
      
      expect(lines.find(l => l.title === 'Prior VAH')).toBeUndefined();
      expect(lines.find(l => l.title === 'Prior VAL')).toBeUndefined();
      expect(lines.find(l => l.title === 'Prior POC')).toBeUndefined();
    });
  });

  describe('calculateVWAPColor', () => {
    it('returns default cyan when insufficient data', () => {
      const result = calculateVWAPColor([]);
      expect(result.color).toBe('#06b6d4');
      expect(result.label).toBe('VWAP');
    });

    it('returns green for rising VWAP', () => {
      const data = [
        { vwap: 50000 },
        { vwap: 50050 },
        { vwap: 50100 },
        { vwap: 50150 },
        { vwap: 50200 },
      ] as any;
      
      const result = calculateVWAPColor(data);
      expect(result.color).toBe('#22c55e');
      expect(result.label).toBe('VWAP ↑');
    });

    it('returns red for declining VWAP', () => {
      const data = [
        { vwap: 50200 },
        { vwap: 50150 },
        { vwap: 50100 },
        { vwap: 50050 },
        { vwap: 50000 },
      ] as any;
      
      const result = calculateVWAPColor(data);
      expect(result.color).toBe('#ef4444');
      expect(result.label).toBe('VWAP ↓');
    });

    it('returns default for flat VWAP', () => {
      const data = [
        { vwap: 50000 },
        { vwap: 50001 },
        { vwap: 50000 },
        { vwap: 50001 },
        { vwap: 50000 },
      ] as any;
      
      const result = calculateVWAPColor(data);
      expect(result.color).toBe('#06b6d4');
      expect(result.label).toBe('VWAP');
    });
  });
});
