
import React, { useEffect, useRef, useState, useMemo } from 'react';
import {
  createChart,
  ColorType,
  IChartApi,
  ISeriesApi,
  CrosshairMode,
  UTCTimestamp,
  LineStyle,
  IPriceLine,
  SeriesMarker,
} from 'lightweight-charts';
import { OHLCData, ChartConfig, TradeSignal, TradePosition, AIAnalysis, AMTAnalysis, ChartMode, AggressivePrint } from '../types';
import { Brain, Cpu, MessageSquare, ChevronDown, ChevronUp } from 'lucide-react';
import { sanitizeRationale } from '../utils/textSanitizer';
import DecisionCard from './chart/DecisionCard';

// Extracted chart components (Phase 3)
import {
  generateAMTPriceLines,
  PriceLineConfig,
  AMTLevelsOverlayOptions,
} from './chart/AMTLevelsOverlay';
import {
  generateAllExecutionMarkers,
  ChartMarker,
  ExecutionMarkersOptions,
} from './chart/ExecutionMarkersManager';
import {
  transformToCandleData,
  validateCandleData,
  CandleDataPoint,
} from './chart/CandleSeriesManager';
import {
  transformToVolumeData,
  validateVolumeData,
  getVolumeSeriesConfig,
  VolumeDataPoint,
} from './chart/VolumeSeriesManager';
import {
  generateProfileConfig,
  validateProfileData,
  ProfileLevel,
  ProfileRenderOptions,
} from './chart/ProfileHistogram';
import {
  calculateAllSessionZones,
  DEFAULT_SESSION_PHASES,
  SessionZoneConfig,
} from './chart/SessionPhaseMarkers';
import {
  buildCrosshairTooltip,
  validateCrosshairData,
  CrosshairData,
} from './chart/CrosshairManager';

interface ChartSceneProps {
  data: OHLCData[];
  predictions: OHLCData[];
  config: ChartConfig;
  positions: TradePosition[];
  closedTrades?: TradePosition[];
  aiAnalysis?: AIAnalysis | null;
  amtAnalysis?: AMTAnalysis | null;
  mode?: ChartMode;
  tickBus?: EventTarget;
  symbol?: string;
}

// Helper to convert Hex to RGBA for intensity
const hexToRgba = (hex: string, alpha: number) => {
  let r = 0, g = 0, b = 0;
  if (hex.length === 4) {
    r = parseInt("0x" + hex[1] + hex[1]);
    g = parseInt("0x" + hex[2] + hex[2]);
    b = parseInt("0x" + hex[3] + hex[3]);
  } else if (hex.length === 7) {
    r = parseInt("0x" + hex[1] + hex[2]);
    g = parseInt("0x" + hex[3] + hex[4]);
    b = parseInt("0x" + hex[5] + hex[6]);
  }
  return `rgba(${r},${g},${b},${alpha})`;
};

/**
 * Shallow array equality check
 * Returns true if arrays have same length and all elements are strictly equal
 * O(n) complexity vs JSON.stringify O(n²)
 */
function arraysShallowEqual<T>(a: T[] | undefined, b: T[] | undefined): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.length !== b.length) return false;
  
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  
  return true;
}

