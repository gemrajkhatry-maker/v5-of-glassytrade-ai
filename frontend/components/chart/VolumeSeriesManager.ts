import { OHLCData } from '../../types';

/**
 * VolumeSeriesManager - Data transformation for volume histogram series
 * 
 * Transforms OHLCV data into volume histogram format with proper
 * coloring and IST timezone conversion.
 * 
 * Benefits:
 * - 100% testable (pure functions)
 * - Separates volume logic from chart rendering
 * - Easy to validate volume data
 * - Consistent timezone handling
 */

export interface VolumeDataPoint {
  time: number;
  value: number;
  color: string;
}

export interface VolumeSeriesConfig {
  priceFormat: { type: 'volume' };
  priceScaleId: string;
  scaleMargins: {
    top: number;
    bottom: number;
  };
}

export interface VolumeColorConfig {
  bullColor: string;
  bearColor: string;
  bullAlpha?: number;
  bearAlpha?: number;
}

/**
 * IST timezone offset in seconds (UTC+5:30)
 */
const IST_OFFSET = 19800;

/**
 * Default volume series configuration
 */
export const DEFAULT_VOLUME_CONFIG: VolumeSeriesConfig = {
  priceFormat: { type: 'volume' },
  priceScaleId: '',
  scaleMargins: {
    top: 0.8,
    bottom: 0,
  },
};

/**
 * Default volume colors (institutional style)
 */
export const DEFAULT_VOLUME_COLORS: VolumeColorConfig = {
  bullColor: 'rgba(0, 200, 150, 0.6)',
  bearColor: 'rgba(255, 71, 87, 0.6)',
  bullAlpha: 0.6,
  bearAlpha: 0.6,
};

/**
 * Transform OHLCData to volume histogram data points
 * 
 * @param data - Raw OHLCV data
 * @param colors - Color configuration
 * @returns Array of volume data points with colors
 */
export function transformToVolumeData(
  data: OHLCData[],
  colors: VolumeColorConfig = DEFAULT_VOLUME_COLORS
): VolumeDataPoint[] {
  if (!data || data.length === 0) {
    return [];
  }

  // Sort by time to ensure chronological order
  const sortedData = [...data].sort((a, b) =>
    new Date(a.time).getTime() - new Date(b.time).getTime()
  );

  return sortedData.map(d => {
    const isBullish = d.close >= d.open;
    return {
      time: new Date(d.time as string).getTime() / 1000 + IST_OFFSET,
      value: d.volume,
      color: isBullish ? colors.bullColor : colors.bearColor,
    };
  });
}

/**
 * Get volume statistics
 * 
 * @param data - Volume data points
 * @returns Statistical summary
 */
export function getVolumeStats(data: VolumeDataPoint[]) {
  if (!data || data.length === 0) {
    return null;
  }

  const values = data.map(d => d.value);
  const totalVolume = values.reduce((a, b) => a + b, 0);

  return {
    count: data.length,
    totalVolume,
    averageVolume: totalVolume / data.length,
    maxVolume: Math.max(...values),
    minVolume: Math.min(...values),
    bullishVolume: data
      .filter(d => d.color.includes('0, 200, 150') || d.color.includes('green'))
      .reduce((a, b) => a + b.value, 0),
    bearishVolume: data
      .filter(d => d.color.includes('255, 71, 87') || d.color.includes('red'))
      .reduce((a, b) => a + b.value, 0),
  };
}

/**
 * Validate volume data integrity
 * 
 * @param data - Volume data points
 * @returns Array of validation errors (empty if valid)
 */
export function validateVolumeData(data: VolumeDataPoint[]): string[] {
  const errors: string[] = [];

  if (!data || data.length === 0) {
    return errors; // Empty is valid
  }

  data.forEach((point, index) => {
    if (!point.time || point.time <= 0) {
      errors.push(`Volume point ${index}: Invalid timestamp`);
    }
    if (point.value === undefined || point.value === null) {
      errors.push(`Volume point ${index}: Missing volume value`);
    }
    if (point.value < 0) {
      errors.push(`Volume point ${index}: Negative volume (${point.value})`);
    }
    if (!point.color) {
      errors.push(`Volume point ${index}: Missing color`);
    }
  });

  // Check for duplicate timestamps
  const timestamps = data.map(d => d.time);
  const uniqueTimestamps = new Set(timestamps);
  if (uniqueTimestamps.size < timestamps.length) {
    errors.push('Duplicate timestamps detected in volume data');
  }

  return errors;
}

