/**
 * HARSIManager - Heikin Ashi RSI Oscillator (JayRogers "HARSI •")
 * 
 * Mathematical implementation of JayRogers' Pine Script indicator:
 * - Zero-median Wilder RSI: f_zrsi(source, length) = rsi(source, length) - 50
 * - Heikin-Ashi RSI candles:
 *     openRSI  = closeRSI[1]
 *     highRSI  = max(highRSI_raw, lowRSI_raw)
 *     lowRSI   = min(highRSI_raw, lowRSI_raw)
 *     haClose  = (openRSI + highRSI + lowRSI + closeRSI) / 4
 *     haOpen   = na(open[smoothing]) ? (openRSI + closeRSI) / 2 : (open[1]*smoothing + close[1]) / (smoothing + 1)
 *     haHigh   = max(highRSI, max(haOpen, haClose))
 *     haLow    = min(lowRSI, min(haOpen, haClose))
 * - Smoothed mode RSI overlay and histogram
 * - Zero-median Stochastic RSI (StochK, StochD)
 * - Reference boundaries: OB (+20), OB Extreme (+30), Median (0), OS (-20), OS Extreme (-30)
 */

import { CandleDataPoint } from './CandleSeriesManager';

export interface HARSIOptions {
  lenHARSI?: number;      // Default: 14
  smoothing?: number;     // Default: 1 (HARSI Open smoothing)
  lenRSI?: number;        // Default: 7 (RSI overlay length)
  mode?: boolean;         // Default: true (Smoothed RSI mode)
  showPlot?: boolean;     // Default: true (Show RSI Line)
  showHist?: boolean;     // Default: true (Show RSI Histogram)
  showStoch?: boolean;    // Default: false (Show Stoch RSI)
  smoothK?: number;       // Default: 3
  smoothD?: number;       // Default: 3
  stochLen?: number;      // Default: 14
  stochFit?: number;      // Default: 80 (Scaling %)
  upper?: number;         // Default: 20
  upperx?: number;        // Default: 30
  lower?: number;         // Default: -20
  lowerx?: number;        // Default: -30
  colUp?: string;         // Default: '#26a69a' (teal/green) or '#3753f5'
  colDown?: string;       // Default: '#ef5350' (red) or '#f537b1'
  colWick?: string;       // Default: '#94a3b8'
  colRSI?: string;        // Default: '#fac832'
  showMarkers?: boolean;  // Default: true (Crossover Buy/Sell markers)
}

export interface HARSICandlePoint {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  color?: string;
}

export interface HARSILinePoint {
  time: number;
  value: number;
}

export interface HARSIHistPoint {
  time: number;
  value: number;
  color: string;
}

export interface HARSIMarkerPoint {
  time: number;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  text: string;
  size?: number;
}

export interface HARSIResult {
  candles: HARSICandlePoint[];
  rsiLine: HARSILinePoint[];
  rsiHist: HARSIHistPoint[];
  stochK: HARSILinePoint[];
  stochD: HARSILinePoint[];
  markers: HARSIMarkerPoint[];
  levels: {
    upperx: number;
    upper: number;
    median: number;
    lower: number;
    lowerx: number;
  };
}

export const DEFAULT_HARSI_OPTIONS: Required<HARSIOptions> = {
  lenHARSI: 14,
  smoothing: 1,
  lenRSI: 7,
  mode: true,
  showPlot: true,
  showHist: true,
  showStoch: false,
  showMarkers: true,
  smoothK: 3,
  smoothD: 3,
  stochLen: 14,
  stochFit: 80,
  upper: 20,
  upperx: 30,
  lower: -20,
  lowerx: -30,
  colUp: '#26a69a',
  colDown: '#ef5350',
  colWick: '#94a3b8',
  colRSI: '#fac832',
};

/**
 * Pine Script RMA (Wilder's Moving Average):
 * rma[i] = (rma[i-1] * (length - 1) + src[i]) / length
 */
export function computeRMA(values: number[], length: number): number[] {
  const n = values.length;
  if (n === 0) return [];
  const result: number[] = new Array(n);
  if (length <= 0) length = 1;

  let sum = 0;
  for (let i = 0; i < n; i++) {
    if (i < length) {
      sum += values[i];
      result[i] = sum / (i + 1);
    } else {
      result[i] = (result[i - 1] * (length - 1) + values[i]) / length;
    }
  }
  return result;
}

