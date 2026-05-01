/**
 * Chart utility functions for time conversion and formatting.
 */

import { IST_OFFSET_SECONDS } from '../constants';

/**
 * Convert a date string or timestamp to IST Unix timestamp.
 * Used for Lightweight Charts time format.
 */
export const toIST = (time: string | number | Date): number => {
  const ts = new Date(time).getTime();
  return ts / 1000 + IST_OFFSET_SECONDS;
};

/**
 * Convert OHLC time to chart format with IST offset.
 */
export const toChartTime = (time: string): number => {
  return toIST(time);
};

/**
 * Format timestamp for display in IST timezone.
 */
export const formatISTTime = (time: string | number | Date): string => {
  const date = new Date(time);
  return date.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
  });
};

/**
 * Create a chart marker with consistent styling.
 */
export const createMarker = (params: {
  time: number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: string;
  text: string;
  size?: number;
}) => ({
  time: params.time as any,
  position: params.position,
  color: params.color,
  shape: params.shape,
  text: params.text,
  size: params.size || 1,
});

/**
 * Get candle color based on OHLC data.
 */
export const getCandleColor = (open: number, close: number): { bullColor: string; bearColor: string } => {
  const isBull = close >= open;
  return {
    bullColor: isBull ? '#10b981' : '#ef4444',
    bearColor: isBull ? '#10b981' : '#ef4444',
  };
};