import { TradePosition, OHLCData, AMTAnalysis } from '../../types';

/**
 * ExecutionMarkersManager - Pure data transformation for chart execution markers
 * 
 * Transforms positions, closed trades, and AMT analysis into TradingView
 * Lightweight Charts marker configurations.
 * 
 * Benefits:
 * - 100% testable (pure functions)
 * - Separates marker logic from chart rendering
 * - Easy to validate marker placement and styling
 * - Supports multiple marker types (entries, exits, events)
 */

export interface ChartMarker {
  time: number; // Unix timestamp
  position: 'aboveBar' | 'belowBar' | 'inBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square' | 'diamond';
  text: string;
  size: 1 | 2;
}

export interface ExecutionMarkersOptions {
  mode: 'STANDARD' | 'FOOTPRINT' | 'RANGE';
  maxMarkers?: number; // Limit markers for performance
}

/**
 * IST timezone offset in seconds (UTC+5:30)
 */
const IST_OFFSET = 19800;

/**
 * Generate entry markers from open positions
 * 
 * @param positions - Open trade positions
 * @returns Array of entry markers
 */
export function generateEntryMarkers(positions: TradePosition[]): ChartMarker[] {
  return positions.map(pos => ({
    time: new Date(pos.entryTime).getTime() / 1000 + IST_OFFSET,
    position: pos.side === 'LONG' ? 'belowBar' : 'aboveBar',
    color: pos.side === 'LONG' ? '#10b981' : '#ef4444',
    shape: pos.side === 'LONG' ? 'arrowUp' : 'arrowDown',
    text: `${pos.side} @${pos.entryPrice.toFixed(2)}`,
    size: 2 as const,
  }));
}

/**
 * Generate entry and exit markers from closed trades
 * 
 * @param closedTrades - Closed trade history
 * @returns Array of entry and exit markers
 */
export function generateClosedTradeMarkers(closedTrades: TradePosition[]): ChartMarker[] {
  const markers: ChartMarker[] = [];

  closedTrades.forEach(trade => {
    // Entry marker (smaller size to differentiate from open positions)
    markers.push({
      time: new Date(trade.entryTime).getTime() / 1000 + IST_OFFSET,
      position: trade.side === 'LONG' ? 'belowBar' : 'aboveBar',
      color: trade.side === 'LONG' ? '#10b981' : '#ef4444',
      shape: trade.side === 'LONG' ? 'arrowUp' : 'arrowDown',
      text: `${trade.side} @${trade.entryPrice.toFixed(2)}`,
      size: 1 as const,
    });

    // Exit marker
    if (trade.exitTime && trade.exitPrice) {
      const reason = trade.closeReason || 'EXIT';
      const pnlStr = trade.pnl >= 0 ? `+${trade.pnl.toFixed(2)}` : trade.pnl.toFixed(2);
      
      markers.push({
        time: new Date(trade.exitTime).getTime() / 1000 + IST_OFFSET,
        position: trade.side === 'LONG' ? 'aboveBar' : 'belowBar',
        color: trade.pnl >= 0 ? '#10b981' : '#ef4444',
        shape: 'circle',
        text: `${reason} ${pnlStr}`,
        size: 1 as const,
      });
    }
  });

  return markers;
}

/**
 * Generate IB (Initial Balance) break marker
 * 
 * @param data - OHLCV candle data
 * @param amt - AMT analysis with break direction and level
 * @returns IB break marker or null
 */
export function generateIBBreakMarker(
  data: OHLCData[],
  amt: AMTAnalysis | null
): ChartMarker | null {
  if (!amt?.breakDirection || !amt.breakLevel || amt.breakLevel <= 0) {
    return null;
  }

  const breakDir = amt.breakDirection;
  const breakLevel = amt.breakLevel;

  // Find the first candle that broke the IB level
  for (let i = 1; i < data.length; i++) {
    const prev = data[i - 1];
    const curr = data[i];
    
    const crossedUp = breakDir === 'UP' && prev.close <= breakLevel && curr.close > breakLevel;
    const crossedDown = breakDir === 'DOWN' && prev.close >= breakLevel && curr.close < breakLevel;
    
    if (crossedUp || crossedDown) {
      return {
        time: new Date(curr.time).getTime() / 1000 + IST_OFFSET,
        position: breakDir === 'UP' ? 'belowBar' : 'aboveBar',
        color: breakDir === 'UP' ? '#10b981' : '#ef4444',
        shape: breakDir === 'UP' ? 'arrowUp' : 'arrowDown',
        text: `IB BREAK ${breakDir} @${breakLevel.toFixed(2)}`,
        size: 2 as const,
      };
    }
  }

  return null;
}

/**
 * Generate CVD divergence markers on recent candles
 * 
 * @param data - OHLCV candle data
 * @param amt - AMT analysis with CVD divergence info
 * @returns Array of CVD divergence markers
 */
export function generateCVDDivergenceMarkers(
  data: OHLCData[],
  amt: AMTAnalysis | null
): ChartMarker[] {
  if (!amt?.cvdDivergence || data.length === 0) {
    return [];
  }

  const markers: ChartMarker[] = [];
  const recentCount = Math.min(3, data.length);
  const isBearishDiv = amt.cvdDivergence.includes('BEARISH');

  // Add markers on the last N candles
  for (let i = data.length - recentCount; i < data.length; i++) {
    const candle = data[i];
    const isInitial = i === (data.length - recentCount);
    
    markers.push({
      time: new Date(candle.time).getTime() / 1000 + IST_OFFSET,
      position: isBearishDiv ? 'aboveBar' : 'belowBar',
      color: isInitial ? '#f97316' : 'rgba(249, 115, 22, 0.4)',
      shape: 'circle',
      text: isInitial ? '⚡CVD DIV' : 'div',
      size: 1 as const,
    });
  }

  return markers;
}