/**
 * Standard Wilder's RSI calculation:
 * Returns array of RSI values between 0 and 100.
 */
export function computeWilderRSI(values: number[], length: number): number[] {
  const n = values.length;
  if (n === 0) return [];
  if (n === 1) return [50];

  const gains: number[] = new Array(n).fill(0);
  const losses: number[] = new Array(n).fill(0);

  for (let i = 1; i < n; i++) {
    const diff = values[i] - values[i - 1];
    if (diff > 0) {
      gains[i] = diff;
    } else {
      losses[i] = -diff;
    }
  }

  const rmaGain = computeRMA(gains, length);
  const rmaLoss = computeRMA(losses, length);
  const rsi: number[] = new Array(n);

  for (let i = 0; i < n; i++) {
    if (i === 0) {
      rsi[i] = 50;
      continue;
    }
    const up = rmaGain[i];
    const down = rmaLoss[i];

    if (down === 0 && up === 0) {
      rsi[i] = 50;
    } else if (down === 0) {
      rsi[i] = 100;
    } else if (up === 0) {
      rsi[i] = 0;
    } else {
      const rs = up / down;
      rsi[i] = 100 - (100 / (1 + rs));
    }
  }

  return rsi;
}

/**
 * Zero-median RSI: f_zrsi(src, length) = rsi(src, length) - 50
 */
export function computeZeroMedianRSI(values: number[], length: number): number[] {
  const rsi = computeWilderRSI(values, length);
  return rsi.map(val => Number((val - 50).toFixed(4)));
}

/**
 * Simple Moving Average (SMA)
 */
export function computeSMA(values: number[], period: number): number[] {
  const n = values.length;
  if (n === 0) return [];
  const result: number[] = new Array(n);
  let sum = 0;

  for (let i = 0; i < n; i++) {
    sum += values[i];
    if (i < period) {
      result[i] = Number((sum / (i + 1)).toFixed(4));
    } else {
      sum -= values[i - period];
      result[i] = Number((sum / period).toFixed(4));
    }
  }
  return result;
}

/**
 * Compute JayRogers' Heikin Ashi RSI Oscillator (HARSI)
 */
