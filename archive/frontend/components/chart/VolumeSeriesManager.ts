import { OHLCData } from '../../types';
import { IST_OFFSET_SECONDS } from '../../constants';

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

export interface VolumeColorConfig {
  bullColor: string;
  bearColor: string;
  bullAlpha?: number;
  bearAlpha?: number;
}

/**
 * IST timezone offset in seconds (UTC+5:30)
 */
const IST_OFFSET = IST_OFFSET_SECONDS;

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

