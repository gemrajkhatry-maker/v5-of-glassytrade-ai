import { describe, it, expect } from 'vitest';
import {
  transformToCandleData,
  transformToVolumeData,
  validateCandleData,
  getCandleStats,
  filterCandlesByTimeRange,
  getLastNCandles,
  getCandleBodySize,
  getCandleRange,
  isBullishCandle,
  getDefaultCandleConfig,
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
      // IST is UTC+5:30, so offset should be 19800 seconds
      const utcTime = new Date('2024-01-01T00:00:00Z').getTime() / 1000;
      expect(timestamp).toBe(utcTime + 19800);
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

  describe('transformToVolumeData', () => {
    it('transforms to volume histogram data', () => {
      const volumeData = transformToVolumeData(sampleData);
      expect(volumeData).toHaveLength(3);
      expect(volumeData[0].value).toBe(1000);
    });

    it('assigns bull color for bullish candles', () => {
      const volumeData = transformToVolumeData(sampleData, '#green', '#red');
      expect(volumeData[0].color).toBe('#green'); // close > open
    });

    it('assigns bear color for bearish candles', () => {
      const bearData = [
        { time: '2024-01-01T09:15:00Z', open: 50100, high: 50200, low: 50000, close: 50050, volume: 1000 },
      ] as any[];

      const volumeData = transformToVolumeData(bearData, '#green', '#red');
      expect(volumeData[0].color).toBe('#red'); // close < open
    });

    it('handles empty data', () => {
      const volumeData = transformToVolumeData([]);
      expect(volumeData).toHaveLength(0);
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

  describe('getCandleStats', () => {
    const candles: CandleDataPoint[] = [
      { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050, volume: 1000 },
      { time: 2000, open: 50050, high: 50150, low: 50000, close: 50100, volume: 1100 },
    ];

    it('calculates correct count', () => {
      const stats = getCandleStats(candles);
      expect(stats?.count).toBe(2);
    });

    it('calculates price range', () => {
      const stats = getCandleStats(candles);
      expect(stats?.priceRange.min).toBe(49950);
      expect(stats?.priceRange.max).toBe(50150);
    });

    it('calculates volume stats', () => {
      const stats = getCandleStats(candles);
      expect(stats?.volumeStats.total).toBe(2100);
      expect(stats?.volumeStats.average).toBe(1050);
    });

    it('counts bullish and bearish candles', () => {
      const stats = getCandleStats(candles);
      expect(stats?.bullishCount).toBe(2);
      expect(stats?.bearishCount).toBe(0);
    });

    it('returns null for empty data', () => {
      const stats = getCandleStats([]);
      expect(stats).toBeNull();
    });
  });

  describe('filterCandlesByTimeRange', () => {
    const candles: CandleDataPoint[] = [
      { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050 },
      { time: 2000, open: 50050, high: 50150, low: 50000, close: 50100 },
      { time: 3000, open: 50100, high: 50200, low: 50050, close: 50150 },
    ];

    it('filters candles within time range', () => {
      const filtered = filterCandlesByTimeRange(candles, 1500, 2500);
      expect(filtered).toHaveLength(1);
      expect(filtered[0].time).toBe(2000);
    });

    it('includes boundary times', () => {
      const filtered = filterCandlesByTimeRange(candles, 1000, 2000);
      expect(filtered).toHaveLength(2);
    });

    it('returns empty array when no candles in range', () => {
      const filtered = filterCandlesByTimeRange(candles, 5000, 6000);
      expect(filtered).toHaveLength(0);
    });
  });

  describe('getLastNCandles', () => {
    const candles: CandleDataPoint[] = [
      { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050 },
      { time: 2000, open: 50050, high: 50150, low: 50000, close: 50100 },
      { time: 3000, open: 50100, high: 50200, low: 50050, close: 50150 },
    ];

    it('returns last N candles', () => {
      const last2 = getLastNCandles(candles, 2);
      expect(last2).toHaveLength(2);
      expect(last2[0].time).toBe(2000);
      expect(last2[1].time).toBe(3000);
    });

    it('handles N larger than array length', () => {
      const last10 = getLastNCandles(candles, 10);
      expect(last10).toHaveLength(3);
    });

    it('handles empty array', () => {
      const last5 = getLastNCandles([], 5);
      expect(last5).toHaveLength(0);
    });
  });

  describe('getCandleBodySize', () => {
    it('calculates bullish body size', () => {
      const candle: CandleDataPoint = { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050 };
      expect(getCandleBodySize(candle)).toBe(50);
    });

    it('calculates bearish body size', () => {
      const candle: CandleDataPoint = { time: 1000, open: 50100, high: 50150, low: 50000, close: 50050 };
      expect(getCandleBodySize(candle)).toBe(50);
    });
  });

  describe('getCandleRange', () => {
    it('calculates candle range', () => {
      const candle: CandleDataPoint = { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050 };
      expect(getCandleRange(candle)).toBe(150);
    });
  });

  describe('isBullishCandle', () => {
    it('returns true for bullish candle', () => {
      const candle: CandleDataPoint = { time: 1000, open: 50000, high: 50100, low: 49950, close: 50050 };
      expect(isBullishCandle(candle)).toBe(true);
    });

    it('returns false for bearish candle', () => {
      const candle: CandleDataPoint = { time: 1000, open: 50100, high: 50150, low: 50000, close: 50050 };
      expect(isBullishCandle(candle)).toBe(false);
    });

    it('returns true for doji (close == open)', () => {
      const candle: CandleDataPoint = { time: 1000, open: 50000, high: 50100, low: 49950, close: 50000 };
      expect(isBullishCandle(candle)).toBe(true);
    });
  });

  describe('getDefaultCandleConfig', () => {
    it('returns default configuration', () => {
      const config = getDefaultCandleConfig();
      expect(config.bullColor).toBe('#00c896');
      expect(config.bearColor).toBe('#ff4757');
      expect(config.borderVisible).toBe(false);
    });

    it('accepts custom colors', () => {
      const config = getDefaultCandleConfig('#green', '#red');
      expect(config.bullColor).toBe('#green');
      expect(config.bearColor).toBe('#red');
      expect(config.wickUpColor).toBe('#green');
      expect(config.wickDownColor).toBe('#red');
    });
  });
});
