/**
 * CrosshairManager - Data formatting for crosshair tooltip
 * 
 * Formats and aggregates data for display when user hovers over chart:
 * - OHLCV data formatting
 * - AMT level annotations
 * - PnL calculations for trades
 * - Time formatting
 * 
 * Benefits:
 * - 100% testable (pure functions)
 * - Separates formatting from rendering
 * - Easy to validate tooltip data
 * - Consistent display logic
 */

export interface CrosshairData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap?: number;
}

export interface TradeInfo {
  side: 'LONG' | 'SHORT';
  entryPrice: number;
  currentPrice: number;
  entryTime: string;
}

export interface CrosshairTooltipData {
  timeLabel: string;
  priceLines: string[];
  volumeLabel?: string;
  pnlLabel?: string;
  tradeInfo?: TradeInfo;
  amtAnnotations: string[];
}

/**
 * Format OHLCV data for crosshair tooltip
 * 
 * @param data - Crosshair data point
 * @returns Formatted price lines
 */
export function formatPriceLines(data: CrosshairData): string[] {
  const lines: string[] = [];

  lines.push(`O: ${data.open.toFixed(2)}`);
  lines.push(`H: ${data.high.toFixed(2)}`);
  lines.push(`L: ${data.low.toFixed(2)}`);
  lines.push(`C: ${data.close.toFixed(2)}`);

  if (data.vwap != null && data.vwap > 0) {
    lines.push(`VWAP: ${data.vwap.toFixed(2)}`);
  }

  return lines;
}

/**
 * Format volume for display
 * 
 * @param volume - Volume value
 * @returns Formatted volume string
 */
export function formatVolume(volume: number): string {
  if (volume >= 1000000) {
    return `${(volume / 1000000).toFixed(2)}M`;
  }
  if (volume >= 1000) {
    return `${(volume / 1000).toFixed(2)}K`;
  }
  return volume.toFixed(0);
}

/**
 * Calculate PnL for a trade
 * 
 * @param trade - Trade information
 * @returns PnL value (positive = profit)
 */
export function calculateTradePnL(trade: TradeInfo): number {
  if (trade.side === 'LONG') {
    return trade.currentPrice - trade.entryPrice;
  }
  return trade.entryPrice - trade.currentPrice;
}

/**
 * Format PnL for display
 * 
 * @param pnl - PnL value
 * @returns Formatted PnL string with sign
 */
export function formatPnL(pnl: number): string {
  const sign = pnl >= 0 ? '+' : '';
  return `${sign}${pnl.toFixed(2)}`;
}

/**
 * Format time for display
 * 
 * @param timestamp - Unix timestamp
 * @returns Formatted time string (HH:MM:SS)
 */
export function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  const hours = String(date.getUTCHours()).padStart(2, '0');
  const minutes = String(date.getUTCMinutes()).padStart(2, '0');
  const seconds = String(date.getUTCSeconds()).padStart(2, '0');
  return `${hours}:${minutes}:${seconds}`;
}

/**
 * Generate AMT level annotations for crosshair
 * 
 * @param price - Current price
 * @param amtLevels - AMT analysis levels
 * @returns Array of annotation strings
 */
export function generateAMTAnnotations(
  price: number,
  amtLevels: {
    poc?: number;
    valueAreaHigh?: number;
    valueAreaLow?: number;
    sessionVwap?: number;
  }
): string[] {
  const annotations: string[] = [];

  if (amtLevels.poc != null) {
    const diff = price - amtLevels.poc;
    annotations.push(`POC: ${amtLevels.poc.toFixed(2)} (${diff >= 0 ? '+' : ''}${diff.toFixed(2)})`);
  }

  if (amtLevels.valueAreaHigh != null) {
    const diff = price - amtLevels.valueAreaHigh;
    annotations.push(`VAH: ${amtLevels.valueAreaHigh.toFixed(2)} (${diff >= 0 ? '+' : ''}${diff.toFixed(2)})`);
  }

  if (amtLevels.valueAreaLow != null) {
    const diff = price - amtLevels.valueAreaLow;
    annotations.push(`VAL: ${amtLevels.valueAreaLow.toFixed(2)} (${diff >= 0 ? '+' : ''}${diff.toFixed(2)})`);
  }

  if (amtLevels.sessionVwap != null && amtLevels.sessionVwap > 0) {
    const diff = price - amtLevels.sessionVwap;
    annotations.push(`VWAP: ${amtLevels.sessionVwap.toFixed(2)} (${diff >= 0 ? '+' : ''}${diff.toFixed(2)})`);
  }

  return annotations;
}

/**
 * Build complete crosshair tooltip data
 * 
 * @param data - Crosshair data point
 * @param amtLevels - Optional AMT levels
 * @param activeTrade - Optional active trade
 * @returns Complete tooltip data
 */
export function buildCrosshairTooltip(
  data: CrosshairData,
  amtLevels?: {
    poc?: number;
    valueAreaHigh?: number;
    valueAreaLow?: number;
    sessionVwap?: number;
  },
  activeTrade?: TradeInfo
): CrosshairTooltipData {
  const priceLines = formatPriceLines(data);
  const amtAnnotations = amtLevels
    ? generateAMTAnnotations(data.close, amtLevels)
    : [];

  let pnlLabel: string | undefined;
  if (activeTrade) {
    const pnl = calculateTradePnL(activeTrade);
    pnlLabel = `PnL: ${formatPnL(pnl)}`;
  }

  return {
    timeLabel: data.time,
    priceLines,
    volumeLabel: formatVolume(data.volume),
    pnlLabel,
    tradeInfo: activeTrade,
    amtAnnotations,
  };
}

/**
 * Validate crosshair data
 * 
 * @param data - Crosshair data
 * @returns Array of validation errors (empty if valid)
 */
export function validateCrosshairData(data: CrosshairData): string[] {
  const errors: string[] = [];

  if (!data.time) {
    errors.push('Missing time');
  }
  if (data.open === undefined || data.open === null) {
    errors.push('Missing open price');
  }
  if (data.high === undefined || data.high === null) {
    errors.push('Missing high price');
  }
  if (data.low === undefined || data.low === null) {
    errors.push('Missing low price');
  }
  if (data.close === undefined || data.close === null) {
    errors.push('Missing close price');
  }
  if (data.volume === undefined || data.volume === null) {
    errors.push('Missing volume');
  }

  // Validate price relationships
  if (data.high < data.low) {
    errors.push(`High (${data.high}) < Low (${data.low})`);
  }
  if (data.open > data.high) {
    errors.push(`Open (${data.open}) > High (${data.high})`);
  }
  if (data.open < data.low) {
    errors.push(`Open (${data.open}) < Low (${data.low})`);
  }
  if (data.close > data.high) {
    errors.push(`Close (${data.close}) > High (${data.high})`);
  }
  if (data.close < data.low) {
    errors.push(`Close (${data.close}) < Low (${data.low})`);
  }

  return errors;
}
