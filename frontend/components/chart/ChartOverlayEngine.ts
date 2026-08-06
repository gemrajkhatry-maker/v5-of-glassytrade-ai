/**
 * ChartOverlayEngine - Canvas overlay drawing utilities for ChartScene
 * Extracted from ChartScene.tsx lines 482-1370
 * 
 * Contains all canvas drawing functions:
 * - drawAggressiveBubbles
 * - drawVAShadedBox
 * - drawTimeMarkers
 * - drawIBRetestZone
 * - drawProfileBars
 * - drawVolumeProfile
 */

import { IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts';
import { ChartConfig, AggressivePrint, AMTAnalysis, OHLCData } from '../../types';

// Helper: Convert Hex to RGBA
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
 * Draw aggressive trade bubbles on chart
 */
export const drawAggressiveBubbles = (
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
    const printTime = (new Date(print.time).getTime() / 1000 + 19800) as UTCTimestamp;
    const x = timeScale.timeToCoordinate(printTime);
    const y = series.priceToCoordinate(print.price);

    if (x === null || y === null) return;

    const radius = Math.max(8, Math.min(20, print.volume / 100));
    const color = print.side === 'BUY' ? cfg.bullColor || '#22c55e' : cfg.bearColor || '#ef4444';

    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = hexToRgba(color, 0.7);
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.fillStyle = '#fff';
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(print.volume > 1000 ? `${(print.volume / 1000).toFixed(1)}K` : print.volume.toString(), x, y);
  });
};

/**
 * Draw VA shaded box (VAH-VAL fill)
 */
export const drawVAShadedBox = (
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  amt: AMTAnalysis
) => {
  const vahY = series.priceToCoordinate(amt.valueAreaHigh);
  const valY = series.priceToCoordinate(amt.valueAreaLow);

  if (vahY === null || valY === null) return;

  ctx.fillStyle = 'rgba(59, 130, 246, 0.08)';
  ctx.fillRect(0, Math.min(vahY, valY), canvas.width, Math.abs(valY - vahY));

  [
    { price: amt.valueAreaHigh, color: 'rgba(59, 130, 246, 0.5)', label: 'VAH' },
    { price: amt.valueAreaLow, color: 'rgba(59, 130, 246, 0.5)', label: 'VAL' },
  ].forEach(level => {
    const y = series.priceToCoordinate(level.price);
    if (y !== null) {
      ctx.strokeStyle = level.color;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvas.width, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  });
};

/**
 * Draw time markers (Session Open, IB Close)
 * Simplified version - uses data indices instead of timestamps
 */
export const drawTimeMarkers = (
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  data: OHLCData[],
  amt: AMTAnalysis
) => {
  const timeScale = chart.timeScale();
  
  // Draw OPEN marker at first visible candle
  if (data.length > 0) {
    const firstTime = (new Date(data[0].time).getTime() / 1000 + 19800) as UTCTimestamp;
    const x = timeScale.timeToCoordinate(firstTime);
    
    if (x !== null) {
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
      ctx.setLineDash([]);
      
      ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
      ctx.font = 'bold 9px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('OPEN', x, 15);
    }
  }
  
  // Draw IB marker at ~20% of visible data
  const ibIdx = Math.floor(data.length * 0.2);
  if (data[ibIdx]) {
    const ibTime = (new Date(data[ibIdx].time).getTime() / 1000 + 19800) as UTCTimestamp;
    const x = timeScale.timeToCoordinate(ibTime);
    
    if (x !== null) {
      ctx.strokeStyle = 'rgba(250, 204, 21, 0.7)';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
      ctx.setLineDash([]);
      
      ctx.fillStyle = 'rgba(250, 204, 21, 0.7)';
      ctx.font = 'bold 9px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('IB', x, 15);
    }
  }
};

/**
 * Draw IB retest zone box
 */
export const drawIBRetestZone = (
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  data: OHLCData[],
  amt: AMTAnalysis
) => {
  const timeScale = chart.timeScale();
  const visibleRange = timeScale.getVisibleLogicalRange();
  if (!visibleRange) return;

  const breakLevel = amt.breakLevel;
  const breakDir = amt.breakDirection;

  if (!breakLevel || !breakDir) return;

  const breakIdx = data.findIndex(d => {
    const ts = (new Date(d.time).getTime() / 1000 + 19800) as UTCTimestamp;
    const x = timeScale.timeToCoordinate(ts);
    return x !== null;
  });

  if (breakIdx === -1) return;

  const breakTime = (new Date(data[breakIdx].time).getTime() / 1000 + 19800) as UTCTimestamp;
  const startX = timeScale.timeToCoordinate(breakTime);

  if (startX === null) return;

  const boxTop = breakDir === 'UP' ? series.priceToCoordinate(breakLevel * 1.02) : series.priceToCoordinate(breakLevel);
  const boxBottom = breakDir === 'UP' ? series.priceToCoordinate(breakLevel) : series.priceToCoordinate(breakLevel * 0.98);

  if (boxTop === null || boxBottom === null) return;

  ctx.fillStyle = breakDir === 'UP' ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)';
  ctx.fillRect(startX, Math.min(boxTop, boxBottom), canvas.width - startX, Math.abs(boxBottom - boxTop));

  ctx.strokeStyle = breakDir === 'UP' ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(startX, boxTop);
  ctx.lineTo(canvas.width, boxTop);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(startX, boxBottom);
  ctx.lineTo(canvas.width, boxBottom);
  ctx.stroke();
  ctx.setLineDash([]);
};

/**
 * Draw volume profile bars (horizontal histogram)
 */
export const drawProfileBars = (
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  series: ISeriesApi<"Candlestick">,
  profile: Array<{ price: number; volume: number }>,
  cfg: ChartConfig,
  maxBarWidth: number = 60
) => {
  if (profile.length === 0) return;

  const maxVol = Math.max(...profile.map(p => p.volume));
  const barHeight = 3;

  profile.forEach(p => {
    const y = series.priceToCoordinate(p.price);
    if (y === null) return;

    const barWidth = (p.volume / maxVol) * maxBarWidth;

    ctx.fillStyle = hexToRgba(cfg.bullColor || '#22c55e', 0.3);
    ctx.fillRect(canvas.width - barWidth, y - barHeight / 2, barWidth, barHeight);
  });
};

/**
 * Draw vertical label on canvas
 */
export const drawVerticalLabel = (
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  text: string,
  x: number,
  color: string
) => {
  ctx.save();
  ctx.translate(x, canvas.height / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = color;
  ctx.font = 'bold 10px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(text, 0, 0);
  ctx.restore();
};

/**
 * Draw volume profile (horizontal histogram)
 */
export const drawVolumeProfile = (
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  series: ISeriesApi<"Candlestick">,
  amt: AMTAnalysis,
  cfg: ChartConfig
) => {
  const profile = amt.profile;
  if (!profile || profile.length === 0) return;

  drawProfileBars(ctx, canvas, series, profile, cfg);
};
