import { TradePosition, OHLCData, AMTAnalysis, HalfTrendPoint, HalfTrendState } from '../../types';
import { IST_OFFSET_SECONDS } from '../../time/ist';
import { toISTTimestamp } from './CandleSeriesManager';

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
  quantDecision?: any | null;
  decisionHistory?: any[];
  currentSymbol?: string;
}

/**
 * Generate entry markers from open positions
 * 
 * @param positions - Open trade positions
 * @param fallbackTime - Optional fallback IST timestamp if pos.entryTime is missing
 * @param currentSymbol - Optional current chart symbol for isolation
 * @returns Array of entry markers
 */
export function generateEntryMarkers(
  positions: TradePosition[],
  fallbackTime?: number,
  currentSymbol?: string
): ChartMarker[] {
  const markers: ChartMarker[] = [];
  (positions || []).forEach(pos => {
    if (currentSymbol && pos.symbol && pos.symbol !== currentSymbol) {
      return;
    }
    let time = toISTTimestamp(pos.entryTime);
    if ((time <= 0 || !Number.isFinite(time)) && fallbackTime && fallbackTime > 0) {
      time = fallbackTime;
    }
    if (time <= 0 || !Number.isFinite(time)) return;
    markers.push({
      time,
      position: pos.side === 'LONG' ? 'belowBar' : 'aboveBar',
      color: pos.side === 'LONG' ? '#10b981' : '#ef4444',
      shape: pos.side === 'LONG' ? 'arrowUp' : 'arrowDown',
      text: `${pos.side} @${pos.entryPrice.toFixed(2)}`,
      size: 2 as const,
    });
  });
  return markers;
}

/**
 * Generate entry and exit markers from closed trades
 * 
 * @param closedTrades - Closed trade history
 * @param currentSymbol - Optional current chart symbol for isolation
 * @returns Array of entry and exit markers
 */
