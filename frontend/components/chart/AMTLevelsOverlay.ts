import { AMTAnalysis, OHLCData } from '../../types';

/**
 * AMTLevelsOverlay - Pure data transformation layer for AMT price levels
 * 
 * This module extracts the price line configuration logic from ChartScene.tsx
 * into a testable, pure function. It transforms AMTAnalysis data into
 * TradingView Lightweight Charts price line configurations.
 * 
 * Benefits:
 * - 100% testable (pure functions, no side effects)
 * - Separates data logic from rendering
 * - Easy to validate price line configurations
 * - Supports VP mode filtering (session/combined/daily/leg)
 */

export interface PriceLineConfig {
  price: number;
  color: string;
  lineWidth: number;
  lineStyle: 'Solid' | 'Dashed' | 'Dotted';
  axisLabelVisible: boolean;
  title: string;
}

export interface AMTLevelsOverlayOptions {
  mode: 'STANDARD';
  showVolumeProfile: boolean;
  vpMode: 'session' | 'combined' | 'daily' | 'leg';
  bullColor?: string;
  bearColor?: string;
}

/**
 * Calculate VWAP slope and determine color based on recent trend
 * 
 * @param data - Recent OHLCV data with VWAP values
 * @returns VWAP color hex code and direction label
 */
export function calculateVWAPColor(data: OHLCData[]): { color: string; label: string } {
  const recentVwaps = data.slice(-10).map(d => d.vwap).filter(v => v > 0);
  
  if (recentVwaps.length < 3) {
    return { color: '#06b6d4', label: 'VWAP' }; // Default cyan
  }

  const midPoint = Math.floor(recentVwaps.length / 2);
  const firstHalf = recentVwaps.slice(0, midPoint);
  const secondHalf = recentVwaps.slice(midPoint);
  
  const avgFirst = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length;
  const avgSecond = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length;
  const slope = avgSecond - avgFirst;
  const threshold = avgFirst * 0.001; // 0.1% change threshold

  if (slope > threshold) {
    return { color: '#22c55e', label: 'VWAP ↑' }; // Green: rising
  } else if (slope < -threshold) {
    return { color: '#ef4444', label: 'VWAP ↓' }; // Red: declining
  }

  return { color: '#06b6d4', label: 'VWAP' }; // Default cyan
}

/**
 * Generate AMT price line configurations from analysis data
 * 
 * @param amt - AMT analysis data
 * @param options - Display options
 * @param data - OHLCV data for VWAP slope calculation
 * @returns Array of price line configurations
 */
