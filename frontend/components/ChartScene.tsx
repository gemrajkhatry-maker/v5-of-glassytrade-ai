
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
import { OHLCData, ChartConfig, TradePosition, AMTAnalysis, AgentDecision, ChartMode, AggressivePrint, HalfTrendPoint } from '../types';
import { IST_OFFSET_SECONDS } from '../constants';
import DecisionCard from './chart/DecisionCard';

// Extracted chart components (Phase 3)
import {
  generateAMTPriceLines,
  AMTLevelsOverlayOptions,
} from './chart/AMTLevelsOverlay';
import {
  generateAllExecutionMarkers,
  halfTrendSeriesData,
  halfTrendSignalMarkers,
  ExecutionMarkersOptions,
} from './chart/ExecutionMarkersManager';
import {
  transformToCandleData,
  validateCandleData,
  toISTTimestamp,
} from './chart/CandleSeriesManager';
import {
  transformToVolumeData,
  validateVolumeData,
} from './chart/VolumeSeriesManager';
interface ChartSceneProps {
  data: OHLCData[];
  config: ChartConfig;
  positions: TradePosition[];
  closedTrades?: TradePosition[];
  agentDecision?: AgentDecision | null;
  amtAnalysis?: AMTAnalysis | null;
  halfTrendSeries?: HalfTrendPoint[];
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
 * Profile levels are JSON-decoded on every WS snapshot, so object identity is
 * never stable across ticks. Compare the rendered fields instead.
 */
function arraysShallowEqual<T extends object>(a: T[] | undefined, b: T[] | undefined): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.length !== b.length) return false;
  
  for (let i = 0; i < a.length; i++) {
    const left = a[i] as Record<string, unknown>;
    const right = b[i] as Record<string, unknown>;
    if (left === right) continue;
    const keys = Object.keys(left);
    if (keys.length !== Object.keys(right).length || keys.some(key => left[key] !== right[key])) return false;
  }
  
  return true;
}

