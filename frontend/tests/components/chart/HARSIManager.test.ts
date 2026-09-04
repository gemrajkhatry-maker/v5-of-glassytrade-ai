import { describe, it, expect } from 'vitest';
import {
  computeRMA,
  computeWilderRSI,
  computeZeroMedianRSI,
  computeSMA,
  computeHARSI,
  DEFAULT_HARSI_OPTIONS,
} from '../../../components/chart/HARSIManager';
import { CandleDataPoint } from '../../../components/chart/CandleSeriesManager';

describe('HARSIManager', () => {
  describe('computeRMA', () => {
    it('handles empty input', () => {
      expect(computeRMA([], 14)).toEqual([]);
    });

    it('computes initial values as cumulative averages, then RMA smoothing', () => {
      const values = [10, 20, 30, 40, 50];
      const rma = computeRMA(values, 3);
      expect(rma.length).toBe(5);
      expect(rma[0]).toBe(10);
      expect(rma[1]).toBe(15);
      expect(rma[2]).toBe(20);
      // for i=3, rma = (rma[2] * 2 + 40) / 3 = (40 + 40) / 3 = 80/3 = 26.666...
      expect(rma[3]).toBeCloseTo(80 / 3, 4);
    });
  });

  describe('computeWilderRSI & computeZeroMedianRSI', () => {
    it('returns 50 for single value', () => {
      expect(computeWilderRSI([100], 14)).toEqual([50]);
      expect(computeZeroMedianRSI([100], 14)).toEqual([0]);
    });

    it('oscillates between 0 and 100 for Wilder RSI, and -50 to +50 for zero median RSI', () => {
      // Monotonically increasing prices -> RSI should approach 100, zero-median should approach +50
      const upValues = Array.from({ length: 30 }, (_, i) => 100 + i * 5);
      const rsiUp = computeWilderRSI(upValues, 14);
      const zrsiUp = computeZeroMedianRSI(upValues, 14);

      expect(rsiUp[rsiUp.length - 1]).toBe(100);
      expect(zrsiUp[zrsiUp.length - 1]).toBe(50);

      // Monotonically decreasing prices -> RSI should approach 0, zero-median should approach -50
      const downValues = Array.from({ length: 30 }, (_, i) => 200 - i * 5);
      const rsiDown = computeWilderRSI(downValues, 14);
      const zrsiDown = computeZeroMedianRSI(downValues, 14);

      expect(rsiDown[rsiDown.length - 1]).toBe(0);
      expect(zrsiDown[zrsiDown.length - 1]).toBe(-50);
    });
  });

  describe('computeSMA', () => {
    it('calculates running simple moving average', () => {
      const values = [2, 4, 6, 8, 10];
      const sma = computeSMA(values, 3);
      expect(sma[0]).toBe(2);
      expect(sma[1]).toBe(3);
      expect(sma[2]).toBe(4);
      expect(sma[3]).toBe(6);
      expect(sma[4]).toBe(8);
    });
  });

  describe('computeHARSI', () => {
    it('handles empty candle array gracefully', () => {
      const res = computeHARSI([]);
      expect(res.candles).toEqual([]);
      expect(res.rsiLine).toEqual([]);
      expect(res.rsiHist).toEqual([]);
      expect(res.levels).toEqual({
        upperx: 30,
        upper: 20,
        median: 0,
        lower: -20,
        lowerx: -30,
      });
    });

    it('calculates valid Heikin-Ashi RSI candles and overlays for candle series', () => {
      const baseTime = 1725000000;
      const candles: CandleDataPoint[] = Array.from({ length: 25 }, (_, i) => ({
        time: baseTime + i * 300,
        open: 100 + Math.sin(i / 3) * 5,
        high: 105 + Math.sin(i / 3) * 5,
        low: 95 + Math.sin(i / 3) * 5,
        close: 102 + Math.sin(i / 3) * 5,
      }));

      const res = computeHARSI(candles, {
        lenHARSI: 14,
        smoothing: 1,
        lenRSI: 7,
        mode: true,
        showPlot: true,
        showHist: true,
        showStoch: true,
      });

      expect(res.candles.length).toBe(25);
      expect(res.rsiLine.length).toBe(25);
      expect(res.rsiHist.length).toBe(25);
      expect(res.stochK.length).toBe(25);
      expect(res.stochD.length).toBe(25);

      // Verify HA Candle properties
      res.candles.forEach((c, idx) => {
        expect(c.time).toBe(candles[idx].time);
        expect(c.high).toBeGreaterThanOrEqual(c.open);
        expect(c.high).toBeGreaterThanOrEqual(c.close);
        expect(c.low).toBeLessThanOrEqual(c.open);
        expect(c.low).toBeLessThanOrEqual(c.close);
        // Zero-median boundaries are bounded within [-50, +50]
        expect(c.high).toBeLessThanOrEqual(50);
        expect(c.low).toBeGreaterThanOrEqual(-50);
        expect(c.color).toBeDefined();
      });

      // Verify RSI overlay line is bounded within [-50, +50]
      res.rsiLine.forEach(pt => {
        expect(pt.value).toBeLessThanOrEqual(50);
        expect(pt.value).toBeGreaterThanOrEqual(-50);
      });

      // Verify markers array is generated
      expect(Array.isArray(res.markers)).toBe(true);
    });

    it('generates BUY and SELL markers when RSI crosses above or below HARSI candles', () => {
      const baseTime = 1725000000;
      // Construct candles that clearly swing from downtrend to sharp uptrend and back
      const candles: CandleDataPoint[] = [
        ...Array.from({ length: 15 }, (_, i) => ({
          time: baseTime + i * 300,
          open: 100 - i * 2,
          high: 101 - i * 2,
          low: 98 - i * 2,
          close: 99 - i * 2,
        })),
        ...Array.from({ length: 15 }, (_, i) => ({
          time: baseTime + (15 + i) * 300,
          open: 70 + i * 5,
          high: 76 + i * 5,
          low: 69 + i * 5,
          close: 75 + i * 5,
        })),
      ];

      const res = computeHARSI(candles, { showMarkers: true });
      expect(res.markers.length).toBeGreaterThan(0);

      // Verify marker schema
      const buyMarker = res.markers.find(m => m.text === 'BUY');
      expect(buyMarker).toBeDefined();
      if (buyMarker) {
        expect(buyMarker.shape).toBe('arrowUp');
        expect(buyMarker.position).toBe('belowBar');
        expect(buyMarker.color).toBe('#00c896');
      }

      // Test showMarkers: false
      const resDisabled = computeHARSI(candles, { showMarkers: false });
      expect(resDisabled.markers).toEqual([]);
    });

    it('filters out mid-range neutral oscillations when extremeOnly is true', () => {
      const baseTime = 1704067200;
      // Flat, low-volatility candles fluctuating in neutral range (no extreme OB/OS)
      const neutralCandles = Array.from({ length: 30 }, (_, i) => ({
        time: baseTime + i * 300,
        open: 100 + (i % 2 === 0 ? 0.2 : -0.2),
        high: 100.5,
        low: 99.5,
        close: 100 + (i % 2 === 0 ? -0.2 : 0.2),
      }));

      const resExtreme = computeHARSI(neutralCandles, { showMarkers: true, extremeOnly: true });
      expect(resExtreme.markers).toEqual([]);
    });
  });
});