/**
 * Filter volume data by time range
 * 
 * @param data - Volume data points
 * @param startTime - Start timestamp
 * @param endTime - End timestamp
 * @returns Filtered volume data within time range
 */
export function filterVolumeByTimeRange(
  data: VolumeDataPoint[],
  startTime: number,
  endTime: number
): VolumeDataPoint[] {
  return data.filter(d => d.time >= startTime && d.time <= endTime);
}

/**
 * Get last N volume data points
 * 
 * @param data - Volume data points
 * @param count - Number of points to retrieve
 * @returns Last N volume data points
 */
export function getLastNVolumePoints(data: VolumeDataPoint[], count: number): VolumeDataPoint[] {
  if (!data || data.length === 0) {
    return [];
  }
  return data.slice(-Math.min(count, data.length));
}

/**
 * Detect volume spikes (unusually high volume)
 * 
 * Uses a one-sided robust z-score based on the median absolute deviation
 * (MAD). A plain mean/std is inflated by the spike itself — a single huge
 * bar pushes the standard deviation up so much that nothing looks unusual
 * anymore. MAD is resilient to that inflation.
 * 
 * @param data - Volume data points
 * @param threshold - Robust z-score threshold (default: 2)
 * @returns Array of spike data points
 */
export function detectVolumeSpikes(
  data: VolumeDataPoint[],
  threshold: number = 2
): VolumeDataPoint[] {
  if (!data || data.length < 3) {
    return [];
  }

  const values = data.map(d => d.value);

  // Guard against non-numeric data — otherwise NaN would silently disable
  // the entire detection (median/MAD become NaN).
  if (values.some(v => !Number.isFinite(v))) {
    return [];
  }

  // Median of the data
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 0
      ? (sorted[mid - 1] + sorted[mid]) / 2
      : sorted[mid];

  // Median absolute deviation
  const deviations = values
    .map(v => Math.abs(v - median))
    .sort((a, b) => a - b);
  const midDev = Math.floor(deviations.length / 2);
  const mad =
    deviations.length % 2 === 0
      ? (deviations[midDev - 1] + deviations[midDev]) / 2
      : deviations[midDev];

  if (mad <= 0) {
    // All values identical (or only one unique value) — nothing to flag.
    return [];
  }

  // 0.6745 normalizes MAD so `threshold` behaves like a z-score.
  // Only flag HIGH volume (one-sided): low-volume dips are not spikes.
  const madSigma = 0.6745 * mad;
  return data.filter(d => (d.value - median) / madSigma > threshold);
}

/**
 * Calculate volume-weighted average price (VWAP) from OHLCV data
 * 
 * @param data - OHLCV data
 * @returns VWAP value
 */
export function calculateVWAP(data: OHLCData[]): number {
  if (!data || data.length === 0) {
    return 0;
  }

  let cumulativeVP = 0;
  let cumulativeVolume = 0;

  data.forEach(d => {
    const typicalPrice = (d.high + d.low + d.close) / 3;
    cumulativeVP += typicalPrice * d.volume;
    cumulativeVolume += d.volume;
  });

  return cumulativeVolume > 0 ? cumulativeVP / cumulativeVolume : 0;
}

/**
 * Get volume series configuration for TradingView
 * 
 * @param customConfig - Optional custom configuration overrides
 * @returns Volume series configuration
 */
export function getVolumeSeriesConfig(
  customConfig?: Partial<VolumeSeriesConfig>
): VolumeSeriesConfig {
  return {
    ...DEFAULT_VOLUME_CONFIG,
    ...customConfig,
    scaleMargins: {
      ...DEFAULT_VOLUME_CONFIG.scaleMargins,
      ...customConfig?.scaleMargins,
    },
  };
}
