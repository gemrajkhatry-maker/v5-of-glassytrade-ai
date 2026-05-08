import { describe, it, expect } from 'vitest';
import {
  formatPriceLines,
  formatVolume,
  calculateTradePnL,
  formatPnL,
  formatTime,
  generateAMTAnnotations,
  buildCrosshairTooltip,
  validateCrosshairData,
  CrosshairData,
  TradeInfo,
} from '../../../components/chart/CrosshairManager';

describe('CrosshairManager', () => {
  const sampleData: CrosshairData = {
    time: '2024-01-01 09:15:00',
    open: 50000,
    high: 50100,
    low: 49950,
    close: 50050,
    volume: 1000,
    vwap: 50025,
  };

  describe('formatPriceLines', () => {
    it('formats OHLC prices', () => {
      const lines = formatPriceLines(sampleData);
      expect(lines).toContain('O: 50000.00');
      expect(lines).toContain('H: 50100.00');
      expect(lines).toContain('L: 49950.00');
      expect(lines).toContain('C: 50050.00');
    });

    it('includes VWAP when available', () => {
      const lines = formatPriceLines(sampleData);
      expect(lines).toContain('VWAP: 50025.00');
    });

    it('excludes VWAP when not available', () => {
      const dataWithoutVwap: CrosshairData = { ...sampleData, vwap: undefined };
      const lines = formatPriceLines(dataWithoutVwap);
      expect(lines).not.toContain(expect.stringContaining('VWAP'));
    });
  });

  describe('formatVolume', () => {
    it('formats small volumes', () => {
      expect(formatVolume(100)).toBe('100');
    });

    it('formats thousands', () => {
      expect(formatVolume(1500)).toBe('1.50K');
    });

    it('formats millions', () => {
      expect(formatVolume(2500000)).toBe('2.50M');
    });

    it('formats exact thousands', () => {
      expect(formatVolume(1000)).toBe('1.00K');
    });
  });

  describe('calculateTradePnL', () => {
    it('calculates profit for LONG trade', () => {
      const trade: TradeInfo = {
        side: 'LONG',
        entryPrice: 50000,
        currentPrice: 50100,
        entryTime: '2024-01-01 09:15:00',
      };
      expect(calculateTradePnL(trade)).toBe(100);
    });

    it('calculates loss for LONG trade', () => {
      const trade: TradeInfo = {
        side: 'LONG',
        entryPrice: 50000,
        currentPrice: 49900,
        entryTime: '2024-01-01 09:15:00',
      };
      expect(calculateTradePnL(trade)).toBe(-100);
    });

    it('calculates profit for SHORT trade', () => {
      const trade: TradeInfo = {
        side: 'SHORT',
        entryPrice: 50000,
        currentPrice: 49900,
        entryTime: '2024-01-01 09:15:00',
      };
      expect(calculateTradePnL(trade)).toBe(100);
    });

    it('calculates loss for SHORT trade', () => {
      const trade: TradeInfo = {
        side: 'SHORT',
        entryPrice: 50000,
        currentPrice: 50100,
        entryTime: '2024-01-01 09:15:00',
      };
      expect(calculateTradePnL(trade)).toBe(-100);
    });
  });

  describe('formatPnL', () => {
    it('formats positive PnL with + sign', () => {
      expect(formatPnL(100)).toBe('+100.00');
    });

    it('formats negative PnL with - sign', () => {
      expect(formatPnL(-100)).toBe('-100.00');
    });

    it('formats zero PnL', () => {
      expect(formatPnL(0)).toBe('+0.00');
    });
  });

  describe('formatTime', () => {
    it('formats timestamp to HH:MM:SS', () => {
      // 2024-01-01 09:15:30 UTC
      const timestamp = 1704100530;
      const formatted = formatTime(timestamp);
      expect(formatted).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    });

    it('pads hours with zero', () => {
      // Early morning UTC
      const timestamp = 1704067200; // Around 00:00 UTC
      const formatted = formatTime(timestamp);
      expect(formatted).toMatch(/^00:\d{2}:\d{2}$/);
    });
  });

  describe('generateAMTAnnotations', () => {
    const amtLevels = {
      poc: 50000,
      valueAreaHigh: 50050,
      valueAreaLow: 49950,
      sessionVwap: 50025,
    };

    it('generates POC annotation', () => {
      const annotations = generateAMTAnnotations(50050, amtLevels);
      expect(annotations.length).toBeGreaterThan(0);
      expect(annotations[0]).toContain('POC');
    });

    it('generates VAH annotation', () => {
      const annotations = generateAMTAnnotations(50050, amtLevels);
      expect(annotations.some(a => a.includes('VAH'))).toBe(true);
    });

    it('generates VAL annotation', () => {
      const annotations = generateAMTAnnotations(49950, amtLevels);
      expect(annotations.some(a => a.includes('VAL'))).toBe(true);
    });

    it('generates VWAP annotation', () => {
      const annotations = generateAMTAnnotations(50025, amtLevels);
      expect(annotations.some(a => a.includes('VWAP'))).toBe(true);
    });

    it('shows price difference from levels', () => {
      const annotations = generateAMTAnnotations(50100, amtLevels);
      expect(annotations[0]).toContain('+100.00'); // 50100 - 50000
    });

    it('handles missing levels', () => {
      const partialLevels = { poc: 50000 };
      const annotations = generateAMTAnnotations(50050, partialLevels);
      expect(annotations).toHaveLength(1);
    });
  });

  describe('buildCrosshairTooltip', () => {
    it('builds complete tooltip data', () => {
      const tooltip = buildCrosshairTooltip(sampleData);
      expect(tooltip.timeLabel).toBe(sampleData.time);
      expect(tooltip.priceLines.length).toBeGreaterThan(0);
      expect(tooltip.volumeLabel).toBe('1.00K');
    });

    it('includes AMT annotations when provided', () => {
      const amtLevels = { poc: 50000 };
      const tooltip = buildCrosshairTooltip(sampleData, amtLevels);
      expect(tooltip.amtAnnotations.length).toBeGreaterThan(0);
    });

    it('includes PnL label for active trade', () => {
      const trade: TradeInfo = {
        side: 'LONG',
        entryPrice: 50000,
        currentPrice: 50050,
        entryTime: '2024-01-01 09:15:00',
      };
      const tooltip = buildCrosshairTooltip(sampleData, undefined, trade);
      expect(tooltip.pnlLabel).toContain('PnL');
    });

    it('excludes PnL label when no active trade', () => {
      const tooltip = buildCrosshairTooltip(sampleData);
      expect(tooltip.pnlLabel).toBeUndefined();
    });
  });

  describe('validateCrosshairData', () => {
    it('returns empty array for valid data', () => {
      const errors = validateCrosshairData(sampleData);
      expect(errors).toHaveLength(0);
    });

    it('detects missing time', () => {
      const invalidData: any = { ...sampleData, time: undefined };
      const errors = validateCrosshairData(invalidData);
      expect(errors).toContain('Missing time');
    });

    it('detects missing prices', () => {
      const invalidData: any = { ...sampleData, open: undefined };
      const errors = validateCrosshairData(invalidData);
      expect(errors).toContain('Missing open price');
    });

    it('detects high < low', () => {
      const invalidData: CrosshairData = { ...sampleData, high: 49900, low: 50100 };
      const errors = validateCrosshairData(invalidData);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('detects open > high', () => {
      const invalidData: CrosshairData = { ...sampleData, open: 50200, high: 50100 };
      const errors = validateCrosshairData(invalidData);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('detects close < low', () => {
      const invalidData: CrosshairData = { ...sampleData, close: 49900, low: 49950 };
      const errors = validateCrosshairData(invalidData);
      expect(errors.length).toBeGreaterThan(0);
    });
  });
});
