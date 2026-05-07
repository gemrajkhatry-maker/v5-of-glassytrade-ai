/**
 * ChartExecutionMarkers - Manages chart price lines and markers
 * Extracted from ChartScene.tsx lines 1473-1888
 * 
 * Features:
 * - AMT analysis lines (POC, VAH, VAL, LVN, HVN)
 * - IB High/Low lines
 * - VWAP bands with slope-based coloring
 * - Prior day levels
 * - Leg profile levels
 * - Trade entry/exit markers
 * - IB break markers
 * - CVD divergence markers
 * - Acceptance/rejection markers
 * - Position price lines (entry, SL, TP)
 */

import { ISeriesApi, IChartApi, LineStyle, SeriesMarker, UTCTimestamp, IPriceLine } from 'lightweight-charts';
import { AMTAnalysis, TradePosition, OHLCData, ChartConfig } from '../../types';

interface ExecutionMarkersProps {
  candleSeries: ISeriesApi<"Candlestick"> | null;
  chart: IChartApi | null;
  stableAmtAnalysis: AMTAnalysis | null;
  stableData: OHLCData[];
  positions: TradePosition[];
  closedTrades: TradePosition[];
  config: ChartConfig;
  mode: 'STANDARD' | 'FOOTPRINT' | 'RANGE';
}

interface MarkerRefs {
  amtLinesRef: React.MutableRefObject<IPriceLine[]>;
  activePriceLinesRef: React.MutableRefObject<Map<string, IPriceLine[]>>;
}

/**
 * Update all chart markers and price lines
 */
export const updateExecutionMarkers = (
  props: ExecutionMarkersProps,
  refs: MarkerRefs
) => {
  const {
    candleSeries,
    stableAmtAnalysis,
    stableData,
    positions,
    closedTrades,
    config,
    mode,
  } = props;

  const { amtLinesRef, activePriceLinesRef } = refs;

  if (!candleSeries) return;

  // Clear existing AMT lines
  amtLinesRef.current.forEach(l => candleSeries.removePriceLine(l));
  amtLinesRef.current = [];

  // Only add lightweight-chart pricelines if NOT in footprint mode
  const vpMode = config.vpMode || 'combined';
  if (stableAmtAnalysis && config.showVolumeProfile && mode !== 'FOOTPRINT') {
    updateAMTLines(candleSeries, stableAmtAnalysis, stableData, vpMode, config, amtLinesRef);
  }

  // Update trade markers (only in STANDARD mode)
  if (mode === 'STANDARD') {
    updateTradeMarkers(candleSeries, stableData, stableAmtAnalysis, positions, closedTrades);
  } else {
    candleSeries.setMarkers([]);
  }

  // Update position price lines
  updatePositionLines(candleSeries, positions, activePriceLinesRef);
};

/**
 * Update AMT analysis price lines (POC, VA, VWAP, IB, etc.)
 */
const updateAMTLines = (
  candleSeries: ISeriesApi<"Candlestick">,
  amt: AMTAnalysis,
  stableData: OHLCData[],
  vpMode: string,
  config: ChartConfig,
  amtLinesRef: React.MutableRefObject<IPriceLine[]>
) => {
  // Session levels (shown in session + combined modes)
  if (vpMode === 'session' || vpMode === 'combined') {
    addSessionLines(candleSeries, amt, amtLinesRef);
    addIBLines(candleSeries, amt, amtLinesRef);
    addVWAPLines(candleSeries, amt, stableData, amtLinesRef);
    addPriorDayLines(candleSeries, amt, amtLinesRef);
  }

  // Leg levels (shown in leg + combined modes when leg profile exists)
  if ((vpMode === 'leg' || vpMode === 'combined') && amt.legProfile && amt.legProfile.length > 0) {
    addLegLines(candleSeries, amt, amtLinesRef);
  }
};

/**
 * Add session profile lines (POC, VAH, VAL, LVN, HVN)
 */
