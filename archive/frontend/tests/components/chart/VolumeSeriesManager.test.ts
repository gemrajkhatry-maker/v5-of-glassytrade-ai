import { describe, it, expect } from 'vitest';
import {
  transformToVolumeData,
  validateVolumeData,
  VolumeDataPoint,
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

  describe('constants', () => {
    it('has correct default volume colors', () => {
      expect(DEFAULT_VOLUME_COLORS.bullColor).toContain('0, 200, 150');
      expect(DEFAULT_VOLUME_COLORS.bearColor).toContain('255, 71, 87');
    });
  });
});