/**
 * Generate acceptance/rejection markers at key levels
 * 
 * @param data - OHLCV candle data
 * @param amt - AMT analysis with acceptance/rejection info
 * @returns Array of acceptance/rejection markers
 */
export function generateAcceptanceRejectionMarkers(
  data: OHLCData[],
  amt: AMTAnalysis | null
): ChartMarker[] {
  if (!amt || data.length === 0) {
    return [];
  }

  const markers: ChartMarker[] = [];
  const lastCandle = data[data.length - 1];
  const lastTime = new Date(lastCandle.time).getTime() / 1000 + IST_OFFSET;

  // Acceptance above VAH
  if (amt.acceptanceAbove) {
    markers.push({
      time: lastTime,
      position: 'aboveBar',
      color: '#10b981',
      shape: 'arrowUp',
      text: 'ACCEPT ABOVE',
      size: 1 as const,
    });
  }

  // Rejection from high levels (if available)
  if ((amt as any).rejectionFromVah) {
    markers.push({
      time: lastTime,
      position: 'aboveBar',
      color: '#ef4444',
      shape: 'arrowDown',
      text: 'REJECT VAH',
      size: 1 as const,
    });
  }

  // Acceptance below VAL
  if (amt.acceptanceBelow) {
    markers.push({
      time: lastTime,
      position: 'belowBar',
      color: '#ef4444',
      shape: 'arrowDown',
      text: 'ACCEPT BELOW',
      size: 1 as const,
    });
  }

  // Rejection from low levels (if available)
  if ((amt as any).rejectionFromVal) {
    markers.push({
      time: lastTime,
      position: 'belowBar',
      color: '#10b981',
      shape: 'arrowUp',
      text: 'REJECT VAL',
      size: 1 as const,
    });
  }

  return markers;
}

/**
 * Generate all execution markers for chart display
 * 
 * @param positions - Open positions
 * @param closedTrades - Closed trade history
 * @param data - OHLCV candle data
 * @param amt - AMT analysis
 * @param options - Display options
 * @returns Combined array of all markers
 */
export function generateAllExecutionMarkers(
  positions: TradePosition[],
  closedTrades: TradePosition[],
  data: OHLCData[],
  amt: AMTAnalysis | null,
  options: ExecutionMarkersOptions
): ChartMarker[] {
  // Only generate markers in STANDARD mode
  if (options.mode !== 'STANDARD') {
    return [];
  }

  const markers: ChartMarker[] = [];

  // Entry markers from open positions
  markers.push(...generateEntryMarkers(positions));

  // Entry + exit markers from closed trades
  markers.push(...generateClosedTradeMarkers(closedTrades));

  // IB break marker
  const ibBreak = generateIBBreakMarker(data, amt);
  if (ibBreak) {
    markers.push(ibBreak);
  }

  // CVD divergence markers
  markers.push(...generateCVDDivergenceMarkers(data, amt));

  // Acceptance/rejection markers
  markers.push(...generateAcceptanceRejectionMarkers(data, amt));

  // Limit markers for performance (optional)
  const maxMarkers = options.maxMarkers || 100;
  if (markers.length > maxMarkers) {
    // Keep most recent markers by sorting by time descending
    markers.sort((a, b) => b.time - a.time);
    return markers.slice(0, maxMarkers);
  }

  return markers;
}

/**
 * Count markers by type
 * 
 * Classification by marker text (more reliable than shape alone, since exit
 * markers use the same circle shape as event markers):
 *   - exits:    EXIT / TP HIT / SL HIT / signed P&L text
 *   - events:   CVD divergence, IB break, acceptance/rejection
 *   - entries:  everything else (arrow markers from open/closed positions)
 * 
 * @param markers - Array of markers
 * @returns Count breakdown by type
 */
export function countMarkersByType(markers: ChartMarker[]): Record<string, number> {
  const counts: Record<string, number> = {
    entries: 0,
    exits: 0,
    events: 0,
  };

  const EVENT_PATTERN = /CVD|IB BREAK|ACCEPT|REJECT|DIV/i;
  const EXIT_PATTERN = /EXIT|TP HIT|SL HIT|\bHIT\b|^[+-]\d/;

  markers.forEach(marker => {
    const text = marker.text || '';
    if (EVENT_PATTERN.test(text)) {
      counts.events++;
    } else if (EXIT_PATTERN.test(text)) {
      counts.exits++;
    } else {
      counts.entries++;
    }
  });

  return counts;
}

/**
 * Filter markers by time range
 * 
 * @param markers - Array of markers
 * @param startTime - Start timestamp
 * @param endTime - End timestamp
 * @returns Filtered markers within time range
 */
export function filterMarkersByTimeRange(
  markers: ChartMarker[],
  startTime: number,
  endTime: number
): ChartMarker[] {
  return markers.filter(m => m.time >= startTime && m.time <= endTime);
}

/**
 * Validate marker data integrity
 * 
 * @param markers - Array of markers to validate
 * @returns Array of validation errors (empty if valid)
 */
export function validateMarkers(markers: ChartMarker[]): string[] {
  const errors: string[] = [];

  markers.forEach((marker, index) => {
    if (!marker.time || marker.time <= 0) {
      errors.push(`Marker ${index}: Invalid timestamp`);
    }
    if (!marker.color) {
      errors.push(`Marker ${index}: Missing color`);
    }
    if (!marker.text || marker.text.trim() === '') {
      errors.push(`Marker ${index}: Empty text`);
    }
    if (![1, 2].includes(marker.size)) {
      errors.push(`Marker ${index}: Invalid size ${marker.size}`);
    }
  });

  return errors;
}