const ChartScene: React.FC<ChartSceneProps> = ({
  data,
  predictions,
  config,
  positions,
  closedTrades = [],
  aiAnalysis,
  amtAnalysis,
  mode = 'STANDARD',
  tickBus,
  symbol,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const predictionSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const activePriceLinesRef = useRef<Map<string, IPriceLine[]>>(new Map());
  const amtLinesRef = useRef<IPriceLine[]>([]);
  const initializedRef = useRef(false);

  // Memoize amtAnalysis to prevent overlay redraws when profile data hasn't changed.
  // The backend sends new AMT objects on every tick, but profile/legProfile arrays
  // only change on candle boundaries. We fingerprint the visually-relevant fields
  // so the expensive canvas overlay only redraws when actual drawing data changes.
  const prevAmtRef = useRef<AMTAnalysis | null | undefined>(null);
  const stableAmtAnalysis = useMemo(() => {
    const prev = prevAmtRef.current;
    if (amtAnalysis === prev) return prev;
    if (!amtAnalysis) { prevAmtRef.current = amtAnalysis; return amtAnalysis; }
    if (!prev) { prevAmtRef.current = amtAnalysis; return amtAnalysis; }

    // Compare fields that affect overlay drawing: profiles, levels, aggressive prints
    // OPTIMIZED: Use shallow comparison instead of JSON.stringify (O(n) vs O(n²))
    const profileSame = arraysShallowEqual(prev.profile, amtAnalysis.profile);
    const legSame = arraysShallowEqual(prev.legProfile, amtAnalysis.legProfile);
    const printsSame = arraysShallowEqual(prev.aggressivePrints, amtAnalysis.aggressivePrints);
    const levelsSame = prev.poc === amtAnalysis.poc &&
      prev.valueAreaHigh === amtAnalysis.valueAreaHigh &&
      prev.valueAreaLow === amtAnalysis.valueAreaLow &&
      prev.legPoc === amtAnalysis.legPoc &&
      prev.legVah === amtAnalysis.legVah &&
      prev.legVal === amtAnalysis.legVal &&
      prev.sessionVwap === amtAnalysis.sessionVwap;

    if (profileSame && legSame && printsSame && levelsSame) {
      return prev; // Return old reference to skip redraw
    }

    prevAmtRef.current = amtAnalysis;
    return amtAnalysis;
  }, [amtAnalysis]);

  // Stabilize data reference — only update when array length changes (new candle boundary).
  // Prevents canvas overlay from redrawing on every intra-candle tick update.
  const stableData = useMemo(() => data, [data.length]);

  // 1. Initialize Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#6b7a99', // glassy-text-tertiary
      },
      grid: {
        vertLines: { color: 'rgba(42, 53, 80, 0.2)' }, // glassy-border-default 20% opacity
        horzLines: { color: 'rgba(42, 53, 80, 0.2)' },
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      timeScale: {
        borderColor: '#2a3550', // glassy-border-default
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
      },
      rightPriceScale: {
        borderColor: '#2a3550', // glassy-border-default
        autoScale: true,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: config.bullColor,
      downColor: config.bearColor,
      borderVisible: false,
      wickUpColor: config.bullColor,
      wickDownColor: config.bearColor,
    });

    const predSeries = chart.addCandlestickSeries({
      upColor: '#7c5cfc', // glassy-ai-primary
      downColor: '#6048d0', // glassy-ai-muted
      borderVisible: true,
      borderColor: '#7c5cfc',
      wickUpColor: '#7c5cfc',
      wickDownColor: '#7c5cfc',
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    predictionSeriesRef.current = predSeries;

    chartRef.current.priceScale('right').applyOptions({
      scaleMargins: {
        top: 0.15,
        bottom: 0.15,
      }
    });

    chartRef.current.applyOptions({
      timeScale: {
        barSpacing: 6,
        minBarSpacing: 2,
        // Allow free scrolling on both sides
        fixLeftEdge: false,
        fixRightEdge: false,
        rightOffset: 5,
        timeVisible: true,
        secondsVisible: true,
        // Handle irregular tick data better
        shiftVisibleRangeOnNewBar: false,
      }
    });

    candleSeries.applyOptions({ visible: true });
    predSeries.applyOptions({ visible: true });

    const resizeObserver = new ResizeObserver(entries => {
      if (entries.length === 0 || !entries[0].contentRect) return;
      if (entries[0].contentRect.width === 0 || entries[0].contentRect.height === 0) return;

      const { width, height } = entries[0].contentRect;
      chart.applyOptions({ width, height });

      if (overlayRef.current) {
        overlayRef.current.width = width;
        overlayRef.current.height = height;
      }
    });

    resizeObserver.observe(chartContainerRef.current);

    // Initial Data Load
    // Use extracted CandleSeriesManager for data transformation
    const validation = validateCandleData(data as any);
    if (!validation.isValid) {
      console.error('Invalid candle data:', validation.errors);
    }

    const candleData = transformToCandleData(data);
    candleSeries.setData(candleData.map(d => ({ ...d, time: d.time as any })));

    // Use extracted VolumeSeriesManager for volume data
    const volumeData = transformToVolumeData(data);
    const volumeValidation = validateVolumeData(volumeData);
    if (!volumeValidation.length) {
      volumeSeries.setData(volumeData.map(d => ({ ...d, time: d.time as any })));
    }

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      initializedRef.current = false;
    };
  }, []); // Only runs once on mount

  // 2. Realtime Subscription via EventBus
  useEffect(() => {
    if (!tickBus || !symbol || !candleSeriesRef.current || !volumeSeriesRef.current) return;

    const handleTick = (e: Event) => {
      const customEvent = e as CustomEvent;
      if (customEvent.detail.symbol !== symbol) return;

      const { tick } = customEvent.detail;

      // Common Time
      const unixTime = (new Date(tick.time).getTime() / 1000 + 19800) as any;

      // CRITICAL: In server-mode, sometimes delayed ticks can arrive.
      // Lightweight charts will crash if we update with an older timestamp.
      // The hook now drops stale ticks, but we wrap in try-catch for total UI safety.
      try {
        // Update Candlestick directly Native API
        candleSeriesRef.current?.update({
          ...tick,
          time: unixTime
        } as any);

        // Update Volume Native API
        volumeSeriesRef.current?.update({
          time: unixTime,
          value: tick.volume,
          color: tick.close >= tick.open ? '#22c55e80' : '#ef444480'
        });
      } catch (e) {
        console.warn('[ChartScene] Ignored stale/out-of-order tick update:', tick.time);
      }
    };

    tickBus.addEventListener('tick', handleTick);

    // Gap fill event handler - updates chart with historical candles
    const handleGapFill = (e: Event) => {
      const customEvent = e as CustomEvent;
      if (customEvent.detail.symbol !== symbol) return;

      const candles = customEvent.detail.candles || [];
      console.log(`[ChartScene] Gap fill: updating chart with ${candles.length} historical candles`);

      // Update chart with each historical candle
      candles.forEach((candle: any) => {
        try {
          const time = (new Date(candle.time).getTime() / 1000 + 19800) as any;
          
          // Update candlestick
          candleSeriesRef.current?.update({
            time,
            open: candle.open,
            high: candle.high,
            low: candle.low,
            close: candle.close,
          });

          // Update volume
          volumeSeriesRef.current?.update({
            time,
            value: candle.volume,
            color: candle.close >= candle.open ? '#22c55e80' : '#ef444480',
          });
        } catch (e) {
          console.warn('[ChartScene] Failed to update gap fill candle:', candle.time, e);
        }
      });
    };

    tickBus.addEventListener('gap_fill', handleGapFill);

    return () => {
      tickBus.removeEventListener('tick', handleTick);
      tickBus.removeEventListener('gap_fill', handleGapFill);
    };
  }, [tickBus, symbol, mode]);

  // Handle mode/config changes dynamically without remount
  useEffect(() => {
    if (!candleSeriesRef.current || !predictionSeriesRef.current) return;

    candleSeriesRef.current.applyOptions({
      upColor: config.bullColor,
      downColor: config.bearColor,
      wickUpColor: config.bullColor,
      wickDownColor: config.bearColor,
      borderVisible: false
    });
    predictionSeriesRef.current.applyOptions({ visible: true });
  }, [mode, config.bullColor, config.bearColor]);

  // 3. Canvas Overlay Drawing
  useEffect(() => {
    if (!chartRef.current || !candleSeriesRef.current || !overlayRef.current) return;

    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    const canvas = overlayRef.current;
    const ctx = canvas.getContext('2d');

    const drawOverlay = () => {
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      try {
        if (stableAmtAnalysis) {
          // P1-1: VA shaded box (VAH-VAL fill) — draw FIRST as background layer
          if (stableAmtAnalysis.valueAreaHigh > 0 && stableAmtAnalysis.valueAreaLow > 0) {
            drawVAShadedBox(ctx, canvas, chart, series, stableAmtAnalysis);
          }
          // P1-6: Session Open + IB Close vertical markers — also background layer
          if (stableData.length > 0) {
            drawTimeMarkers(ctx, canvas, chart, series, stableData, stableAmtAnalysis);
          }
          // P2: IB Break Retest Zone Box — forward-looking box after IB break
          if (stableAmtAnalysis.breakDirection && stableAmtAnalysis.breakLevel > 0 && stableData.length > 0) {
            drawIBRetestZone(ctx, canvas, chart, series, stableData, stableAmtAnalysis);
          }
          if (config.showVolumeProfile) {
            drawVolumeProfile(ctx, canvas, series, stableAmtAnalysis, config);
          }
          // Render Aggressive Bubbles (Fabio Valentini Style)
          if (stableAmtAnalysis.aggressivePrints && stableAmtAnalysis.aggressivePrints.length > 0) {
            drawAggressiveBubbles(ctx, canvas, chart, series, stableAmtAnalysis.aggressivePrints, config);
          }
        }
      } catch (e) {
        console.error("Overlay draw error", e);
      }
    };

    // Draw once immediately when data changes
    drawOverlay();

    // Subscribe to chart pan/zoom events to redraw
    const onVisibleRangeChange = () => drawOverlay();
    chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleRangeChange);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleRangeChange);
    };

  }, [stableAmtAnalysis, stableData, config, mode]);


  // Helper: Draw Aggressive Bubbles
  const drawAggressiveBubbles = (
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    chart: IChartApi,
    series: ISeriesApi<"Candlestick">,
    prints: AggressivePrint[],
    cfg: ChartConfig
  ) => {
    const timeScale = chart.timeScale();
    const visibleRange = timeScale.getVisibleLogicalRange();
    if (!visibleRange) return;

    prints.forEach(print => {
      // Convert time string to timestamp
      const printTime = (new Date(print.time).getTime() / 1000 + 19800) as UTCTimestamp;

      // Coordinate conversion
      const x = timeScale.timeToCoordinate(printTime);
      const y = series.priceToCoordinate(print.price);

      if (x === null || y === null || x < 0 || x > canvas.width) return;

      // Radius based on volume (logarithmic scale)
      // Adjust 3 and 1.5 multiplier as needed for visual balance
      const radius = Math.min(25, Math.max(2, Math.log(print.volume) * 2.5));

      const isBuy = print.side === 'BUY';
      const color = isBuy ? cfg.bullColor : cfg.bearColor;

      // Draw Bubble
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, 2 * Math.PI);

      // Gradient Fill
      const grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
      grad.addColorStop(0, hexToRgba(color, 0.4));
      grad.addColorStop(1, hexToRgba(color, 0.1));

      ctx.fillStyle = grad;
      ctx.fill();

      // Border
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Only draw text if bubble is large enough
      if (radius > 8) {
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 9px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        
        // Show side (B/S) + volume
        ctx.fillText(`${print.side === 'BUY' ? 'B' : 'S'} ${formatK(print.volume)}`, x, y);
        
        // Context label for very large prints
        if (radius > 15) {
          ctx.font = '7px sans-serif';
          ctx.fillText(`INSTITUTIONAL`, x, y + 8);
        }
      }
    });
  };

  // P1-1: Draw VA shaded box (semi-transparent fill between VAH and VAL)
  const drawVAShadedBox = (
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    chart: IChartApi,
    series: ISeriesApi<"Candlestick">,
    amt: AMTAnalysis,
  ) => {
    const vah = amt.valueAreaHigh;
    const val = amt.valueAreaLow;
    if (vah <= 0 || val <= 0) return;

    const vahY = series.priceToCoordinate(vah);
    const valY = series.priceToCoordinate(val);
    if (vahY === null || valY === null) return;

    const leftEdge = 0;
    const rightEdge = canvas.width;

    // Semi-transparent blue fill for Value Area
    ctx.fillStyle = 'rgba(59, 130, 246, 0.10)'; // 10% opacity blue
    ctx.fillRect(leftEdge, Math.min(vahY, valY), rightEdge - leftEdge, Math.abs(valY - vahY));

    // VAH and VAL border lines on the fill
    ctx.strokeStyle = 'rgba(59, 130, 246, 0.25)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(leftEdge, vahY);
    ctx.lineTo(rightEdge, vahY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(leftEdge, valY);
    ctx.lineTo(rightEdge, valY);
    ctx.stroke();
    ctx.setLineDash([]);
  };

  // P1-6: Draw Session Open (9:15) and IB Close (10:15) vertical time markers
  const drawTimeMarkers = (
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    chart: IChartApi,
    series: ISeriesApi<"Candlestick">,
    data: OHLCData[],
    amt: AMTAnalysis,
  ) => {
    if (data.length < 2) return;

    // Convert OHLCData time string to chart timestamp (same as toIST)
    const toChartTs = (timeStr: string) => {
      const unix = new Date(timeStr).getTime() / 1000;
      return unix + 19800; // IST offset
    };

    // Find the X coordinate for a specific IST hour:minute
    const findTimeX = (targetHour: number, targetMinute: number): number | null => {
      for (const candle of data) {
        const chartTs = toChartTs(candle.time as string);
        // The chart timestamp is UTC+IST_offset, so getUTCHours gives IST hours
        const d = new Date(chartTs * 1000);
        const istHour = d.getUTCHours();
        const istMinute = d.getUTCMinutes();
        if (istHour === targetHour && istMinute === targetMinute) {
          const coord = chart.timeScale().timeToCoordinate(chartTs as UTCTimestamp);
          return coord;
        }
      }
      return null;
    };

    // Find X coordinate for a time, or use canvas edge if not found
    const findTimeXOrEdge = (targetHour: number, targetMinute: number, defaultX: number): number => {
      return findTimeX(targetHour, targetMinute) ?? defaultX;
    };

    const drawVerticalLine = (x: number | null, label: string, color: string) => {
      if (x === null || x < 0 || x > canvas.width) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
      ctx.setLineDash([]);

      // Label at top
      ctx.fillStyle = color;
      ctx.font = '9px monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(label, x, 4);
    };

    const drawShadedZone = (startX: number | null, endX: number | null, color: string, label: string, labelY: number = 16) => {
      if (startX === null || endX === null || endX <= startX) return;
      ctx.fillStyle = color;
      ctx.fillRect(startX, 0, endX - startX, canvas.height);
      // Label
      ctx.fillStyle = 'rgba(255,255,255,0.15)';
      ctx.font = '8px monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(label, (startX + endX) / 2, labelY);
    };

    // Session Open: 9:15 AM IST
    const openX = findTimeX(9, 15);
    drawVerticalLine(openX, 'SESSION OPEN 9:15', 'rgba(255,255,255,0.3)');

    // IB Close: 10:15 AM IST
    const ibCloseX = findTimeX(10, 15);
    drawVerticalLine(ibCloseX, 'IB CLOSE 10:15', 'rgba(251,146,60,0.5)');

    // === P2: Session Phase Background Shading ===
    
    // 1. IB Formation Period (9:15-10:15) - amber tint
    if (openX !== null && ibCloseX !== null) {
      drawShadedZone(openX, ibCloseX, 'rgba(251,191,36,0.03)', 'IB FORMATION', 28);
    }

    // 2. Lunch Dead Zone (12:00-14:00) - grey tint
    const lunchStartX = findTimeX(12, 0);
    const lunchEndX = findTimeX(14, 0);
    if (lunchStartX !== null && lunchEndX !== null) {
      drawShadedZone(lunchStartX, lunchEndX, 'rgba(100,100,100,0.04)', 'LUNCH ZONE', 16);
    }

    // 3. Closing Risk Zone (14:45-15:30) - light red tint
    const closeStartX = findTimeX(14, 45);
    const closeEndX = findTimeX(15, 30);
    if (closeStartX !== null && closeEndX !== null) {
      drawShadedZone(closeStartX, closeEndX, 'rgba(239,68,68,0.04)', 'CLOSING RISK', 40);
    }
  };

  // P2: Draw IB Break Retest Zone Box
  const drawIBRetestZone = (
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    chart: IChartApi,
    series: ISeriesApi<"Candlestick">,
    data: OHLCData[],
    amt: AMTAnalysis,
  ) => {
    const breakDir = amt.breakDirection;
    const breakLevel = amt.breakLevel;
    if (!breakDir || breakLevel <= 0 || data.length < 2) return;

    // Find the break candle
    let breakCandleIndex = -1;
    for (let i = 1; i < data.length; i++) {
      const prev = data[i - 1];
      const curr = data[i];
      const crossedUp = breakDir === 'UP' && prev.close <= breakLevel && curr.close > breakLevel;
      const crossedDown = breakDir === 'DOWN' && prev.close >= breakLevel && curr.close < breakLevel;
      if (crossedUp || crossedDown) {
        breakCandleIndex = i;
        break;
      }
    }

    if (breakCandleIndex < 0) return;

    // Convert break candle time to chart coordinate
    const breakCandle = data[breakCandleIndex];
    const toChartTs = (timeStr: string) => new Date(timeStr).getTime() / 1000 + 19800;
    const breakTs = toChartTs(breakCandle.time as string) as UTCTimestamp;
    const breakX = chart.timeScale().timeToCoordinate(breakTs);
    if (breakX === null) return;

    // Current price (last candle)
    const currentPrice = data[data.length - 1].close;
    const currentY = series.priceToCoordinate(currentPrice);
    if (currentY === null) return;

    // Retest zone: break level ± 0.3%
    const zoneSize = breakLevel * 0.003;
    const zoneTop = breakLevel + zoneSize;
    const zoneBottom = breakLevel - zoneSize;
    const zoneTopY = series.priceToCoordinate(zoneTop);
    const zoneBottomY = series.priceToCoordinate(zoneBottom);
    if (zoneTopY === null || zoneBottomY === null) return;

    // Zone extends from break candle to right edge
    const rightEdge = canvas.width;
    const zoneLeft = breakX;
    const zoneWidth = rightEdge - zoneLeft;

    // Check if current price is in the retest zone
    const inRetestZone = currentPrice >= zoneBottom && currentPrice <= zoneTop;

    // Draw zone box
    ctx.fillStyle = inRetestZone ? 'rgba(251,191,36,0.08)' : 'rgba(251,191,36,0.04)';
    ctx.fillRect(zoneLeft, Math.min(zoneTopY, zoneBottomY), zoneWidth, Math.abs(zoneBottomY - zoneTopY));

    // Zone border
    ctx.strokeStyle = inRetestZone ? 'rgba(251,191,36,0.5)' : 'rgba(251,191,36,0.2)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(zoneLeft, zoneTopY);
    ctx.lineTo(rightEdge, zoneTopY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(zoneLeft, zoneBottomY);
    ctx.lineTo(rightEdge, zoneBottomY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Label
    ctx.fillStyle = inRetestZone ? 'rgba(251,191,36,0.8)' : 'rgba(251,191,36,0.4)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    const label = inRetestZone ? '⏳ RETEST ZONE ACTIVE' : 'RETEST WATCH';
    ctx.fillText(label, zoneLeft + 4, Math.min(zoneTopY, zoneBottomY) + 4);
  };


  // Helper: Draw a single VP profile on the RIGHT side of the chart (glassy style)
  const drawProfileBars = (
    ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement,
    series: ISeriesApi<"Candlestick">, profile: { price: number; volume: number; buyVolume: number; sellVolume: number }[],
    maxWidthPct: number, xOffset: number, bullColor: string, bearColor: string, useDirectionColors: boolean,
    hvnPrices?: number[], lvnPrices?: number[], vahPrice?: number, valPrice?: number, pocPrice?: number
  ) => {
    if (!profile || profile.length === 0) {
      return;
    }
    const maxVol = Math.max(...profile.map(p => p.volume));
    if (maxVol === 0) {
      return;
    }
    const maxBarWidth = canvas.width * maxWidthPct;
    const widthScale = maxBarWidth / maxVol;
    const step = profile.length > 1 ? Math.abs(profile[1].price - profile[0].price) : 0;
    const rightEdge = canvas.width - 50;
    const tolerance = step > 0 ? step * 0.6 : 1;

    const isNear = (price: number, targets: number[] | undefined) =>
      targets?.some(t => Math.abs(price - t) < tolerance) ?? false;
    const inValueArea = (price: number) =>
      vahPrice != null && valPrice != null && price >= valPrice && price <= vahPrice;
    const isPoc = (price: number) =>
      pocPrice != null && Math.abs(price - pocPrice) < tolerance;

    // Value Area shaded background
    if (vahPrice != null && valPrice != null) {
      const vahY = series.priceToCoordinate(vahPrice);
      const valY = series.priceToCoordinate(valPrice);
      if (vahY !== null && valY !== null) {
        const vaGrad = ctx.createLinearGradient(rightEdge - xOffset - maxBarWidth, 0, rightEdge - xOffset, 0);
        vaGrad.addColorStop(0, 'rgba(59,130,246,0.0)');
        vaGrad.addColorStop(0.5, 'rgba(59,130,246,0.04)');
        vaGrad.addColorStop(1, 'rgba(59,130,246,0.08)');
        ctx.fillStyle = vaGrad;
        ctx.fillRect(rightEdge - xOffset - maxBarWidth, Math.min(vahY, valY), maxBarWidth, Math.abs(valY - vahY));
      }
    }

    profile.forEach(level => {
      const y = series.priceToCoordinate(level.price);
      if (y === null) return;
      let barHeight = 2;
      if (step > 0) {
        const topY = series.priceToCoordinate(level.price + (step / 2));
        const bottomY = series.priceToCoordinate(level.price - (step / 2));
        if (topY !== null && bottomY !== null) {
          barHeight = Math.max(1, Math.abs(bottomY - topY) + 0.5);
        }
      }
      const barWidth = level.volume * widthScale;
      const x = rightEdge - xOffset - barWidth;

      // Determine zone type for color enhancement
      const isHvn = isNear(level.price, hvnPrices);
      const isLvn = isNear(level.price, lvnPrices);
      const isVA = inValueArea(level.price);
      const isP = isPoc(level.price);

      // Base color selection
      let baseColor: string;
      let baseAlpha: number;
      if (useDirectionColors) {
        const isBullish = level.buyVolume > level.sellVolume;
        baseColor = isBullish ? bullColor : bearColor;
      } else {
        baseColor = bullColor;
      }

      // Alpha and glow based on zone
      if (isP) {
        baseAlpha = 0.85;
      } else if (isHvn) {
        baseAlpha = 0.65;
      } else if (isLvn) {
        baseAlpha = 0.18;
      } else if (isVA) {
        baseAlpha = 0.45;
      } else {
        baseAlpha = 0.30;
      }

      // Glassy gradient fill (left=transparent → right=color)
      const grad = ctx.createLinearGradient(x, 0, x + barWidth, 0);
      grad.addColorStop(0, hexToRgba(baseColor, baseAlpha * 0.3));
      grad.addColorStop(0.4, hexToRgba(baseColor, baseAlpha * 0.7));
      grad.addColorStop(1, hexToRgba(baseColor, baseAlpha));
      ctx.fillStyle = grad;
      ctx.fillRect(x, y - barHeight / 2, barWidth, barHeight);

      // Top highlight (glass refraction)
      ctx.fillStyle = `rgba(255,255,255,${baseAlpha * 0.12})`;
      ctx.fillRect(x, y - barHeight / 2, barWidth, Math.max(1, barHeight * 0.3));

      // POC bar: bright edge + glow
      if (isP) {
        ctx.shadowColor = hexToRgba('#facc15', 0.6);
        ctx.shadowBlur = 8;
        ctx.fillStyle = hexToRgba('#facc15', 0.9);
        ctx.fillRect(x, y - barHeight / 2, 2, barHeight);
        ctx.shadowBlur = 0;
      }
      // HVN: bright left edge + subtle glow
      else if (isHvn) {
        ctx.shadowColor = hexToRgba('#22c55e', 0.4);
        ctx.shadowBlur = 6;
        ctx.fillStyle = hexToRgba('#22c55e', 0.7);
        ctx.fillRect(x, y - barHeight / 2, 2, barHeight);
        ctx.shadowBlur = 0;
      }
      // LVN: thin dim edge
      else if (isLvn) {
        ctx.fillStyle = hexToRgba('#f97316', 0.5);
        ctx.fillRect(x, y - barHeight / 2, 1, barHeight);
      }
      // Normal edge
      else {
        ctx.fillStyle = hexToRgba(baseColor, baseAlpha * 0.8);
        ctx.fillRect(x, y - barHeight / 2, 1, barHeight);
      }
    });
  };

  // Helper: Draw vertical label on the right side
  const drawVerticalLabel = (ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, text: string, x: number, color: string) => {
    ctx.save();
    ctx.translate(x, canvas.height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillStyle = color;
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'center';
    ctx.globalAlpha = 0.6;
    ctx.fillText(text, 0, 0);
    ctx.restore();
  };

  // Helper: Draw Volume Profile (session + leg on RIGHT side, controlled by vpMode)
  const drawVolumeProfile = (ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, series: ISeriesApi<"Candlestick">, amt: AMTAnalysis, cfg: ChartConfig) => {
    const mode = cfg.vpMode || 'combined';
    const hasLeg = amt.legProfile && amt.legProfile.length > 0;
    const rightEdge = canvas.width - 50;

    // Session profile (blue-tinted direction bars with HVN/LVN/VA zones)
    if (mode === 'session' || mode === 'combined') {
      const sessionOffset = (hasLeg && mode === 'combined') ? canvas.width * 0.12 : 0;
      drawProfileBars(ctx, canvas, series, amt.profile, 0.15, sessionOffset, '#4488cc', '#cc4444', true,
        amt.hvns, amt.lvns, amt.valueAreaHigh, amt.valueAreaLow, amt.poc);
      drawVerticalLabel(ctx, canvas, 'SESSION PROFILE', rightEdge - sessionOffset - canvas.width * 0.08, '#6699cc');
    }

    // Leg profile (amber/orange bars with leg-specific levels)
    if (hasLeg && (mode === 'leg' || mode === 'combined')) {
      drawProfileBars(ctx, canvas, series, amt.legProfile, 0.10, 0, '#FF9900', '#FF6600', false,
        undefined, amt.legLvns, amt.legVah > 0 ? amt.legVah : undefined, amt.legVal > 0 ? amt.legVal : undefined, amt.legPoc > 0 ? amt.legPoc : undefined);
      drawVerticalLabel(ctx, canvas, 'LEG PROFILE', rightEdge - canvas.width * 0.05, '#FF9900');
    }

    // Show "No displacement" indicator when in leg mode but no leg data
    if (!hasLeg && mode === 'leg') {
      ctx.fillStyle = '#FF990060';
      ctx.font = '11px monospace';
      ctx.fillText('No active displacement leg', rightEdge - 200, 20);
    }
  };

  const formatK = (val: number) => {
    if (isNaN(val)) return '0';
    if (val >= 1000000) return (val / 1000000).toFixed(2) + 'M';
    if (val >= 1000) return (val / 1000).toFixed(1) + 'K';
    return Math.floor(val).toString();
  };

  // 4a. Update Candlestick Series (STANDARD mode)
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !predictionSeriesRef.current) return;

    // Offset UTC → IST (+5:30) so chart axis shows Indian Standard Time
    const IST_OFFSET = 19800; // 5h30m in seconds
    const toIST = (timeStr: string) =>
      (new Date(timeStr).getTime() / 1000 + IST_OFFSET) as UTCTimestamp;

    const formatCandle = (d: OHLCData) => ({
      time: toIST(d.time),
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    });

    const formatVolume = (d: OHLCData) => ({
      time: toIST(d.time),
      value: d.volume,
      // P2: Colour volume bars by delta sign (who won the candle), not candle direction
      // Green delta = buyers won, Red delta = sellers won, Grey = neutral
      color: Math.abs(d.delta || 0) / Math.max(d.volume || 1, 1) > 0.02
        ? (d.delta > 0 ? `${config.bullColor}80` : `${config.bearColor}80`)
        : 'rgba(156,163,175,0.4)', // Grey for neutral delta
    });

    if (data.length > 0) {
      candleSeriesRef.current.setData(data.map(formatCandle));
      volumeSeriesRef.current.setData(data.map(formatVolume));

      if (!initializedRef.current && chartRef.current) {
        chartRef.current.timeScale().scrollToPosition(0, false);
        initializedRef.current = true;
      }
    }

    if (predictions.length > 0) {
      predictionSeriesRef.current.setData(predictions.map(formatCandle));
    } else {
      predictionSeriesRef.current.setData([]);
    }
  }, [data, predictions, config.bullColor, config.bearColor, mode]);

  // 5. Update Markers & Lines
  useEffect(() => {
    if (!candleSeriesRef.current || !chartRef.current) return;

    amtLinesRef.current.forEach(l => candleSeriesRef.current?.removePriceLine(l));
    amtLinesRef.current = [];

    // Add lightweight-chart pricelines
    const vpMode = config.vpMode || 'combined';
    if (stableAmtAnalysis && config.showVolumeProfile) {
      // Use extracted AMTLevelsOverlay component for price line generation
      const amtOptions: AMTLevelsOverlayOptions = {
        mode: mode as any,
        showVolumeProfile: config.showVolumeProfile,
        vpMode: vpMode as any,
      };

      const priceLines = generateAMTPriceLines(stableAmtAnalysis, amtOptions, stableData);

      // Create price lines in chart
      priceLines.forEach(lineConfig => {
        amtLinesRef.current.push(candleSeriesRef.current!.createPriceLine({
          price: lineConfig.price,
          color: lineConfig.color,
          lineWidth: lineConfig.lineWidth as any,
          lineStyle: lineConfig.lineStyle === 'Solid' ? LineStyle.Solid :
                     lineConfig.lineStyle === 'Dashed' ? LineStyle.Dashed : LineStyle.Dotted,
          axisLabelVisible: lineConfig.axisLabelVisible,
          title: lineConfig.title,
        }));
      });
    }

    // Use extracted ExecutionMarkersManager for all marker generation
    const markerOptions: ExecutionMarkersOptions = {
      mode: mode as any,
      maxMarkers: 100,
    };

    const allMarkers = generateAllExecutionMarkers(
      positions,
      closedTrades || [],
      stableData,
      stableAmtAnalysis,
      markerOptions
    );

    // Convert to TradingView format and set markers
    const tvMarkers = allMarkers.map(m => ({
      time: m.time as any,
      position: m.position,
      color: m.color,
      shape: m.shape === 'diamond' ? 'square' : m.shape, // TradingView doesn't support diamond
      text: m.text,
      size: m.size as any,
    }));

    tvMarkers.sort((a, b) => (a.time as number) - (b.time as number));
    candleSeriesRef.current.setMarkers(tvMarkers);

    const currentPosIds = new Set(positions.map(p => p.id));
    activePriceLinesRef.current.forEach((lines, id) => {
      if (!currentPosIds.has(id)) {
        lines.forEach(l => candleSeriesRef.current?.removePriceLine(l));
        activePriceLinesRef.current.delete(id);
      }
    });

    positions.forEach(pos => {
      if (activePriceLinesRef.current.has(pos.id)) return;

      const lines: IPriceLine[] = [];
      const mainColor = pos.source === 'PREDICTION' ? '#a855f7' : '#3b82f6';

      lines.push(candleSeriesRef.current!.createPriceLine({
        price: pos.entryPrice,
        color: mainColor,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `${pos.source} ${pos.side}`,
      }));

      lines.push(candleSeriesRef.current!.createPriceLine({
        price: pos.stopLoss,
        color: '#ef4444',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'SL',
      }));

      lines.push(candleSeriesRef.current!.createPriceLine({
        price: pos.takeProfit,
        color: '#10b981',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'TP',
      }));

      activePriceLinesRef.current.set(pos.id, lines);
    });

  }, [positions, closedTrades, stableAmtAnalysis, config.bullColor, config.bearColor, config.showVolumeProfile, config.vpMode, mode]);

  return (
    <div className="w-full h-full relative bg-[#0f172a] overflow-hidden">
      <div ref={chartContainerRef} className="w-full h-full relative z-10" />
      <canvas ref={overlayRef} className="absolute inset-0 z-20 pointer-events-none" />

      {/* Chart Mode Indicator */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-black/40 backdrop-blur px-3 py-1 rounded-full border border-white/5 text-[10px] text-white/50 z-30 pointer-events-none uppercase tracking-wider">
        STANDARD CANDLESTICKS
      </div>

      {/* Current Decision Card */}
      {(amtAnalysis?.direction || amtAnalysis?.llmThinking) && (
        <div className="absolute top-4 right-4 z-40 w-72 max-h-[80%] overflow-hidden">
          <DecisionCard 
            direction={amtAnalysis.direction || 'FLAT'} 
            setup={amtAnalysis.setup || 'NONE'}
            pLong={amtAnalysis.pLong || 0}
            pShort={amtAnalysis.pShort || 0}
            regime={amtAnalysis.agentRegime || ''}
            timing={amtAnalysis.agentTiming || ''}
            kelly={amtAnalysis.agentKelly || 0}
            rationale={amtAnalysis.agentRationale || amtAnalysis.llmThinking || ''}
            marketState={amtAnalysis.marketState}
            aggression={String(amtAnalysis.aggression ?? '')}
          />
        </div>
      )}
    </div>
  );
};

// Custom comparator to avoid expensive re-renders when only reference identity
// changes but the visually-relevant data has not actually changed.
function chartSceneAreEqual(prev: ChartSceneProps, next: ChartSceneProps): boolean {
    if (prev.mode !== next.mode) return false;
    if (prev.symbol !== next.symbol) return false;
    if (prev.config !== next.config) return false;
    if (prev.data.length !== next.data.length) return false;
    if (prev.positions.length !== next.positions.length) return false;
    if ((prev.closedTrades?.length ?? 0) !== (next.closedTrades?.length ?? 0)) return false;
    if (prev.amtAnalysis !== next.amtAnalysis) return false;
    return true;
}

export default React.memo(ChartScene, chartSceneAreEqual);