const addSessionLines = (
  candleSeries: ISeriesApi<"Candlestick">,
  amt: AMTAnalysis,
  amtLinesRef: React.MutableRefObject<IPriceLine[]>
) => {
  // Session POC
  if (amt.poc > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.poc,
      color: '#facc15',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: 'S-POC',
    }));
  }

  // Session VAH
  if (amt.valueAreaHigh > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.valueAreaHigh,
      color: '#3b82f6',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'S-VAH',
    }));
  }

  // Session VAL
  if (amt.valueAreaLow > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.valueAreaLow,
      color: '#3b82f6',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'S-VAL',
    }));
  }

  // LVN lines (amber dotted — thin, low-volume gaps)
  amt.lvns?.forEach((lvn: number) => {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: lvn,
      color: '#fb923c',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: 'LVN',
    }));
  });

  // HVN lines (emerald dashed — high-volume support/resistance)
  amt.hvns?.forEach((hvn: number) => {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: hvn,
      color: '#34d399',
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'HVN',
    }));
  });
};

/**
 * Add IB High/Low lines
 */
const addIBLines = (
  candleSeries: ISeriesApi<"Candlestick">,
  amt: AMTAnalysis,
  amtLinesRef: React.MutableRefObject<IPriceLine[]>
) => {
  if (amt.ibHigh && amt.ibHigh > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.ibHigh,
      color: '#fb923c',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: amt.breakDirection === 'UP' ? 'IB HIGH [BROKEN ↑]' : 'IB HIGH',
    }));
  }

  if (amt.ibLow && amt.ibLow > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.ibLow,
      color: '#fb923c',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: amt.breakDirection === 'DOWN' ? 'IB LOW [BROKEN ↓]' : 'IB LOW',
    }));
  }
};

/**
 * Add VWAP lines with slope-based coloring
 */
const addVWAPLines = (
  candleSeries: ISeriesApi<"Candlestick">,
  amt: AMTAnalysis,
  stableData: OHLCData[],
  amtLinesRef: React.MutableRefObject<IPriceLine[]>
) => {
  if (!amt.sessionVwap || amt.sessionVwap <= 0) return;

  // Compute VWAP slope from recent candles to determine directional colour
  let vwapColour = '#06b6d4'; // Default cyan
  const recentVwaps = stableData.slice(-10).map(d => d.vwap).filter(v => v > 0);
  
  if (recentVwaps.length >= 3) {
    const firstHalf = recentVwaps.slice(0, Math.floor(recentVwaps.length / 2));
    const secondHalf = recentVwaps.slice(Math.floor(recentVwaps.length / 2));
    const avgFirst = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length;
    const avgSecond = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length;
    const slope = avgSecond - avgFirst;
    const threshold = avgFirst * 0.001; // 0.1% change threshold
    
    if (slope > threshold) {
      vwapColour = '#22c55e'; // Green: rising VWAP
    } else if (slope < -threshold) {
      vwapColour = '#ef4444'; // Red: declining VWAP
    }
  }

  // Main VWAP line
  amtLinesRef.current.push(candleSeries.createPriceLine({
    price: amt.sessionVwap,
    color: vwapColour,
    lineWidth: 2,
    lineStyle: LineStyle.Solid,
    axisLabelVisible: true,
    title: vwapColour === '#22c55e' ? 'VWAP ↑' : vwapColour === '#ef4444' ? 'VWAP ↓' : 'VWAP',
  }));

  // ±1σ bands
  if (amt.vwapUpper1 && amt.vwapUpper1 > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.vwapUpper1,
      color: '#06b6d4',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: '+1σ',
    }));
  }

  if (amt.vwapLower1 && amt.vwapLower1 > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.vwapLower1,
      color: '#06b6d4',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: '-1σ',
    }));
  }

  // ±2σ bands (extreme fade zones)
  if (amt.vwapUpper2 && amt.vwapUpper2 > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.vwapUpper2,
      color: '#0891b2',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: '+2σ FADE',
    }));
  }

  if (amt.vwapLower2 && amt.vwapLower2 > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.vwapLower2,
      color: '#0891b2',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: '-2σ FADE',
    }));
  }
};

/**
 * Add prior day VAH/VAL/POC lines
 */
const addPriorDayLines = (
  candleSeries: ISeriesApi<"Candlestick">,
  amt: AMTAnalysis,
  amtLinesRef: React.MutableRefObject<IPriceLine[]>
) => {
  if (amt.priorVah && amt.priorVah > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.priorVah,
      color: '#6b7280',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Prior VAH',
    }));
  }

  if (amt.priorVal && amt.priorVal > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.priorVal,
      color: '#6b7280',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Prior VAL',
    }));
  }

  if (amt.priorPoc && amt.priorPoc > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.priorPoc,
      color: '#9ca3af',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Prior POC',
    }));
  }
};