export function generateAMTPriceLines(
  amt: AMTAnalysis,
  options: AMTLevelsOverlayOptions,
  data: OHLCData[] = []
): PriceLineConfig[] {
  const lines: PriceLineConfig[] = [];

  // Skip if VP disabled
  if (!options.showVolumeProfile) {
    return lines;
  }

  const { vpMode } = options;

  // === Session Levels (session + combined modes) ===
  if (vpMode === 'session' || vpMode === 'combined') {
    // Session POC (yellow solid)
    if (amt.poc && amt.poc > 0) {
      lines.push({
        price: amt.poc,
        color: '#facc15',
        lineWidth: 2,
        lineStyle: 'Solid',
        axisLabelVisible: true,
        title: 'S-POC',
      });
    }

    // Session VAH (blue dashed)
    if (amt.valueAreaHigh && amt.valueAreaHigh > 0) {
      lines.push({
        price: amt.valueAreaHigh,
        color: '#3b82f6',
        lineWidth: 1,
        lineStyle: 'Dashed',
        axisLabelVisible: true,
        title: 'S-VAH',
      });
    }

    // Session VAL (blue dashed)
    if (amt.valueAreaLow && amt.valueAreaLow > 0) {
      lines.push({
        price: amt.valueAreaLow,
        color: '#3b82f6',
        lineWidth: 1,
        lineStyle: 'Dashed',
        axisLabelVisible: true,
        title: 'S-VAL',
      });
    }

    // LVN lines (amber dotted — max 4 prominent nodes)
    if (amt.lvns && amt.lvns.length > 0) {
      amt.lvns.slice(0, 4).forEach(lvn => {
        lines.push({
          price: lvn,
          color: '#fb923c',
          lineWidth: 1,
          lineStyle: 'Dotted',
          axisLabelVisible: true,
          title: 'LVN',
        });
      });
    }

    // HVN lines (emerald dashed — max 4 prominent nodes)
    if (amt.hvns && amt.hvns.length > 0) {
      amt.hvns.slice(0, 4).forEach(hvn => {
        lines.push({
          price: hvn,
          color: '#34d399',
          lineWidth: 1,
          lineStyle: 'Dashed',
          axisLabelVisible: true,
          title: 'HVN',
        });
      });
    }

    // IB High/Low (orange solid)
    if (amt.ibHigh && amt.ibHigh > 0) {
      const ibHighTitle = amt.breakDirection === 'UP' ? 'IB HIGH [BROKEN ↑]' : 'IB HIGH';
      lines.push({
        price: amt.ibHigh,
        color: '#fb923c',
        lineWidth: 2,
        lineStyle: 'Solid',
        axisLabelVisible: true,
        title: ibHighTitle,
      });
    }

    if (amt.ibLow && amt.ibLow > 0) {
      const ibLowTitle = amt.breakDirection === 'DOWN' ? 'IB LOW [BROKEN ↓]' : 'IB LOW';
      lines.push({
        price: amt.ibLow,
        color: '#fb923c',
        lineWidth: 2,
        lineStyle: 'Solid',
        axisLabelVisible: true,
        title: ibLowTitle,
      });
    }

    // VWAP + sigma bands
    if (amt.sessionVwap && amt.sessionVwap > 0) {
      const vwapStyle = calculateVWAPColor(data);
      
      lines.push({
        price: amt.sessionVwap,
        color: vwapStyle.color,
        lineWidth: 2,
        lineStyle: 'Solid',
        axisLabelVisible: true,
        title: vwapStyle.label,
      });

      // ±1σ bands
      if (amt.vwapUpper1 && amt.vwapUpper1 > 0) {
        lines.push({
          price: amt.vwapUpper1,
          color: '#06b6d4',
          lineWidth: 1,
          lineStyle: 'Dashed',
          axisLabelVisible: true,
          title: '+1σ',
        });
      }

      if (amt.vwapLower1 && amt.vwapLower1 > 0) {
        lines.push({
          price: amt.vwapLower1,
          color: '#06b6d4',
          lineWidth: 1,
          lineStyle: 'Dashed',
          axisLabelVisible: true,
          title: '-1σ',
        });
      }

      // ±2σ bands
      if (amt.vwapUpper2 && amt.vwapUpper2 > 0) {
        lines.push({
          price: amt.vwapUpper2,
          color: '#0891b2',
          lineWidth: 1,
          lineStyle: 'Dotted',
          axisLabelVisible: true,
          title: '+2σ FADE',
        });
      }

      if (amt.vwapLower2 && amt.vwapLower2 > 0) {
        lines.push({
          price: amt.vwapLower2,
          color: '#0891b2',
          lineWidth: 1,
          lineStyle: 'Dotted',
          axisLabelVisible: true,
          title: '-2σ FADE',
        });
      }
    }

    // Prior day levels (grey dashed)
    if (amt.priorVah && amt.priorVah > 0) {
      lines.push({
        price: amt.priorVah,
        color: '#6b7280',
        lineWidth: 1,
        lineStyle: 'Dashed',
        axisLabelVisible: true,
        title: 'Prior VAH',
      });
    }

    if (amt.priorVal && amt.priorVal > 0) {
      lines.push({
        price: amt.priorVal,
        color: '#6b7280',
        lineWidth: 1,
        lineStyle: 'Dashed',
        axisLabelVisible: true,
        title: 'Prior VAL',
      });
    }

    if (amt.priorPoc && amt.priorPoc > 0) {
      lines.push({
        price: amt.priorPoc,
        color: '#6b7280',
        lineWidth: 1,
        lineStyle: 'Dashed',
        axisLabelVisible: true,
        title: 'Prior POC',
      });
    }
  }

  // === Leg Levels (leg + combined modes) ===
  if (vpMode === 'leg' || vpMode === 'combined') {
    if (amt.legPoc && amt.legPoc > 0) {
      lines.push({
        price: amt.legPoc,
        color: '#f97316',
        lineWidth: 1,
        lineStyle: 'Solid',
        axisLabelVisible: true,
        title: 'L-POC',
      });
    }

    if (amt.legVah && amt.legVah > 0) {
      lines.push({
        price: amt.legVah,
        color: '#f97316',
        lineWidth: 1,
        lineStyle: 'Dashed',
        axisLabelVisible: true,
        title: 'L-VAH',
      });
    }

    if (amt.legVal && amt.legVal > 0) {
      lines.push({
        price: amt.legVal,
        color: '#f97316',
        lineWidth: 1,
        lineStyle: 'Dashed',
        axisLabelVisible: true,
        title: 'L-VAL',
      });
    }
  }

  return lines;
}