const ChartScene: React.FC<ChartSceneProps> = ({
  data,
  config,
  positions,
  closedTrades = [],
  agentDecision,
  amtAnalysis,
  halfTrendSeries = [],
  mode = 'STANDARD',
  tickBus,
  symbol,
}) => {
const chartContainerRef = useRef<HTMLDivElement>(null);
    const overlayRef = useRef<HTMLCanvasElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const htLineRef = useRef<ISeriesApi<"Line"> | null>(null);
    const atrHighRef = useRef<ISeriesApi<"Line"> | null>(null);
    const atrLowRef = useRef<ISeriesApi<"Line"> | null>(null);
    const activePriceLinesRef = useRef<Map<string, IPriceLine[]>>(new Map());
    const amtLinesRef = useRef<IPriceLine[]>([]);
    const initializedRef = useRef(false);
    const lastCandleTimeRef = useRef<number>(0);
    const prevSymbolRef = useRef<string | undefined>(undefined);
    const prevIntervalRef = useRef<string | undefined>(undefined);
    const prevActiveDataRef = useRef<OHLCData[] | null>(null);
    const prevDataLenRef = useRef<number>(0);
    // Shared redraw trigger so the ResizeObserver can repaint the overlay
    // without leaving a blank canvas during a sidebar slide.
    const drawOverlayRef = useRef<(() => void) | null>(null);

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
      prev.breakDirection === amtAnalysis.breakDirection &&
      prev.breakLevel === amtAnalysis.breakLevel &&
      prev.ibComplete === amtAnalysis.ibComplete;
    if (profileSame && legSame && printsSame && levelsSame) {
      return prev; // Return old reference to skip redraw
    }

    prevAmtRef.current = amtAnalysis;
    return amtAnalysis;
  }, [amtAnalysis]);

  // Interval-scoped data fetching (ensures 1m and 5m load their exact independent candle feeds)
  const [scopedData, setScopedData] = useState<OHLCData[] | null>(null);

  useEffect(() => {
    if (!symbol) return;
    const targetInterval = config.interval || '5m';
    let cancelled = false;
    const url = `/api/market/history/${encodeURIComponent(symbol)}?interval=${encodeURIComponent(targetInterval)}&limit=500`;
    fetch(url)
      .then(res => (res.ok ? res.json() : null))
      .then(body => {
        if (cancelled || !body?.data || !Array.isArray(body.data) || body.data.length === 0) return;
        const candles: OHLCData[] = body.data.map((c: any) => ({
          time: String(c.time),
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
          volume: Number(c.volume ?? 0),
          vwap: Number(c.vwap ?? 0),
          takerBuyVolume: Number(c.takerBuyVolume ?? 0),
          delta: Number(c.delta ?? 0),
        }));
        setScopedData(candles);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [symbol, config.interval]);

  const activeData = useMemo(() => {
    if (scopedData && scopedData.length > 0) return scopedData;
    return data;
  }, [scopedData, data]);

  // Stabilize data reference — only update when activeData reference or length changes.
  // Prevents canvas overlay from redrawing on every intra-candle tick update while correctly switching on interval change.
  const stableData = useMemo(() => activeData, [activeData, activeData.length]);

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

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    // HalfTrend overlay: ht trend line + ATR channel rails (backend data).
    const htLineSeries = chart.addLineSeries({
      color: '#2962ff',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const atrHighSeries = chart.addLineSeries({
      color: '#f23645',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const atrLowSeries = chart.addLineSeries({
      color: '#2962ff',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    htLineRef.current = htLineSeries;
    atrHighRef.current = atrHighSeries;
    atrLowRef.current = atrLowSeries;

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

    // ponytail: rAF debounce — ResizeObserver fires per-frame during 300ms sidebar slide
    let raf = 0;
    const resizeObserver = new ResizeObserver(entries => {
      if (!entries[0]?.contentRect) return;
      const { width, height } = entries[0].contentRect;
      if (width===0 || height===0) return;
      if (chartRef.current && (chartRef.current as any)._lastW===width && (chartRef.current as any)._lastH===height) return;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        chart.applyOptions({ width, height });
        if (overlayRef.current) { overlayRef.current.width = width; overlayRef.current.height = height; }
        (chartRef.current as any)._lastW = width; (chartRef.current as any)._lastH = height;
        // canvas.width= clears the bitmap — repaint immediately so a sidebar
        // slide never leaves the VP profile/VA box blank for a frame.
        drawOverlayRef.current?.();
      });
    });

    resizeObserver.observe(chartContainerRef.current);

    return () => {
      drawOverlayRef.current = null;
      cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      chart.remove();
      htLineRef.current = null;
      atrHighRef.current = null;
      atrLowRef.current = null;
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

      // Interval guard: only accept ticks matching this chart's configured timeframe.
      // Backend tags each tick with barIntervalSec (60 = 1m, 300 = 5m).
      const myInterval = config.interval || '5m';
      const myIntervalSec = myInterval === '1m' ? 60 : 300;
      if (tick.barIntervalSec !== undefined && tick.barIntervalSec !== myIntervalSec) {
        return;
      }

      // Common Time in IST (consistently aligned with historical candles)
      const unixTime = toISTTimestamp(tick.time) as any;

      // Guard: timestamp must be strictly >= last rendered candle time
      if (lastCandleTimeRef.current > 0 && unixTime < lastCandleTimeRef.current) {
        return;
      }

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
        lastCandleTimeRef.current = unixTime;
      } catch {
        // Silently ignore benign in-flight tick collisions
      }
    };

    tickBus.addEventListener('tick', handleTick);

    return () => {
      tickBus.removeEventListener('tick', handleTick);
    };
  }, [tickBus, symbol, config.interval, mode]);

  // Handle mode/config changes dynamically without remount
  useEffect(() => {
    if (!candleSeriesRef.current) return;

    candleSeriesRef.current.applyOptions({
      upColor: config.bullColor,
      downColor: config.bearColor,
      wickUpColor: config.bullColor,
      wickDownColor: config.bearColor,
      borderVisible: false
    });
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

    // Expose the redraw to the ResizeObserver so a canvas resize never leaves
    // a blank frame (canvas.width= clears the bitmap) without repainting.
    drawOverlayRef.current = drawOverlay;

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
      // Convert time string to chart timestamp (IST-aligned, same as candles)
      const printTime = toISTTimestamp(print.time) as UTCTimestamp;

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

    // Convert OHLCData time string to chart timestamp (IST-aligned)
    const toChartTs = (timeStr: string) => {
      return toISTTimestamp(timeStr) as UTCTimestamp;
    };

    // Find the X coordinate for a specific IST hour:minute
    const findTimeX = (targetHour: number, targetMinute: number): number | null => {
      for (const candle of data) {
        const chartTs = toChartTs(candle.time as string);
        const d = new Date(candle.time as string);
        const istHour = d.getHours();
        const istMinute = d.getMinutes();
        if (istHour === targetHour && istMinute === targetMinute) {
          const coord = chart.timeScale().timeToCoordinate(chartTs);
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

    // Convert break candle time to chart coordinate (IST-aligned)
    const breakCandle = data[breakCandleIndex];
    const breakTs = toISTTimestamp(breakCandle.time as string) as UTCTimestamp;
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
        baseAlpha = 0.90;
      } else if (isHvn) {
        baseAlpha = 0.70;
      } else if (isLvn) {
        baseAlpha = 0.20;
      } else if (isVA) {
        baseAlpha = 0.55;
      } else {
        baseAlpha = 0.30;
      }

      const buyVol = level.buyVolume || 0;
      const sellVol = level.sellVolume || 0;
      const isInsignificant = maxVol > 0 && level.volume < maxVol * 0.20;

      if (isInsignificant) {
        // Insignificant volume profile rows (< 20% of max volume) -> muted grey
        const greyGrad = ctx.createLinearGradient(x, 0, x + barWidth, 0);
        greyGrad.addColorStop(0, hexToRgba('#9ca3af', baseAlpha * 0.2));
        greyGrad.addColorStop(1, hexToRgba('#9ca3af', baseAlpha * 0.4));
        ctx.fillStyle = greyGrad;
        ctx.fillRect(x, y - barHeight / 2, barWidth, barHeight);
      } else if (useDirectionColors && (buyVol > 0 || sellVol > 0)) {
        const total = buyVol + sellVol || level.volume || 1;
        const buyFraction = buyVol / total;
        const buyW = barWidth * buyFraction;
        const sellW = barWidth - buyW;

        // Draw Up-Volume (Green #089981) segment attached to right edge
        if (buyW > 0) {
          const buyX = rightEdge - xOffset - buyW;
          const buyGrad = ctx.createLinearGradient(buyX, 0, buyX + buyW, 0);
          buyGrad.addColorStop(0, hexToRgba('#089981', baseAlpha * 0.4));
          buyGrad.addColorStop(1, hexToRgba('#089981', baseAlpha * 0.9));
          ctx.fillStyle = buyGrad;
          ctx.fillRect(buyX, y - barHeight / 2, buyW, barHeight);
        }

        // Draw Down-Volume (Red #f23645) segment extended to the left
        if (sellW > 0) {
          const sellX = rightEdge - xOffset - barWidth;
          const sellGrad = ctx.createLinearGradient(sellX, 0, sellX + sellW, 0);
          sellGrad.addColorStop(0, hexToRgba('#f23645', baseAlpha * 0.4));
          sellGrad.addColorStop(1, hexToRgba('#f23645', baseAlpha * 0.9));
          ctx.fillStyle = sellGrad;
          ctx.fillRect(sellX, y - barHeight / 2, sellW, barHeight);
        }
      } else {
        // Single color glassy gradient fill
        const grad = ctx.createLinearGradient(x, 0, x + barWidth, 0);
        grad.addColorStop(0, hexToRgba(baseColor, baseAlpha * 0.3));
        grad.addColorStop(0.4, hexToRgba(baseColor, baseAlpha * 0.7));
        grad.addColorStop(1, hexToRgba(baseColor, baseAlpha));
        ctx.fillStyle = grad;
        ctx.fillRect(x, y - barHeight / 2, barWidth, barHeight);
      }

      // Top highlight (glass refraction)
      ctx.fillStyle = `rgba(255,255,255,${baseAlpha * 0.12})`;
      ctx.fillRect(x, y - barHeight / 2, barWidth, Math.max(1, barHeight * 0.3));

      // POC bar: bright electric blue edge + glow (#5b9cf6)
      if (isP) {
        ctx.shadowColor = hexToRgba('#5b9cf6', 0.85);
        ctx.shadowBlur = 10;
        ctx.fillStyle = hexToRgba('#5b9cf6', 0.95);
        ctx.fillRect(x, y - barHeight / 2, 2.5, barHeight);
        ctx.shadowBlur = 0;
      }
      // HVN: bright green left edge + subtle glow
      else if (isHvn) {
        ctx.shadowColor = hexToRgba('#089981', 0.4);
        ctx.shadowBlur = 6;
        ctx.fillStyle = hexToRgba('#089981', 0.7);
        ctx.fillRect(x, y - barHeight / 2, 2, barHeight);
        ctx.shadowBlur = 0;
      }
      // LVN: thin orange edge
      else if (isLvn) {
        ctx.fillStyle = hexToRgba('#f97316', 0.5);
        ctx.fillRect(x, y - barHeight / 2, 1, barHeight);
      }
      // Value Area (VA) blue accent edge (#5b9cf6)
      else if (isVA) {
        ctx.fillStyle = hexToRgba('#5b9cf6', baseAlpha * 0.9);
        ctx.fillRect(x, y - barHeight / 2, 1.5, barHeight);
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
    ctx.globalAlpha = 0.75;
    ctx.fillText(text, 0, 0);
    ctx.restore();
  };

  // Helper: Draw Volume Profile (session + leg on RIGHT side, controlled by vpMode)
  const drawVolumeProfile = (ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, series: ISeriesApi<"Candlestick">, amt: AMTAnalysis, cfg: ChartConfig) => {
    const mode = cfg.vpMode || 'combined';
    const hasLeg = amt.legProfile && amt.legProfile.length > 0;
    const rightEdge = canvas.width - 50;

    // Session profile: Green (#089981) up-volume / Red (#f23645) down-volume with Blue (#5b9cf6) POC and VA
    if (mode === 'session' || mode === 'combined') {
      const sessionWidth = mode === 'session' ? 0.40 : 0.28;
      const sessionOffset = (hasLeg && mode === 'combined') ? canvas.width * 0.16 : 0;
      drawProfileBars(ctx, canvas, series, amt.profile, sessionWidth, sessionOffset, '#089981', '#f23645', true,
        amt.hvns, amt.lvns, amt.valueAreaHigh, amt.valueAreaLow, amt.poc);
      drawVerticalLabel(ctx, canvas, 'SESSION PROFILE', rightEdge - sessionOffset - canvas.width * 0.14, '#5b9cf6');
    }

    // Leg profile (amber/orange bars with leg-specific levels)
    if (hasLeg && (mode === 'leg' || mode === 'combined')) {
      const legWidth = mode === 'leg' ? 0.40 : 0.16;
      drawProfileBars(ctx, canvas, series, amt.legProfile, legWidth, 0, '#FF9900', '#FF6600', false,
        undefined, amt.legLvns, amt.legVah > 0 ? amt.legVah : undefined, amt.legVal > 0 ? amt.legVal : undefined, amt.legPoc > 0 ? amt.legPoc : undefined);
      drawVerticalLabel(ctx, canvas, 'LEG PROFILE', rightEdge - canvas.width * 0.08, '#FF9900');
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
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

    const formatCandle = (d: OHLCData) => ({
      time: toISTTimestamp(d.time) as UTCTimestamp,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    });

    const formatVolume = (d: OHLCData) => ({
      time: toISTTimestamp(d.time) as UTCTimestamp,
      value: d.volume,
      // P2: Colour volume bars by delta sign (who won the candle), not candle direction
      // Green delta = buyers won, Red delta = sellers won, Grey = neutral
      color: Math.abs(d.delta || 0) / Math.max(d.volume || 1, 1) > 0.02
        ? (d.delta > 0 ? `${config.bullColor}80` : `${config.bearColor}80`)
        : 'rgba(156,163,175,0.4)', // Grey for neutral delta
    });

    const isSymbolChange = symbol !== undefined && symbol !== prevSymbolRef.current;
    if (isSymbolChange) {
      prevSymbolRef.current = symbol;
      lastCandleTimeRef.current = 0;

      // Clean up previous symbol's price lines immediately so they don't stretch the price scale
      amtLinesRef.current.forEach(l => candleSeriesRef.current?.removePriceLine(l));
      amtLinesRef.current = [];
      activePriceLinesRef.current.forEach(lines => {
        lines.forEach(l => candleSeriesRef.current?.removePriceLine(l));
      });
      activePriceLinesRef.current.clear();
      // NOTE: do NOT clearRect here — the overlay effect (deps stableData) fires
      // in the same React commit and repaints. Clearing here blanks the canvas
      // for one frame before that paint lands.
    }

    // Guard: only call setData() when the chart actually needs a full rebuild.
    // tickBus (effect #2) already handles intra-candle tick updates via
    // candleSeries.update(). Calling setData() on every data reference change
    // causes a full chart redraw + visible flicker with zero benefit.
    const isIntervalChange = config.interval !== undefined && config.interval !== prevIntervalRef.current;
    const isDataChange = activeData !== prevActiveDataRef.current;
    const dataLenChanged = activeData.length !== prevDataLenRef.current;
    const needsFullRebuild = isSymbolChange || isIntervalChange || isDataChange || !initializedRef.current || dataLenChanged;

    prevIntervalRef.current = config.interval;
    prevActiveDataRef.current = activeData;
    prevDataLenRef.current = activeData.length;

    if (activeData.length > 0 && needsFullRebuild) {
      const formattedCandles = activeData.map(formatCandle);
      candleSeriesRef.current.setData(formattedCandles);
      volumeSeriesRef.current.setData(activeData.map(formatVolume));

      // Redraw overlay AFTER setData so priceToCoordinate() uses the new
      // chart data — fixes volume profile blank on symbol switch.
      drawOverlayRef.current?.();

      const lastCandle = formattedCandles[formattedCandles.length - 1];
      if (lastCandle) {
        lastCandleTimeRef.current = Number(lastCandle.time);
      }

      if (chartRef.current) {
        const chart = chartRef.current;
        const doFit = () => {
          chart.priceScale('right').applyOptions({
            autoScale: true,
            scaleMargins: { top: 0.15, bottom: 0.15 },
          });
          if (isSymbolChange || isIntervalChange || !initializedRef.current) {
            chart.timeScale().fitContent();
            chart.timeScale().scrollToPosition(0, false);
            initializedRef.current = true;
          }
          // Overlay must redraw again after fitContent shifts the visible range
          drawOverlayRef.current?.();
        };
        if (isSymbolChange || isIntervalChange || !initializedRef.current) {
          requestAnimationFrame(doFit);
        } else {
          doFit();
        }
      }
    } else if (activeData.length > 0) {
      // Intra-candle tick: update lastCandleTimeRef for the tickBus guard
      const lastD = activeData[activeData.length - 1];
      if (lastD) {
        lastCandleTimeRef.current = toISTTimestamp(lastD.time);
      }
    }
  }, [activeData, symbol, config.interval, config.bullColor, config.bearColor, mode]);

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
      positions || [],
      closedTrades || [],
      stableData,
      stableAmtAnalysis,
      markerOptions
    );

    // HalfTrend Buy/Sell labels (signals computed in the backend)
    allMarkers.push(...halfTrendSignalMarkers(halfTrendSeries));

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

    const currentPosIds = new Set((positions || []).map(p => p.id));
    activePriceLinesRef.current.forEach((lines, id) => {
      if (!currentPosIds.has(id)) {
        lines.forEach(l => candleSeriesRef.current?.removePriceLine(l));
        activePriceLinesRef.current.delete(id);
      }
    });

    (positions || []).forEach(pos => {
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

  }, [symbol, positions, closedTrades, stableAmtAnalysis, halfTrendSeries, config.bullColor, config.bearColor, config.showVolumeProfile, config.vpMode, mode]);

  // 6. HalfTrend overlay — ht trend line + ATR channel rails.
  useEffect(() => {
    if (!htLineRef.current || !atrHighRef.current || !atrLowRef.current) return;
    const { ht, atrHigh, atrLow } = halfTrendSeriesData(halfTrendSeries || []);
    htLineRef.current.setData(ht as any);
    atrHighRef.current.setData(atrHigh as any);
    atrLowRef.current.setData(atrLow as any);
  }, [symbol, halfTrendSeries]);

  return (
    <div className="w-full h-full relative bg-[#0f172a] overflow-hidden">
      <div ref={chartContainerRef} className="w-full h-full relative z-10" />
      <canvas ref={overlayRef} className="absolute inset-0 z-20 pointer-events-none" />

      {/* Chart Mode Indicator */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-black/40 backdrop-blur px-3 py-1 rounded-full border border-white/5 text-[10px] text-white/50 z-30 pointer-events-none uppercase tracking-wider">
        STANDARD CANDLESTICKS
      </div>

      {/* Empty State / Live Stream Status Overlay */}
      {activeData.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center z-25 pointer-events-none p-6 text-center">
          <div className="p-6 rounded-2xl bg-black/40 backdrop-blur-xl border border-white/10 max-w-md space-y-3 shadow-2xl">
            <div className="flex items-center justify-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs font-bold font-mono uppercase tracking-widest text-emerald-400">
                Live Market Feed Connected
              </span>
            </div>
            <div className="text-sm font-extrabold text-white tracking-wide font-mono">
              {symbol || 'Awaiting Contract'}
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Connected to Dhan WebSocket gameloop. Live 0.5s price delta, depth, and order book imbalance are actively streaming.
            </p>
          </div>
        </div>
      )}

      {/* Current Decision Card */}
      {(agentDecision?.direction || agentDecision?.rationale) && (
        <div className="absolute top-4 right-4 z-40 w-72 max-h-[80%] overflow-hidden">
          <DecisionCard
            direction={agentDecision.direction || 'FLAT'}
            regime={agentDecision.regime || ''}
            rationale={agentDecision.rationale || ''}
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
    if (prev.agentDecision !== next.agentDecision) return false;
    if (prev.amtAnalysis !== next.amtAnalysis) return false;
    return true;
}

export default React.memo(ChartScene, chartSceneAreEqual);