/**
 * Add leg profile lines (LEG-POC, LEG-VAH, LEG-VAL, Leg LVN)
 */
const addLegLines = (
  candleSeries: ISeriesApi<"Candlestick">,
  amt: AMTAnalysis,
  amtLinesRef: React.MutableRefObject<IPriceLine[]>
) => {
  if (amt.legPoc > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.legPoc,
      color: '#FF9900',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: 'LEG-POC',
    }));
  }

  if (amt.legVah > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.legVah,
      color: '#FF6600',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'LEG-VAH',
    }));
  }

  if (amt.legVal > 0) {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: amt.legVal,
      color: '#FF6600',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'LEG-VAL',
    }));
  }

  // Leg LVN lines (warm yellow dotted)
  amt.legLvns?.forEach((lvn: number) => {
    amtLinesRef.current.push(candleSeries.createPriceLine({
      price: lvn,
      color: '#fbbf24',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: 'Leg LVN',
    }));
  });
};

/**
 * Update trade markers (entry, exit, IB break, CVD divergence, etc.)
 */
const updateTradeMarkers = (
  candleSeries: ISeriesApi<"Candlestick">,
  stableData: OHLCData[],
  amt: AMTAnalysis | null,
  positions: TradePosition[],
  closedTrades: TradePosition[]
) => {
  const markers: SeriesMarker<UTCTimestamp>[] = [];

  // Entry markers from open positions
  positions.forEach(pos => {
    markers.push({
      time: (new Date(pos.entryTime).getTime() / 1000 + 19800) as UTCTimestamp,
      position: pos.side === 'LONG' ? 'belowBar' : 'aboveBar',
      color: pos.side === 'LONG' ? '#10b981' : '#ef4444',
      shape: pos.side === 'LONG' ? 'arrowUp' : 'arrowDown',
      text: `${pos.side} @${pos.entryPrice.toFixed(2)}`,
      size: 2,
    });
  });

  // Entry + exit markers from closed trades
  closedTrades.forEach(trade => {
    markers.push({
      time: (new Date(trade.entryTime).getTime() / 1000 + 19800) as UTCTimestamp,
      position: trade.side === 'LONG' ? 'belowBar' : 'aboveBar',
      color: trade.side === 'LONG' ? '#10b981' : '#ef4444',
      shape: trade.side === 'LONG' ? 'arrowUp' : 'arrowDown',
      text: `${trade.side} @${trade.entryPrice.toFixed(2)}`,
      size: 1,
    });

    if (trade.exitTime && trade.exitPrice) {
      const reason = trade.closeReason || 'EXIT';
      const pnlStr = trade.pnl >= 0 ? `+${trade.pnl.toFixed(2)}` : trade.pnl.toFixed(2);
      markers.push({
        time: (new Date(trade.exitTime).getTime() / 1000 + 19800) as UTCTimestamp,
        position: trade.side === 'LONG' ? 'aboveBar' : 'belowBar',
        color: trade.pnl >= 0 ? '#10b981' : '#ef4444',
        shape: 'circle',
        text: `${reason} ${pnlStr}`,
        size: 1,
      });
    }
  });

  // IB Break marker
  if (amt?.breakDirection && amt.breakLevel && amt.breakLevel > 0) {
    addIBBreakMarker(markers, stableData, amt.breakDirection, amt.breakLevel);
  }

  // CVD Divergence markers
  if (amt?.cvdDivergence && stableData.length > 0) {
    addCVDDivergenceMarkers(markers, stableData, amt.cvdDivergence);
  }

  // Acceptance/Rejection annotations
  if (stableData.length > 0 && amt) {
    addAcceptanceRejectionMarkers(markers, stableData, amt);
  }

  // Sort markers by time (required by lightweight-charts)
  markers.sort((a, b) => (a.time as number) - (b.time as number));
  candleSeries.setMarkers(markers);
};

/**
 * Add IB break marker on the breaking candle
 */