export function generateClosedTradeMarkers(
  closedTrades: TradePosition[],
  currentSymbol?: string
): ChartMarker[] {
  const markers: ChartMarker[] = [];

  (closedTrades || []).forEach(trade => {
    if (currentSymbol && trade.symbol && trade.symbol !== currentSymbol) {
      return;
    }
    // Entry marker (smaller size to differentiate from open positions)
    const entryTime = toISTTimestamp(trade.entryTime);
    if (entryTime > 0 && Number.isFinite(entryTime)) {
      markers.push({
        time: entryTime,
        position: trade.side === 'LONG' ? 'belowBar' : 'aboveBar',
        color: trade.side === 'LONG' ? '#10b981' : '#ef4444',
        shape: trade.side === 'LONG' ? 'arrowUp' : 'arrowDown',
        text: `${trade.side} @${trade.entryPrice.toFixed(2)}`,
        size: 1 as const,
      });
    }

    // Exit marker
    if (trade.exitTime && trade.exitPrice) {
      const exitTime = toISTTimestamp(trade.exitTime);
      if (exitTime > 0 && Number.isFinite(exitTime)) {
        const reason = trade.closeReason || 'EXIT';
        const pnlStr = trade.pnl >= 0 ? `+${trade.pnl.toFixed(2)}` : trade.pnl.toFixed(2);
        
        markers.push({
          time: exitTime,
          position: trade.side === 'LONG' ? 'aboveBar' : 'belowBar',
          color: trade.pnl >= 0 ? '#10b981' : '#ef4444',
          shape: 'circle',
          text: `${reason} ${pnlStr}`,
          size: 1 as const,
        });
      }
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

  // Scale guard: if breakLevel is far out of scale from chart candles (e.g. futures level on option chart), skip
  if (data && data.length > 0) {
    const lastClose = data[data.length - 1].close;
    if (lastClose > 0 && (breakLevel > lastClose * 3 || breakLevel < lastClose * 0.3)) {
      return null;
    }
  }

  // Find the first candle that broke the IB level
  for (let i = 1; i < data.length; i++) {
    const prev = data[i - 1];
    const curr = data[i];
    
    const crossedUp = breakDir === 'UP' && prev.close <= breakLevel && curr.close > breakLevel;
    const crossedDown = breakDir === 'DOWN' && prev.close >= breakLevel && curr.close < breakLevel;
    
    if (crossedUp || crossedDown) {
      const time = toISTTimestamp(curr.time);
      if (time <= 0 || !Number.isFinite(time)) continue;
      return {
        time,
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
  if (!amt?.cvdDivergence || !data || data.length === 0) {
    return [];
  }

  const markers: ChartMarker[] = [];
  const recentCount = Math.min(3, data.length);
  const isBearishDiv = amt.cvdDivergence.includes('BEARISH');

  // Add markers on the last N candles
  for (let i = data.length - recentCount; i < data.length; i++) {
    const candle = data[i];
    const time = toISTTimestamp(candle.time);
    if (time <= 0 || !Number.isFinite(time)) continue;
    const isInitial = i === (data.length - recentCount);
    
    markers.push({
      time,
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
  if (!amt || !data || data.length === 0) {
    return [];
  }

  const lastCandle = data[data.length - 1];
  const lastTime = toISTTimestamp(lastCandle.time);
  if (lastTime <= 0 || !Number.isFinite(lastTime)) {
    return [];
  }

  const markers: ChartMarker[] = [];

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
  if (amt.rejectionAtHigh) {
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
  if (amt.rejectionAtLow) {
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
 * Generate LuxAlgo Value Area Reversion Signal (VARS) reclaim markers
 */
export function generateVARSReclaimMarkers(
  data: OHLCData[],
  amt: AMTAnalysis | null
): ChartMarker[] {
  if (!amt?.vars || !data || data.length === 0) {
    return [];
  }

  const markers: ChartMarker[] = [];
  const lastTime = toISTTimestamp(data[data.length - 1].time);
  const src = amt.vars.signalSource || 'VA';

  if (amt.vars.bullishReclaim) {
    markers.push({
      time: lastTime,
      position: 'belowBar',
      color: '#089981',
      shape: 'arrowUp',
      text: `${src} BUY`,
      size: 1 as const,
    });
  }

  if (amt.vars.bearishReclaim) {
    markers.push({
      time: lastTime,
      position: 'aboveBar',
      color: '#f23645',
      shape: 'arrowDown',
      text: `${src} SELL`,
      size: 1 as const,
    });
  }

  return markers;
}

/**
 * Generate Triple-A (Absorption -> Accumulation -> Aggression) signal markers
 */
export function generateTripleAMarkers(
  data: OHLCData[],
  amt: AMTAnalysis | null
): ChartMarker[] {
  if (!amt || !data || data.length === 0) return [];
  const signal = (amt as any).tripleASignal;
  if (!signal || (signal !== 'LONG' && signal !== 'SHORT')) return [];

  const lastCandle = data[data.length - 1];
  const time = toISTTimestamp(lastCandle.time);
  if (time <= 0 || !Number.isFinite(time)) return [];

  const phase = (amt as any).tripleAPhase || 'AGG';
  const isLong = signal === 'LONG';

  return [{
    time,
    position: isLong ? 'belowBar' : 'aboveBar',
    color: isLong ? '#06b6d4' : '#f43f5e',
    shape: isLong ? 'arrowUp' : 'arrowDown',
    text: `3A ${signal} (${phase})`,
    size: 2 as const,
  }];
}

/**
 * Snap a timestamp to the corresponding bar time in the candle series.
 * Returns the bar time (candleTimes[i] <= time), or the exact time if no candles.
 */
export function snapToBarTime(time: number, barTimes: number[]): number {
  if (!barTimes || barTimes.length === 0 || time <= 0) return time;
  if (time < barTimes[0]) return barTimes[0];
  let low = 0;
  let high = barTimes.length - 1;
  let best = barTimes[0];
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (barTimes[mid] <= time) {
      best = barTimes[mid];
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return best;
}

/**
 * Generate AMT Quant Decision and historical signal markers
 */
export function generateDecisionSignalMarkers(
  data: OHLCData[],
  quantDecision?: any | null,
  decisionHistory?: any[],
  currentSymbol?: string,
  existingMarkers?: ChartMarker[]
): ChartMarker[] {
  const markers: ChartMarker[] = [];
  const barTimes = (data || []).map(d => toISTTimestamp(d.time)).filter(t => t > 0);

  // Collect entry times from existing markers to prevent placing redundant generic decision arrows on the exact same candle
  const entryTimes = new Set<number>();
  (existingMarkers || []).forEach(m => {
    if (m.text.startsWith('LONG @') || m.text.startsWith('SHORT @')) {
      entryTimes.add(barTimes.length > 0 ? snapToBarTime(m.time, barTimes) : m.time);
    }
  });

  // Track the previous direction to only record directional changes / state transitions
  // and ensure at most one decision marker per candle bar
  let lastDirection: string | null = null;
  const seenBarTimes = new Set<number>();

  (decisionHistory || []).forEach(h => {
    if (h.symbol && currentSymbol && h.symbol !== currentSymbol) {
      return;
    }
    const dir = h.direction;
    if (dir === 'LONG' || dir === 'SHORT') {
      const rawTime = toISTTimestamp(h.timestamp);
      if (rawTime > 0 && Number.isFinite(rawTime)) {
        const time = barTimes.length > 0 ? snapToBarTime(rawTime, barTimes) : rawTime;
        // If an actual order entry already exists on this bar, suppress generic "AMT LONG/SHORT"
        if (entryTimes.has(time)) {
          lastDirection = dir;
          return;
        }
        // Only trigger on directional change/initiation and at most once per bar
        if (dir !== lastDirection && !seenBarTimes.has(time)) {
          const isLong = dir === 'LONG';
          markers.push({
            time,
            position: isLong ? 'belowBar' : 'aboveBar',
            color: isLong ? '#10b981' : '#ef4444',
            shape: isLong ? 'arrowUp' : 'arrowDown',
            text: `AMT ${dir}`,
            size: 1 as const,
          });
          seenBarTimes.add(time);
        }
        lastDirection = dir;
      }
    } else if (dir === 'FLAT' || dir === 'EXIT' || !dir) {
      lastDirection = null;
    }
  });

  // Current active quant decision
  if (quantDecision?.signal && (quantDecision.signal.type === 'LONG' || quantDecision.signal.type === 'SHORT')) {
    const sigSymbol = quantDecision.signal.symbol || quantDecision.symbol;
    if (sigSymbol && currentSymbol && sigSymbol !== currentSymbol) {
      return markers;
    }
    const entryPx = Number(quantDecision.signal.entry) || 0;
    // Cross-scale guard: if entry price is 3x higher or 0.3x lower than candle price, it belongs to underlying index, not this chart
    if (data && data.length > 0 && entryPx > 0) {
      const lastClose = data[data.length - 1].close;
      if (lastClose > 0 && (entryPx > lastClose * 3 || entryPx < lastClose * 0.3)) {
        return markers;
      }
    }
    const isLong = quantDecision.signal.type === 'LONG';
    const pxStr = entryPx > 0 ? ` @${entryPx.toFixed(2)}` : '';
    const label = quantDecision.approved ? 'AMT DECISION' : 'AMT SIGNAL';

    if (data && data.length > 0) {
      const lastTime = toISTTimestamp(data[data.length - 1].time);
      if (lastTime > 0 && Number.isFinite(lastTime)) {
        // If an actual order entry already took place on this last candle, suppress recommendation marker to avoid overlap
        if (!entryTimes.has(lastTime)) {
          markers.push({
            time: lastTime,
            position: isLong ? 'belowBar' : 'aboveBar',
            color: isLong ? '#10b981' : '#ef4444',
            shape: isLong ? 'arrowUp' : 'arrowDown',
            text: `${label} ${quantDecision.signal.type}${pxStr}`,
            size: 2 as const,
          });
        }
      }
    }
  }

  return markers;
}

/** Pine HalfTrend colors. */
export const HALF_TREND_UP_COLOR = '#2962ff'; // Pine buyColor (blue)
export const HALF_TREND_DOWN_COLOR = '#f23645'; // Pine sellColor (red)

/**
 * Normalize one live `amt.halfTrend` record (camelCase signal keys) into a
 * HalfTrendPoint compatible with the REST history rows.
 */
/**
 * Drop stale HalfTrend rows whose ATR channel rails are non-positive
 * (0/negative) — the artifact of the old DTO that serialized pre-warm-up
 * rails as 0.0. Called on WS reconnect and symbol switch so those
 * zero-value rails can never resurface in the series.
 *
 * Null rails are deliberately KEPT: pre-warm-up rows carry the valid ht
 * line (only the channel needs ATR), so dropping them would erase the
 * trend line entirely for sessions shorter than ATR(period).
 *
 * Returns the same array reference when nothing is pruned, so React.memo
 * comparators (ChartScene) don't trigger spurious re-renders.
 */
export function pruneHalfTrendSeries(
  series: HalfTrendPoint[] | undefined
): HalfTrendPoint[] {
  const pts = series || [];
  const pruned = pts.filter(
    p => (p.atrHigh == null || p.atrHigh > 0) && (p.atrLow == null || p.atrLow > 0)
  );
  return pruned.length === pts.length ? pts : pruned;
}

export function halfTrendLivePoint(
  ht?: HalfTrendState
): HalfTrendPoint | null {
  if (!ht || !ht.time) return null;
  return {
    time: ht.time,
    trend: ht.trend,
    ht: ht.ht,
    // Channel rails are null until the backend ATR warms up. Treat 0 as
    // null too: a 0-value rail would stretch the chart's price scale from
    // 0 up to the candle price and visually crush the candles.
    atrHigh: ht.atrHigh ? Number(ht.atrHigh) : null,
    atrLow: ht.atrLow ? Number(ht.atrLow) : null,
    buy: !!ht.buySignal,
    sell: !!ht.sellSignal,
  };
}

/**
 * Upsert one point into the HalfTrend series (replace same-timestamp rows,
 * append newer ones), capped like the candle history.
 *
 * The replace/append decisions compare epoch milliseconds, NOT raw strings:
 * the REST history rows are ISO-8601 IST and the WS live rows are the same
 * after the DTO normalization — but a raw-string compare would silently
 * duplicate (or drop, when one side parses invalid) the same bar across
 * formats. epoch-ms is format-agnostic and strict for the pinned tests.
 */
export function mergeHalfTrendPoint(
  series: HalfTrendPoint[] | undefined,
  point: HalfTrendPoint
): HalfTrendPoint[] {
  const out = [...(series || [])];
  const last = out[out.length - 1];
  const pointMs = new Date(point.time).getTime();
  if (!isNaN(pointMs) && last && new Date(last.time).getTime() === pointMs) {
    out[out.length - 1] = point;
    return out;
  }
  if (
    !last ||
    (isNaN(pointMs) && last.time === point.time) ||
    (!isNaN(pointMs) && pointMs > new Date(last.time).getTime())
  ) {
    out.push(point);
    if (out.length > 500) out.shift();
  }
  return out;
}

/**
 * Build lightweight-charts data for the HalfTrend overlay: the trend line
 * (per-point colored) plus the ATR channel rails. Channel points are null
 * before the ATR warms up -> whitespace rows so the rails skip those bars.
 */
export function halfTrendSeriesData(points: HalfTrendPoint[]) {
  const ht: { time: number; value: number; color: string }[] = [];
  const atrHigh: { time: number; value: number; color: string }[] = [];
  const atrLow: { time: number; value: number; color: string }[] = [];

  for (const p of points) {
    const time = toISTTimestamp(p.time);
    if (time <= 0) continue;
    ht.push({
      time,
      value: p.ht,
      color: p.trend === 1 ? HALF_TREND_DOWN_COLOR : HALF_TREND_UP_COLOR,
    });
    // Rails must be positive real channel values; a 0/null rail is skipped
    // so the price scale is never stretched by a rogue zero point.
    if (p.atrHigh != null && p.atrHigh > 0) {
      atrHigh.push({ time, value: p.atrHigh, color: HALF_TREND_DOWN_COLOR });
    }
    if (p.atrLow != null && p.atrLow > 0) {
      atrLow.push({ time, value: p.atrLow, color: HALF_TREND_UP_COLOR });
    }
  }
  return { ht, atrHigh, atrLow };
}

/**
 * Buy/Sell label markers from the HalfTrend series. All signal detection
 * happens in the backend; here we only place labels at the signal times.
 */
export function halfTrendSignalMarkers(points: HalfTrendPoint[]): ChartMarker[] {
  const markers: ChartMarker[] = [];
  for (const p of points) {
    const time = toISTTimestamp(p.time);
    if (time <= 0 || !Number.isFinite(time)) continue;
    if (p.buy) {
      markers.push({
        time,
        position: 'belowBar',
        color: HALF_TREND_UP_COLOR,
        shape: 'arrowUp',
        text: 'Buy',
        size: 1 as const,
      });
    }
    if (p.sell) {
      markers.push({
        time,
        position: 'aboveBar',
        color: HALF_TREND_DOWN_COLOR,
        shape: 'arrowDown',
        text: 'Sell',
        size: 1 as const,
      });
    }
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
  const markers: ChartMarker[] = [];
  const currentSymbol = options?.currentSymbol;
  const fallbackTime = data && data.length > 0 ? toISTTimestamp(data[data.length - 1].time) : undefined;

  // Entry markers from open positions
  const entryMarkers = generateEntryMarkers(positions, fallbackTime, currentSymbol);
  markers.push(...entryMarkers);

  // Entry + exit markers from closed trades
  const closedMarkers = generateClosedTradeMarkers(closedTrades, currentSymbol);
  markers.push(...closedMarkers);

  // AMT Decision and Signal markers
  markers.push(
    ...generateDecisionSignalMarkers(
      data,
      options?.quantDecision,
      options?.decisionHistory,
      currentSymbol,
      [...entryMarkers, ...closedMarkers]
    )
  );

  // Triple-A markers
  markers.push(...generateTripleAMarkers(data, amt));

  // IB break marker
  const ibBreak = generateIBBreakMarker(data, amt);
  if (ibBreak) {
    markers.push(ibBreak);
  }

  // CVD divergence markers
  markers.push(...generateCVDDivergenceMarkers(data, amt));

  // Acceptance/rejection markers
  markers.push(...generateAcceptanceRejectionMarkers(data, amt));

  // LuxAlgo VARS Reclaim markers
  markers.push(...generateVARSReclaimMarkers(data, amt));

  // Deduplicate overlapping markers with same time, position, and text
  const seen = new Set<string>();
  const deduped: ChartMarker[] = [];
  for (const m of markers) {
    const key = `${m.time}_${m.position}_${m.text}`;
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(m);
    }
  }

  // Sanitize: ensure all markers have valid finite time > 0
  const validMarkers = deduped.filter(m => Number.isFinite(m.time) && m.time > 0);

  // Limit markers for performance (optional)
  const maxMarkers = options?.maxMarkers || 100;
  if (validMarkers.length > maxMarkers) {
    // Keep most recent markers by sorting by time descending
    validMarkers.sort((a, b) => b.time - a.time);
    const sliced = validMarkers.slice(0, maxMarkers);
    sliced.sort((a, b) => a.time - b.time);
    return sliced;
  }

  validMarkers.sort((a, b) => a.time - b.time);
  return validMarkers;
}
