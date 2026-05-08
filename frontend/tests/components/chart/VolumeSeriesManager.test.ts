import { describe, it, expect } from 'vitest';
import {
  transformToVolumeData,
  getVolumeStats,
  validateVolumeData,
  filterVolumeByTimeRange,
  getLastNVolumePoints,
  detectVolumeSpikes,
  calculateVWAP,
  getVolumeSeriesConfig,
  VolumeDataPoint,
  DEFAULT_VOLUME_CONFIG,
  DEFAULT_VOLUME_COLORS,
} from '../../../components/chart/VolumeSeriesManager';

describe('VolumeSeriesManager', () => {
  const sampleOHLCV = [
    { time: '2024-01-01T09:15:00Z', open: 50000, high: 50100, low: 49950, close: 50050, volume: 1000 },
    { time: '2024-01-01T09:30:00Z', open: 50050, high: 50150, low: 50000, close: 50100, volume: 1100 },
    { time: '2024-01-01T09:45:00Z', open: 50100, high: 50200, low: 50050, close: 50050, volume: 1200 },
  ] as any[];

  const sampleVolumeData: VolumeDataPoint[] = [
    { time: 1000, value: 1000, color: 'rgba(0, 200, 150, 0.6)' },
    { time: 2000, value: 1100, color: 'rgba(0, 200, 150, 0.6)' },
    { time: 3000, value: 1200, color: 'rgba(255, 71, 87, 0.6)' },
  ];

  describe('transformToVolumeData', () => {
    it('transforms OHLCV to volume histogram data', () => {
      const volumeData = transformToVolumeData(sampleOHLCV);
      expect(volumeData).toHaveLength(3);
      expect(volumeData[0].value).toBe(1000);
    });

    it('assigns bull color for bullish candles', () => {
      const volumeData = transformToVolumeData(sampleOHLCV);
      expect(volumeData[0].color).toContain('0, 200, 150'); // close > open
    });

    it('assigns bear color for bearish candles', () => {
      const volumeData = transformToVolumeData(sampleOHLCV);
      expect(volumeData[2].color).toContain('255, 71, 87'); // close < open
    });

    it('handles empty data', () => {
      const volumeData = transformToVolumeData([]);
      expect(volumeData).toHaveLength(0);
    });

    it('sorts data by time', () => {
      const unsortedData = [
        { time: '2024-01-01T09:45:00Z', open: 50100, high: 50200, low: 50050, close: 50050, volume: 1200 },
        { time: '2024-01-01T09:15:00Z', open: 50000, high: 50100, low: 49950, close: 50050, volume: 1000 },
      ] as any[];

      const volumeData = transformToVolumeData(unsortedData);
      expect(volumeData[0].time).toBeLessThan(volumeData[1].time);
    });
  });

  describe('getVolumeStats', () => {
    it('calculates total volume', () => {
      const stats = getVolumeStats(sampleVolumeData);
      expect(stats?.totalVolume).toBe(3300);
    });

    it('calculates average volume', () => {
      const stats = getVolumeStats(sampleVolumeData);
      expect(stats?.averageVolume).toBe(1100);
    });

    it('finds max and min volume', () => {
      const stats = getVolumeStats(sampleVolumeData);
      expect(stats?.maxVolume).toBe(1200);
      expect(stats?.minVolume).toBe(1000);
    });

    it('returns null for empty data', () => {
      const stats = getVolumeStats([]);
      expect(stats).toBeNull();
    });
  });

  describe('validateVolumeData', () => {
    it('returns empty array for valid data', () => {
      const errors = validateVolumeData(sampleVolumeData);
      expect(errors).toHaveLength(0);
    });

    it('detects invalid timestamp', () => {
      const invalidData: any = [{ time: -1, value: 1000, color: 'red' }];
      const errors = validateVolumeData(invalidData);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('detects negative volume', () => {
      const invalidData: any = [{ time: 1000, value: -100, color: 'red' }];
      const errors = validateVolumeData(invalidData);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('detects duplicate timestamps', () => {
      const duplicateData: VolumeDataPoint[] = [
        { time: 1000, value: 1000, color: 'green' },
        { time: 1000, value: 1100, color: 'red' },
      ];
      const errors = validateVolumeData(duplicateData);
      expect(errors).toContain('Duplicate timestamps detected in volume data');
    });

    it('allows empty data', () => {
      const errors = validateVolumeData([]);
      expect(errors).toHaveLength(0);
    });
  });

  describe('filterVolumeByTimeRange', () => {
    it('filters data within time range', () => {
      const filtered = filterVolumeByTimeRange(sampleVolumeData, 1500, 2500);
      expect(filtered).toHaveLength(1);
      expect(filtered[0].time).toBe(2000);
    });

    it('includes boundary times', () => {
      const filtered = filterVolumeByTimeRange(sampleVolumeData, 1000, 2000);
      expect(filtered).toHaveLength(2);
    });

    it('returns empty array when no data in range', () => {
      const filtered = filterVolumeByTimeRange(sampleVolumeData, 5000, 6000);
      expect(filtered).toHaveLength(0);
    });
  });

  describe('getLastNVolumePoints', () => {
    it('returns last N points', () => {
      const last2 = getLastNVolumePoints(sampleVolumeData, 2);
      expect(last2).toHaveLength(2);
      expect(last2[0].time).toBe(2000);
      expect(last2[1].time).toBe(3000);
    });

    it('handles N larger than array length', () => {
      const last10 = getLastNVolumePoints(sampleVolumeData, 10);
      expect(last10).toHaveLength(3);
    });

    it('handles empty array', () => {
      const last5 = getLastNVolumePoints([], 5);
      expect(last5).toHaveLength(0);
    });
  });

  describe('detectVolumeSpikes', () => {
    it('detects unusually high volume', () => {
      const data: VolumeDataPoint[] = [
        { time: 1, value: 100, color: 'green' },
        { time: 2, value: 110, color: 'green' },
        { time: 3, value: 105, color: 'green' },
        { time: 4, value: 500, color: 'green' }, // Spike
      ];

      const spikes = detectVolumeSpikes(data, 2);
      expect(spikes).toHaveLength(1);
      expect(spikes[0].value).toBe(500);
    });

    it('returns empty for normal data', () => {
      const data: VolumeDataPoint[] = [
        { time: 1, value: 100, color: 'green' },
        { time: 2, value: 110, color: 'green' },
        { time: 3, value: 105, color: 'green' },
      ];

      const spikes = detectVolumeSpikes(data, 2);
      expect(spikes).toHaveLength(0);
    });

    it('returns empty for small datasets', () => {
      const data: VolumeDataPoint[] = [
        { time: 1, value: 100, color: 'green' },
      ];

      const spikes = detectVolumeSpikes(data, 2);
      expect(spikes).toHaveLength(0);
    });
  });

  describe('calculateVWAP', () => {
    it('calculates VWAP correctly', () => {
      const data = [
        { time: '1', high: 50100, low: 49950, close: 50050, volume: 1000 },
        { time: '2', high: 50150, low: 50000, close: 50100, volume: 1100 },
      ] as any[];

      const vwap = calculateVWAP(data);
      expect(vwap).toBeGreaterThan(49950);
      expect(vwap).toBeLessThan(50150);
    });

    it('returns 0 for empty data', () => {
      const vwap = calculateVWAP([]);
      expect(vwap).toBe(0);
    });
  });

  describe('getVolumeSeriesConfig', () => {
    it('returns default configuration', () => {
      const config = getVolumeSeriesConfig();
      expect(config.priceFormat.type).toBe('volume');
      expect(config.priceScaleId).toBe('');
      expect(config.scaleMargins.top).toBe(0.8);
      expect(config.scaleMargins.bottom).toBe(0);
    });

    it('accepts custom overrides', () => {
      const config = getVolumeSeriesConfig({
        priceScaleId: 'volume-scale',
        scaleMargins: { top: 0.7, bottom: 0.1 },
      });
      expect(config.priceScaleId).toBe('volume-scale');
      expect(config.scaleMargins.top).toBe(0.7);
      expect(config.scaleMargins.bottom).toBe(0.1);
    });
  });

  describe('constants', () => {
    it('has correct default volume config', () => {
      expect(DEFAULT_VOLUME_CONFIG.priceFormat.type).toBe('volume');
      expect(DEFAULT_VOLUME_CONFIG.scaleMargins.top).toBe(0.8);
    });

    it('has correct default volume colors', () => {
      expect(DEFAULT_VOLUME_COLORS.bullColor).toContain('0, 200, 150');
      expect(DEFAULT_VOLUME_COLORS.bearColor).toContain('255, 71, 87');
    });
  });
});