const addIBBreakMarker = (
  markers: SeriesMarker<UTCTimestamp>[],
  stableData: OHLCData[],
  breakDir: string,
  breakLevel: number
) => {
  for (let i = 1; i < stableData.length; i++) {
    const prev = stableData[i - 1];
    const curr = stableData[i];
    const crossedUp = breakDir === 'UP' && prev.close <= breakLevel && curr.close > breakLevel;
    const crossedDown = breakDir === 'DOWN' && prev.close >= breakLevel && curr.close < breakLevel;
    
    if (crossedUp || crossedDown) {
      markers.push({
        time: (new Date(curr.time).getTime() / 1000 + 19800) as UTCTimestamp,
        position: breakDir === 'UP' ? 'belowBar' : 'aboveBar',
        color: breakDir === 'UP' ? '#10b981' : '#ef4444',
        shape: breakDir === 'UP' ? 'arrowUp' : 'arrowDown',
        text: `IB BREAK ${breakDir} @${breakLevel.toFixed(2)}`,
        size: 2,
      });
      break; // Only mark the first break
    }
  }
};

/**
 * Add CVD divergence markers on recent candles
 */
const addCVDDivergenceMarkers = (
  markers: SeriesMarker<UTCTimestamp>[],
  stableData: OHLCData[],
  cvdDivergence: string
) => {
  const recentCount = Math.min(3, stableData.length);
  for (let i = stableData.length - recentCount; i < stableData.length; i++) {
    const candle = stableData[i];
    const isBearishDiv = cvdDivergence.includes('BEARISH');
    const isInitial = i === (stableData.length - recentCount);
    
    markers.push({
      time: (new Date(candle.time).getTime() / 1000 + 19800) as UTCTimestamp,
      position: isBearishDiv ? 'aboveBar' : 'belowBar',
      color: isInitial ? '#f97316' : 'rgba(249, 115, 22, 0.4)',
      shape: 'circle',
      text: isInitial ? '⚡CVD DIV' : 'div',
      size: 1,
    });
  }
};

/**
 * Add acceptance/rejection markers at key levels
 */
const addAcceptanceRejectionMarkers = (
  markers: SeriesMarker<UTCTimestamp>[],
  stableData: OHLCData[],
  amt: AMTAnalysis
) => {
  const lastCandle = stableData[stableData.length - 1];
  const lastTime = (new Date(lastCandle.time).getTime() / 1000 + 19800) as UTCTimestamp;

  if (amt.acceptanceAbove) {
    markers.push({
      time: lastTime,
      position: 'aboveBar',
      color: '#10b981',
      shape: 'arrowUp',
      text: '✅ ACC ↑',
      size: 1,
    });
  }

  if (amt.acceptanceBelow) {
    markers.push({
      time: lastTime,
      position: 'belowBar',
      color: '#ef4444',
      shape: 'arrowDown',
      text: '✅ ACC ↓',
      size: 1,
    });
  }

  if (amt.rejectionAtHigh) {
    markers.push({
      time: lastTime,
      position: 'aboveBar',
      color: '#f59e0b',
      shape: 'arrowDown',
      text: '↓ REJ',
      size: 1,
    });
  }

  if (amt.rejectionAtLow) {
    markers.push({
      time: lastTime,
      position: 'belowBar',
      color: '#f59e0b',
      shape: 'arrowUp',
      text: '↑ REJ',
      size: 1,
    });
  }
};

/**
 * Update position price lines (entry, SL, TP)
 */
const updatePositionLines = (
  candleSeries: ISeriesApi<"Candlestick">,
  positions: TradePosition[],
  activePriceLinesRef: React.MutableRefObject<Map<string, IPriceLine[]>>
) => {
  // Remove lines for closed positions
  const currentPosIds = new Set(positions.map(p => p.id));
  activePriceLinesRef.current.forEach((lines, id) => {
    if (!currentPosIds.has(id)) {
      lines.forEach(l => candleSeries.removePriceLine(l));
      activePriceLinesRef.current.delete(id);
    }
  });

  // Add lines for open positions
  positions.forEach(pos => {
    if (activePriceLinesRef.current.has(pos.id)) return;

    const lines: IPriceLine[] = [];
    const mainColor = pos.source === 'PREDICTION' ? '#a855f7' : '#3b82f6';

    lines.push(candleSeries.createPriceLine({
      price: pos.entryPrice,
      color: mainColor,
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: `${pos.source} ${pos.side}`,
    }));

    lines.push(candleSeries.createPriceLine({
      price: pos.stopLoss,
      color: '#ef4444',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'SL',
    }));

    lines.push(candleSeries.createPriceLine({
      price: pos.takeProfit,
      color: '#10b981',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'TP',
    }));

    activePriceLinesRef.current.set(pos.id, lines);
  });
};
