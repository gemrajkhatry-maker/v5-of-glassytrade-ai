
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
  Logical
} from 'lightweight-charts';
import { OHLCData, ChartConfig, TradeSignal, TradePosition, AIAnalysis, AMTAnalysis, ChartMode, FootprintCandle, AggressivePrint } from '../types';

interface ChartSceneProps {
  data: OHLCData[];
  predictions: OHLCData[];
  config: ChartConfig;
  activeSignal?: TradeSignal | null;
  positions: TradePosition[];
  closedTrades?: TradePosition[];
  aiAnalysis?: AIAnalysis | null;
  amtAnalysis?: AMTAnalysis | null;
  mode?: ChartMode;
  isHidden?: boolean;
  // New Props for Prepared Data
  footprintData: Record<string, FootprintCandle> | null;
  cumulativeDeltas: number[];
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

const ChartScene: React.FC<ChartSceneProps> = ({
  data,
  predictions,
  config,
  activeSignal,
  positions,
  closedTrades = [],
  aiAnalysis,
  amtAnalysis,
  mode = 'STANDARD',
  isHidden = false,
  footprintData,
  cumulativeDeltas
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

  // 1. Initialize Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
      },
      rightPriceScale: {
        borderColor: '#1e293b',
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
      upColor: '#a855f7',
      downColor: '#581c87',
      borderVisible: true,
      borderColor: '#a855f7',
      wickUpColor: '#a855f7',
      wickDownColor: '#a855f7',
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

    const isFootprint = mode === 'FOOTPRINT';

    // Reserve space for Bottom Summary in Footprint mode
    chartRef.current.priceScale('right').applyOptions({
      scaleMargins: {
        top: 0.05,
        bottom: isFootprint ? 0.25 : 0.0,
      }
    });

    chartRef.current.applyOptions({
      timeScale: {
        barSpacing: isFootprint ? 160 : 6,
        minBarSpacing: isFootprint ? 100 : 2,
      }
    });

    if (isFootprint) {
      candleSeries.applyOptions({
        visible: true,
        upColor: 'rgba(0,0,0,0)',
        downColor: 'rgba(0,0,0,0)',
        wickUpColor: 'rgba(0,0,0,0)',
        wickDownColor: 'rgba(0,0,0,0)',
        borderVisible: false
      });
      predSeries.applyOptions({ visible: false });
    } else {
      candleSeries.applyOptions({ visible: true });
      predSeries.applyOptions({ visible: true });
    }

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

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      initializedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!isHidden && chartRef.current && chartContainerRef.current) {
      const { clientWidth, clientHeight } = chartContainerRef.current;
      if (clientWidth > 0 && clientHeight > 0) {
        chartRef.current.applyOptions({ width: clientWidth, height: clientHeight });
        if (overlayRef.current) {
          overlayRef.current.width = clientWidth;
          overlayRef.current.height = clientHeight;
        }
        chartRef.current.timeScale().scrollToPosition(0, false);
      }
    }
  }, [isHidden]);

  // 3. Canvas Overlay Drawing
  useEffect(() => {
    if (!chartRef.current || !candleSeriesRef.current || !overlayRef.current || isHidden) return;

    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    const canvas = overlayRef.current;
    const ctx = canvas.getContext('2d');

    const drawOverlay = () => {
      if (!ctx || isHidden) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      try {
        if (amtAnalysis) {
          if (config.showVolumeProfile) {
            drawVolumeProfile(ctx, canvas, series, amtAnalysis, config);
          }
          // Render Aggressive Bubbles (Fabio Valentini Style)
          if (amtAnalysis.aggressivePrints && amtAnalysis.aggressivePrints.length > 0) {
            drawAggressiveBubbles(ctx, canvas, chart, series, amtAnalysis.aggressivePrints, config);
          }
        }

        if (mode === 'FOOTPRINT' && footprintData && data.length > 0) {
          drawFootprint(ctx, canvas, chart, series, data, footprintData, cumulativeDeltas, config, amtAnalysis);
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

  }, [amtAnalysis, data, footprintData, cumulativeDeltas, config, mode, isHidden]);


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
        ctx.font = '9px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(formatK(print.volume), x, y);
      }
    });
  };


  // Helper: Draw a single VP profile on the RIGHT side of the chart (glassy style)
  const drawProfileBars = (
    ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement,
    series: ISeriesApi<"Candlestick">, profile: { price: number; volume: number; buyVolume: number; sellVolume: number }[],
    maxWidthPct: number, xOffset: number, bullColor: string, bearColor: string, useDirectionColors: boolean,
    hvnPrices?: number[], lvnPrices?: number[], vahPrice?: number, valPrice?: number, pocPrice?: number
  ) => {
    if (!profile || profile.length === 0) return;
    const maxVol = Math.max(...profile.map(p => p.volume));
    if (maxVol === 0) return;
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

  // Helper: Draw Footprint
  const drawFootprint = (
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    chart: IChartApi,
    series: ISeriesApi<"Candlestick">,
    data: OHLCData[],
    fpMap: Record<string, FootprintCandle>,
    cvdData: number[],
    cfg: ChartConfig,
    amt: AMTAnalysis | null
  ) => {
    const visibleRange = chart.timeScale().getVisibleLogicalRange();
    if (!visibleRange) return;

    const timeScale = chart.timeScale();
    const barSpacing = timeScale.options().barSpacing;

    // Layout
    const colWidth = barSpacing * 0.95;
    const deltaSpineWidth = colWidth > 60 ? 20 : 6; // Wider spine for delta text when room allows
    const spineWidth = 6; // Visual spine (candle body) stays narrow
    const sideWidth = (colWidth - deltaSpineWidth) / 2;
    const textPadding = 4;

    // Bottom Section Bounds
    const summaryHeight = canvas.height * 0.15;
    const summaryY = canvas.height - summaryHeight;

    // Draw Separator Line
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, summaryY);
    ctx.lineTo(canvas.width, summaryY);
    ctx.stroke();

    // --- 0. Draw Global Levels (VAH/VAL/POC) ---
    // We draw these on the canvas for the footprint chart to ensure they are visible
    if (amt) {
      const drawLevel = (price: number, color: string, label: string, isDashed: boolean = true) => {
        const y = series.priceToCoordinate(price);
        if (y === null || y > summaryY) return;

        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.setLineDash(isDashed ? [4, 4] : []);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
        ctx.setLineDash([]);

        // Label
        ctx.fillStyle = color;
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(label, canvas.width - 5, y - 4);
      };

      drawLevel(amt.poc, '#facc15', 'POC', false);
      drawLevel(amt.valueAreaHigh, '#3b82f6', 'VAH');
      drawLevel(amt.valueAreaLow, '#3b82f6', 'VAL');
    }


    // Render Loop
    for (let i = Math.floor(visibleRange.from); i < Math.ceil(visibleRange.to); i++) {
      if (i < 0 || i >= data.length) continue;

      const candle = data[i];
      const fp = fpMap[candle.time];
      if (!fp) continue;

      const centerX = timeScale.logicalToCoordinate(i as Logical);
      if (centerX === null || centerX < -100 || centerX > canvas.width + 100) continue;

      // --- 1. SPINE (Candle Body) ---
      const isBullish = candle.close >= candle.open;
      const bodyColor = isBullish ? cfg.bullColor : cfg.bearColor;

      const openY = series.priceToCoordinate(candle.open);
      const closeY = series.priceToCoordinate(candle.close);
      const highY = series.priceToCoordinate(candle.high);
      const lowY = series.priceToCoordinate(candle.low);

      if (openY !== null && closeY !== null && highY !== null && lowY !== null) {
        // Wick
        ctx.strokeStyle = bodyColor;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(centerX, highY);
        ctx.lineTo(centerX, lowY);
        ctx.stroke();

        // Body
        const bodyTop = Math.min(openY, closeY);
        const bodyHeight = Math.max(2, Math.abs(closeY - openY));
        ctx.fillStyle = bodyColor;
        ctx.fillRect(centerX - spineWidth / 2, bodyTop, spineWidth, bodyHeight);
      }

      // --- 2. FOOTPRINT CELLS ---
      const bidX = centerX - deltaSpineWidth / 2 - sideWidth;
      const askX = centerX + deltaSpineWidth / 2;

      // Calculate max volume for this specific candle (for profile bars)
      let maxVolInCandle = 0;
      let totalBid = 0;
      let totalAsk = 0;

      fp.levels.forEach(l => {
        maxVolInCandle = Math.max(maxVolInCandle, l.bid, l.ask);
        totalBid += l.bid;
        totalAsk += l.ask;
      });

      // Dynamic Grid Height
      let cellHeight = 14;
      if (fp.levels.length > 0) {
        const topY = series.priceToCoordinate(fp.levels[0].price + fp.stepPrice / 2);
        const bottomY = series.priceToCoordinate(fp.levels[0].price - fp.stepPrice / 2);
        if (topY !== null && bottomY !== null) {
          cellHeight = Math.abs(bottomY - topY);
        }
      }
      cellHeight = Math.max(2, cellHeight);
      const showText = cellHeight > 10 && sideWidth > 30;
      ctx.font = `${Math.min(11, cellHeight - 3)}px monospace`;
      ctx.textBaseline = 'middle';

      // Draw Levels
      fp.levels.forEach((level) => {
        const y = series.priceToCoordinate(level.price);
        if (y === null || y > summaryY) return;

        const lvlTop = series.priceToCoordinate(level.price + fp.stepPrice / 2) ?? (y - cellHeight / 2);
        const lvlBot = series.priceToCoordinate(level.price - fp.stepPrice / 2) ?? (y + cellHeight / 2);
        const h = Math.abs(lvlBot - lvlTop);
        const drawY = Math.min(lvlTop, lvlBot);

        // 1px gap for grid look
        const drawH = Math.max(1, h - 1);

        // --- INTENSITY LOGIC ---
        // Calculate alpha based on ratio of volume to max volume in candle
        // Base alpha 0.2, scales up to 0.9
        const isBuyImbalance = level.imbalance && level.ask > level.bid;
        const isSellImbalance = level.imbalance && level.bid > level.ask;

        // Bid Bar (Left Side - Grows Right to Left)
        const bidRatio = maxVolInCandle > 0 ? level.bid / maxVolInCandle : 0;
        const bidBarW = bidRatio * sideWidth;
        const bidAlpha = 0.2 + (bidRatio * 0.7);

        // Use bright red for sell imbalance bars, normal bearColor otherwise
        const bidBarColor = isSellImbalance ? '#ef4444' : cfg.bearColor;
        ctx.fillStyle = hexToRgba(bidBarColor, bidAlpha);
        ctx.fillRect(bidX + sideWidth - bidBarW, drawY, bidBarW, drawH);

        // Ask Bar (Right Side - Grows Left to Right)
        const askRatio = maxVolInCandle > 0 ? level.ask / maxVolInCandle : 0;
        const askBarW = askRatio * sideWidth;
        const askAlpha = 0.2 + (askRatio * 0.7);

        // Use bright green for buy imbalance bars, normal bullColor otherwise
        const askBarColor = isBuyImbalance ? '#22c55e' : cfg.bullColor;
        ctx.fillStyle = hexToRgba(askBarColor, askAlpha);
        ctx.fillRect(askX, drawY, askBarW, drawH);

        // Stacked imbalance border (3+ consecutive imbalances)
        if (level.stacked) {
          const stackedBorderColor = level.ask > level.bid ? '#f59e0b' : '#ec4899'; // Gold for buy, magenta for sell
          ctx.strokeStyle = stackedBorderColor;
          ctx.lineWidth = 2;
          ctx.strokeRect(bidX, drawY, sideWidth * 2 + deltaSpineWidth, drawH);
        }

        // POC Highlight (Within Candle)
        const isPOC = Math.abs(level.price - fp.pocPrice) < 0.00001;
        if (isPOC) {
          ctx.strokeStyle = '#facc15';
          ctx.lineWidth = 1.5;
          ctx.strokeRect(bidX, drawY, (sideWidth * 2) + deltaSpineWidth, drawH);
        }

        if (showText) {
          const midY = drawY + drawH / 2;

          // Bid Text (Right Aligned in Left Column)
          ctx.fillStyle = isSellImbalance ? '#22d3ee' : '#ffffff'; // Cyan for aggressive sell imb
          ctx.textAlign = 'right';
          ctx.fillText(formatK(level.bid), bidX + sideWidth - textPadding, midY);

          // Ask Text (Left Aligned in Right Column)
          ctx.fillStyle = isBuyImbalance ? '#bef264' : '#ffffff'; // Lime for aggressive buy imb
          ctx.textAlign = 'left';
          ctx.fillText(formatK(level.ask), askX + textPadding, midY);

          // Per-level delta in the spine area (between bid and ask columns)
          if (cellHeight > 12 && sideWidth > 25) {
            ctx.fillStyle = level.delta >= 0 ? '#22c55e' : '#ef4444';
            ctx.textAlign = 'center';
            ctx.font = `${Math.min(9, cellHeight - 4)}px monospace`;
            ctx.fillText(formatK(level.delta), centerX, midY);
            ctx.font = `${Math.min(11, cellHeight - 3)}px monospace`; // Restore font
          }
        }
      });

      // --- 3. BOTTOM SUMMARY ---
      // Totals
      const textY = summaryY + 16;
      ctx.font = 'bold 11px monospace';
      ctx.textAlign = 'center';

      // Total Bid (Red)
      ctx.fillStyle = cfg.bearColor;
      ctx.fillText(formatK(totalBid), bidX + sideWidth / 2, textY);

      // Total Ask (Green)
      ctx.fillStyle = cfg.bullColor;
      ctx.fillText(formatK(totalAsk), askX + sideWidth / 2, textY);

      // Delta Card
      const cardY = textY + 14;
      const cardH = 34;
      const cardW = colWidth;

      // Card Background
      ctx.fillStyle = '#1e293b';
      ctx.strokeStyle = '#334155';
      ctx.lineWidth = 1;
      ctx.beginPath();
      if (typeof ctx.roundRect === 'function') {
        ctx.roundRect(centerX - cardW / 2, cardY, cardW, cardH, 4);
      } else {
        ctx.rect(centerX - cardW / 2, cardY, cardW, cardH);
      }
      ctx.fill();
      ctx.stroke();

      // Card Text
      ctx.font = '10px sans-serif';
      ctx.fillStyle = '#94a3b8';
      ctx.fillText('Delta', centerX, cardY + 10);

      ctx.font = 'bold 10px monospace';
      ctx.fillStyle = fp.totalDelta > 0 ? cfg.bullColor : cfg.bearColor;
      ctx.fillText((fp.totalDelta > 0 ? '+' : '') + formatK(fp.totalDelta), centerX, cardY + 24);
    }

    // --- 4. CVD LINE (drawn in summary area below separator) ---
    if (cvdData.length > 0) {
      const cvdTop = summaryY + 4;
      const cvdBottom = canvas.height - 4;
      const cvdHeight = cvdBottom - cvdTop;

      // Collect visible CVD points
      const cvdPoints: { x: number; val: number }[] = [];
      for (let i = Math.floor(visibleRange.from); i < Math.ceil(visibleRange.to); i++) {
        if (i < 0 || i >= data.length || i >= cvdData.length) continue;
        const x = timeScale.logicalToCoordinate(i as Logical);
        if (x === null) continue;
        cvdPoints.push({ x, val: cvdData[i] });
      }

      if (cvdPoints.length > 1) {
        // Normalize CVD values to available height
        let minCvd = Infinity, maxCvd = -Infinity;
        cvdPoints.forEach(p => { minCvd = Math.min(minCvd, p.val); maxCvd = Math.max(maxCvd, p.val); });
        const cvdRange = maxCvd - minCvd || 1;

        // Draw CVD line segments: green when rising, red when falling
        ctx.lineWidth = 1.5;
        for (let j = 1; j < cvdPoints.length; j++) {
          const prev = cvdPoints[j - 1];
          const curr = cvdPoints[j];
          const prevY = cvdBottom - ((prev.val - minCvd) / cvdRange) * cvdHeight;
          const currY = cvdBottom - ((curr.val - minCvd) / cvdRange) * cvdHeight;

          ctx.strokeStyle = curr.val >= prev.val ? '#22c55e' : '#ef4444';
          ctx.beginPath();
          ctx.moveTo(prev.x, prevY);
          ctx.lineTo(curr.x, currY);
          ctx.stroke();
        }

        // Label
        ctx.fillStyle = '#64748b';
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('CVD', 5, cvdTop + 10);
      }
    }
  };

  const formatK = (val: number) => {
    if (isNaN(val)) return '0';
    if (val >= 1000000) return (val / 1000000).toFixed(2) + 'M';
    if (val >= 1000) return (val / 1000).toFixed(1) + 'K';
    return Math.floor(val).toString();
  };

  // 4. Update Data
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
      color: d.close >= d.open ? `${config.bullColor}80` : `${config.bearColor}80`,
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
  }, [data, predictions, config.bullColor, config.bearColor]);

  // 5. Update Markers & Lines
  useEffect(() => {
    if (!candleSeriesRef.current || !chartRef.current) return;

    amtLinesRef.current.forEach(l => candleSeriesRef.current?.removePriceLine(l));
    amtLinesRef.current = [];

    // Only add lightweight-chart pricelines if NOT in footprint mode
    const vpMode = config.vpMode || 'combined';
    if (amtAnalysis && config.showVolumeProfile && mode !== 'FOOTPRINT') {
      // Session levels (shown in session + combined modes)
      if (vpMode === 'session' || vpMode === 'combined') {
        amtLinesRef.current.push(candleSeriesRef.current.createPriceLine({
          price: amtAnalysis.poc,
          color: '#facc15',
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: 'POC',
        }));
        amtLinesRef.current.push(candleSeriesRef.current.createPriceLine({
          price: amtAnalysis.valueAreaHigh,
          color: '#3b82f6',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'VAH',
        }));
        amtLinesRef.current.push(candleSeriesRef.current.createPriceLine({
          price: amtAnalysis.valueAreaLow,
          color: '#3b82f6',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'VAL',
        }));

        // LVN lines (amber dotted — thin, low-volume gaps)
        amtAnalysis.lvns?.forEach((lvn: number) => {
          amtLinesRef.current.push(candleSeriesRef.current!.createPriceLine({
            price: lvn,
            color: '#fb923c',
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: 'LVN',
          }));
        });

        // HVN lines (emerald dashed — high-volume support/resistance)
        amtAnalysis.hvns?.forEach((hvn: number) => {
          amtLinesRef.current.push(candleSeriesRef.current!.createPriceLine({
            price: hvn,
            color: '#34d399',
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'HVN',
          }));
        });
      }

      // Leg levels (shown in leg + combined modes when leg profile exists)
      if ((vpMode === 'leg' || vpMode === 'combined') && amtAnalysis.legProfile && amtAnalysis.legProfile.length > 0) {
        if (amtAnalysis.legPoc > 0) {
          amtLinesRef.current.push(candleSeriesRef.current.createPriceLine({
            price: amtAnalysis.legPoc,
            color: '#FF9900',
            lineWidth: 2,
            lineStyle: LineStyle.Solid,
            axisLabelVisible: true,
            title: 'Leg POC',
          }));
        }
        if (amtAnalysis.legVah > 0) {
          amtLinesRef.current.push(candleSeriesRef.current.createPriceLine({
            price: amtAnalysis.legVah,
            color: '#FF6600',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'Leg VAH',
          }));
        }
        if (amtAnalysis.legVal > 0) {
          amtLinesRef.current.push(candleSeriesRef.current.createPriceLine({
            price: amtAnalysis.legVal,
            color: '#FF6600',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'Leg VAL',
          }));
        }
        // Leg LVN lines (warm yellow dotted)
        amtAnalysis.legLvns?.forEach((lvn: number) => {
          amtLinesRef.current.push(candleSeriesRef.current!.createPriceLine({
            price: lvn,
            color: '#fbbf24',
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: 'Leg LVN',
          }));
        });
      }
    }

    if (mode === 'STANDARD') {
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
      (closedTrades || []).forEach(trade => {
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

      // Active signal (when no position yet)
      if (activeSignal && positions.length === 0) {
        markers.push({
          time: (new Date(activeSignal.timestamp).getTime() / 1000 + 19800) as UTCTimestamp,
          position: activeSignal.type === 'BUY' ? 'belowBar' : 'aboveBar',
          color: activeSignal.type === 'BUY' ? '#10b981' : '#ef4444',
          shape: activeSignal.type === 'BUY' ? 'arrowUp' : 'arrowDown',
          text: `SIGNAL: ${activeSignal.type}`,
          size: 2,
        });
      }

      // Sort markers by time (required by lightweight-charts)
      markers.sort((a, b) => (a.time as number) - (b.time as number));
      candleSeriesRef.current.setMarkers(markers);
    } else {
      candleSeriesRef.current.setMarkers([]);
    }

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

  }, [positions, closedTrades, activeSignal, amtAnalysis, config.bullColor, config.bearColor, config.showVolumeProfile, config.vpMode, mode]);

  return (
    <div className="w-full h-full relative bg-[#0f172a] overflow-hidden" style={{ display: isHidden ? 'none' : 'block' }}>
      <div ref={chartContainerRef} className="w-full h-full relative z-10" />
      <canvas ref={overlayRef} className="absolute inset-0 z-20 pointer-events-none" />

      {/* Chart Mode Indicator */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-black/40 backdrop-blur px-3 py-1 rounded-full border border-white/5 text-[10px] text-white/50 z-30 pointer-events-none uppercase tracking-wider">
        {mode === 'FOOTPRINT' ? 'ORDERFLOW FOOTPRINT' : 'STANDARD CANDLESTICKS'}
      </div>
    </div>
  );
};

export default React.memo(ChartScene);