export function computeHARSI(
  candles: CandleDataPoint[],
  options: HARSIOptions = {}
): HARSIResult {
  const opts: Required<HARSIOptions> = { ...DEFAULT_HARSI_OPTIONS, ...options };
  const levels = {
    upperx: opts.upperx,
    upper: opts.upper,
    median: 0,
    lower: opts.lower,
    lowerx: opts.lowerx,
  };

  if (!candles || candles.length === 0) {
    return {
      candles: [],
      rsiLine: [],
      rsiHist: [],
      stochK: [],
      stochD: [],
      markers: [],
      levels,
    };
  }

  const n = candles.length;
  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const ohlc4 = candles.map(c => (c.open + c.high + c.low + c.close) / 4);

  // 1. Base zero-median RSIs for HA candles
  const closeRSI = computeZeroMedianRSI(closes, opts.lenHARSI);
  const highRSI_raw = computeZeroMedianRSI(highs, opts.lenHARSI);
  const lowRSI_raw = computeZeroMedianRSI(lows, opts.lenHARSI);

  // 2. HA calculations
  const haCandles: HARSICandlePoint[] = new Array(n);
  let prevHaOpen = 0;
  let prevHaClose = 0;

  for (let i = 0; i < n; i++) {
    const time = candles[i].time;
    const curCloseRSI = closeRSI[i];
    const openRSI = i === 0 ? curCloseRSI : closeRSI[i - 1];

    const curHighRaw = highRSI_raw[i];
    const curLowRaw = lowRSI_raw[i];
    const highRSI = Math.max(curHighRaw, curLowRaw);
    const lowRSI = Math.min(curHighRaw, curLowRaw);

    // HA Close = (openRSI + highRSI + lowRSI + closeRSI) / 4
    const haClose = (openRSI + highRSI + lowRSI + curCloseRSI) / 4;

    // HA Open:
    // Pine: _open := na( _open[ i_smoothing ] ) ? ( _openRSI + _closeRSI ) / 2 :
    //                ( ( _open[1] * i_smoothing ) + _close[1] ) / ( i_smoothing + 1 )
    let haOpen: number;
    if (i < opts.smoothing || i === 0) {
      haOpen = (openRSI + curCloseRSI) / 2;
    } else {
      haOpen = ((prevHaOpen * opts.smoothing) + prevHaClose) / (opts.smoothing + 1);
    }

    const haHigh = Math.max(highRSI, Math.max(haOpen, haClose));
    const haLow = Math.min(lowRSI, Math.min(haOpen, haClose));

    const color = haClose >= haOpen ? opts.colUp : opts.colDown;

    haCandles[i] = {
      time,
      open: Number(haOpen.toFixed(4)),
      high: Number(haHigh.toFixed(4)),
      low: Number(haLow.toFixed(4)),
      close: Number(haClose.toFixed(4)),
      color,
    };

    prevHaOpen = haOpen;
    prevHaClose = haClose;
  }

  // 3. RSI Overlay and Histogram (f_rsi)
  const zrsiOverlay = computeZeroMedianRSI(ohlc4, opts.lenRSI);
  const rsiValues: number[] = new Array(n);

  let prevSmoothed: number | null = null;
  for (let i = 0; i < n; i++) {
    const zrsi = zrsiOverlay[i];
    if (opts.mode) {
      const smoothed = prevSmoothed === null ? zrsi : (prevSmoothed + zrsi) / 2;
      prevSmoothed = smoothed;
      rsiValues[i] = Number(smoothed.toFixed(4));
    } else {
      rsiValues[i] = zrsi;
    }
  }

  const rsiLine: HARSILinePoint[] = [];
  const rsiHist: HARSIHistPoint[] = [];

  for (let i = 0; i < n; i++) {
    const t = candles[i].time;
    const v = rsiValues[i];

    if (opts.showPlot) {
      rsiLine.push({ time: t, value: v });
    }

    if (opts.showHist) {
      const histCol = v >= 0 ? 'rgba(38, 166, 154, 0.35)' : 'rgba(239, 83, 80, 0.35)';
      rsiHist.push({ time: t, value: v, color: histCol });
    }
  }

  // 4. Stochastic RSI (f_zstoch)
  const stochK: HARSILinePoint[] = [];
  const stochD: HARSILinePoint[] = [];

  if (opts.showStoch) {
    const zstochArr: number[] = new Array(n);

    for (let i = 0; i < n; i++) {
      const startIdx = Math.max(0, i - opts.stochLen + 1);
      let highVal = -Infinity;
      let lowVal = Infinity;
      for (let j = startIdx; j <= i; j++) {
        if (rsiValues[j] > highVal) highVal = rsiValues[j];
        if (rsiValues[j] < lowVal) lowVal = rsiValues[j];
      }
      const range = highVal - lowVal;
      const rawStoch = range === 0 ? 50 : ((rsiValues[i] - lowVal) / range) * 100;
      zstochArr[i] = rawStoch - 50;
    }

    const smoothedZStoch = computeSMA(zstochArr, opts.smoothK);
    const scaledK: number[] = smoothedZStoch.map(val => (val / 100) * opts.stochFit);
    const smoothedD: number[] = computeSMA(scaledK, opts.smoothD);

    for (let i = 0; i < n; i++) {
      stochK.push({ time: candles[i].time, value: Number(scaledK[i].toFixed(4)) });
      stochD.push({ time: candles[i].time, value: Number(smoothedD[i].toFixed(4)) });
    }
  }

  // 5. Crossover Markers: RSI vs HARSI Candle
  const markers: HARSIMarkerPoint[] = [];

  if (opts.showMarkers && n > 1) {
    for (let i = 1; i < n; i++) {
      const prevRsi = rsiValues[i - 1];
      const currRsi = rsiValues[i];
      const prevClose = haCandles[i - 1].close;
      const currClose = haCandles[i].close;
      const t = candles[i].time;

      // Bullish Crossover: RSI line crosses above HARSI candle
      if (prevRsi <= prevClose && currRsi > currClose) {
        markers.push({
          time: t,
          position: 'belowBar',
          color: '#00c896',
          shape: 'arrowUp',
          text: 'BUY',
          size: 1,
        });
      }
      // Bearish Crossunder: RSI line crosses below HARSI candle
      else if (prevRsi >= prevClose && currRsi < currClose) {
        markers.push({
          time: t,
          position: 'aboveBar',
          color: '#ff4757',
          shape: 'arrowDown',
          text: 'SELL',
          size: 1,
        });
      }
    }
  }

  return {
    candles: haCandles,
    rsiLine,
    rsiHist,
    stochK,
    stochD,
    markers,
    levels,
  };
}
