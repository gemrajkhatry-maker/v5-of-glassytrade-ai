import { describe, it, expect } from 'vitest';
import { IST_OFFSET_SECONDS } from '../../../constants';
import {
  transformToCandleData,
  validateCandleData,
  toISTTimestamp,
  CandleDataPoint,
} from '../../../components/chart/CandleSeriesManager';

describe('CandleSeriesManager', () => {
  const sampleData = [
    { time: '2024-01-01T09:15:00Z', open: 50000, high: 50100, low: 49950, close: 50050, volume: 1000 },
    { time: '2024-01-01T09:30:00Z', open: 50050, high: 50150, low: 50000, close: 50100, volume: 1100 },
    { time: '2024-01-01T09:45:00Z', open: 50100, high: 50200, low: 50050, close: 50150, volume: 1200 },
  ] as any[];

  describe('toISTTimestamp', () => {
    it('converts UTC to IST correctly', () => {
      const timestamp = toISTTimestamp('2024-01-01T00:00:00Z');
      // IST is UTC+5:30, so offset should be IST_OFFSET_SECONDS
      const utcTime = new Date('2024-01-01T00:00:00Z').getTime() / 1000;
      expect(timestamp).toBe(utcTime + IST_OFFSET_SECONDS);
    });
  });

  describe('transformToCandleData', () => {
    it('transforms OHLCData to candle format', () => {
      const candles = transformToCandleData(sampleData);
      expect(candles).toHaveLength(3);
      expect(candles[0].open).toBe(50000);
      expect(candles[0].high).toBe(50100);
      expect(candles[0].low).toBe(49950);
      expect(candles[0].close).toBe(50050);
    });

    it('sorts candles by time', () => {
      const unsortedData = [
        { time: '2024-01-01T09:45:00Z', open: 50100, high: 50200, low: 50050, close: 50150, volume: 1200 },
        { time: '2024-01-01T09:15:00Z', open: 50000, high: 50100, low: 49950, close: 50050, volume: 1000 },
      ] as any[];

      const candles = transformToCandleData(unsortedData);
      expect(candles[0].time).toBeLessThan(candles[1].time);
    });

    it('handles empty data', () => {
      const candles = transformToCandleData([]);
      expect(candles).toHaveLength(0);
    });

    it('includes volume in transformed data', () => {
      const candles = transformToCandleData(sampleData);
      expect(candles[0].volume).toBe(1000);
      expect(candles[1].volume).toBe(1100);
    });
  });

  describe('validateCandleData', () => {
    it('returns valid for correct candle data', () => {
      const candles: CandleDataPoint[] = [
        { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050 },
      ];

      const result = validateCandleData(candles);
      expect(result.isValid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it('detects missing fields', () => {
      const candles: any = [
        { time: 1000, open: 50000 },
      ];

      const result = validateCandleData(candles);
      expect(result.isValid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('detects invalid timestamp', () => {
      const candles: any = [
        { time: -1, open: 50000, high: 50100, low: 49950, close: 50050 },
      ];

      const result = validateCandleData(candles);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('detects high < low', () => {
      const candles: CandleDataPoint[] = [
        { time: 1000, open: 50000, high: 49900, low: 50100, close: 50050 },
      ];

      const result = validateCandleData(candles);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('warns about open > high', () => {
      const candles: CandleDataPoint[] = [
        { time: 1000, open: 50200, high: 50100, low: 49950, close: 50050 },
      ];

      const result = validateCandleData(candles);
      expect(result.warnings.length).toBeGreaterThan(0);
    });

    it('warns about zero volume', () => {
      const candles: CandleDataPoint[] = [
        { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050, volume: 0 },
      ];

      const result = validateCandleData(candles);
      expect(result.warnings.length).toBeGreaterThan(0);
    });

    it('detects negative prices', () => {
      const candles: any = [
        { time: 1000, open: -50000, high: 50100, low: 49950, close: 50050 },
      ];

      const result = validateCandleData(candles);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('warns about duplicate timestamps', () => {
      const candles: CandleDataPoint[] = [
        { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050 },
        { time: 1000, open: 50050, high: 50150, low: 50000, close: 50100 },
      ];

      const result = validateCandleData(candles);
      expect(result.warnings.length).toBeGreaterThan(0);
    });

    it('handles empty data as valid', () => {
      const result = validateCandleData([]);
      expect(result.isValid).toBe(true);
    });
  });
});
