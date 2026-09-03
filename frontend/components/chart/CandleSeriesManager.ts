import { OHLCData } from '../../types';
import { IST_OFFSET_SECONDS } from '../../constants';

/**
 * CandleSeriesManager - Pure data transformation for candlestick series
 * 
 * Transforms OHLCV data into TradingView Lightweight Charts format,
 * handles data validation, sorting, and IST timezone conversion.
 * 
 * Benefits:
 * - 100% testable (pure functions)
 * - Separates data logic from chart rendering
 * - Easy to validate candle data integrity
 * - Handles timezone conversions consistently
 */

export interface CandleDataPoint {
  time: number; // Unix timestamp
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface CandleValidationResult {
  isValid: boolean;
  errors: string[];
  warnings: string[];
}

/**
 * IST timezone offset in seconds (UTC+5:30)
 */
const IST_OFFSET = IST_OFFSET_SECONDS;

/**
 * Convert timestamp to IST timezone
 * 
 * @param timeStr - ISO timestamp string
 * @returns Unix timestamp in IST
 */
export function toISTTimestamp(timeStr: string | number): number {
  if (typeof timeStr === 'number') {
    if (!Number.isFinite(timeStr) || timeStr <= 0) return 0;
    const sec = timeStr > 1e11 ? Math.floor(timeStr / 1000) : timeStr;
    return sec + IST_OFFSET;
  }
  if (!timeStr) return 0;
  const parsed = new Date(timeStr).getTime();
  if (isNaN(parsed) || parsed <= 0) return 0;
  return Math.floor(parsed / 1000) + IST_OFFSET;
}

/**
 * Transform OHLCData array to TradingView candle format
 * 
 * @param data - Raw OHLCV data
 * @returns Array of candle data points sorted by time
 */
export function transformToCandleData(data: OHLCData[]): CandleDataPoint[] {
  if (!data || data.length === 0) {
    return [];
  }

  // Sort by time to ensure chronological order
  const sortedData = [...data].sort((a, b) => 
    new Date(a.time).getTime() - new Date(b.time).getTime()
  );

  return sortedData.map(d => ({
    time: toISTTimestamp(d.time as string),
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
    volume: d.volume,
  }));
}

/**
 * Validate candle data integrity
 * 
 * @param candles - Array of candle data points
 * @returns Validation result with errors and warnings
 */
export function validateCandleData(candles: CandleDataPoint[]): CandleValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!candles || candles.length === 0) {
    return { isValid: true, errors: [], warnings: ['Empty candle data'] };
  }

  candles.forEach((candle, index) => {
    // Check required fields
    if (!candle.time || candle.time <= 0) {
      errors.push(`Candle ${index}: Invalid timestamp`);
    }
    if (candle.open === undefined || candle.open === null) {
      errors.push(`Candle ${index}: Missing open price`);
    }
    if (candle.high === undefined || candle.high === null) {
      errors.push(`Candle ${index}: Missing high price`);
    }
    if (candle.low === undefined || candle.low === null) {
      errors.push(`Candle ${index}: Missing low price`);
    }
    if (candle.close === undefined || candle.close === null) {
      errors.push(`Candle ${index}: Missing close price`);
    }

    // Validate price relationships
    if (candle.high !== undefined && candle.low !== undefined) {
      if (candle.high < candle.low) {
        errors.push(`Candle ${index}: High (${candle.high}) < Low (${candle.low})`);
      }
    }

    if (candle.open !== undefined && candle.high !== undefined) {
      if (candle.open > candle.high) {
        warnings.push(`Candle ${index}: Open (${candle.open}) > High (${candle.high})`);
      }
    }

    if (candle.open !== undefined && candle.low !== undefined) {
      if (candle.open < candle.low) {
        warnings.push(`Candle ${index}: Open (${candle.open}) < Low (${candle.low})`);
      }
    }

    if (candle.close !== undefined && candle.high !== undefined) {
      if (candle.close > candle.high) {
        warnings.push(`Candle ${index}: Close (${candle.close}) > High (${candle.high})`);
      }
    }

    if (candle.close !== undefined && candle.low !== undefined) {
      if (candle.close < candle.low) {
        warnings.push(`Candle ${index}: Close (${candle.close}) < Low (${candle.low})`);
      }
    }

    // Check for zero volume (warning, not error)
    if (candle.volume !== undefined && candle.volume === 0) {
      warnings.push(`Candle ${index}: Zero volume`);
    }

    // Check for negative prices
    ['open', 'high', 'low', 'close'].forEach(field => {
      const value = candle[field as keyof CandleDataPoint];
      if (typeof value === 'number' && value < 0) {
        errors.push(`Candle ${index}: Negative ${field} (${value})`);
      }
    });
  });

  // Check for duplicate timestamps
  const timestamps = candles.map(c => c.time);
  const uniqueTimestamps = new Set(timestamps);
  if (uniqueTimestamps.size < timestamps.length) {
    warnings.push('Duplicate timestamps detected');
  }

  // Check for time sequence gaps (optional, for large datasets)
  if (candles.length > 10) {
    let gapCount = 0;
    for (let i = 1; i < candles.length; i++) {
      const gap = candles[i].time - candles[i - 1].time;
      // If gap is more than 10x the median gap, flag it
      if (gap > 86400) { // More than 1 day
        gapCount++;
      }
    }
    if (gapCount > 0) {
      warnings.push(`${gapCount} large time gaps detected (>24h)`);
    }
  }

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
  };
}
