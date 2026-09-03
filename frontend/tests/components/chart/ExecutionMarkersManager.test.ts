import { describe, it, expect } from 'vitest';
import {
  generateEntryMarkers,
  generateClosedTradeMarkers,
  generateIBBreakMarker,
  generateCVDDivergenceMarkers,
  generateAcceptanceRejectionMarkers,
  generateAllExecutionMarkers,
  ChartMarker,
} from '../../../components/chart/ExecutionMarkersManager';

describe('ExecutionMarkersManager', () => {
  describe('generateEntryMarkers', () => {
    it('generates LONG entry marker', () => {
      const positions = [{
        id: 'pos-1',
        side: 'LONG' as const,
        entryPrice: 50000,
        entryTime: '2024-01-01T09:30:00Z',
      } as any];

      const markers = generateEntryMarkers(positions);
      expect(markers).toHaveLength(1);
      expect(markers[0].position).toBe('belowBar');
      expect(markers[0].color).toBe('#10b981');
      expect(markers[0].shape).toBe('arrowUp');
      expect(markers[0].text).toBe('LONG @50000.00');
      expect(markers[0].size).toBe(2);
    });

    it('generates SHORT entry marker', () => {
      const positions = [{
        id: 'pos-1',
        side: 'SHORT' as const,
        entryPrice: 50100,
        entryTime: '2024-01-01T10:00:00Z',
      } as any];

      const markers = generateEntryMarkers(positions);
      expect(markers[0].position).toBe('aboveBar');
      expect(markers[0].color).toBe('#ef4444');
      expect(markers[0].shape).toBe('arrowDown');
    });

    it('generates multiple entry markers', () => {
      const positions = [
        { side: 'LONG', entryPrice: 50000, entryTime: '2024-01-01T09:30:00Z' } as any,
        { side: 'SHORT', entryPrice: 50100, entryTime: '2024-01-01T10:00:00Z' } as any,
      ];

      const markers = generateEntryMarkers(positions);
      expect(markers).toHaveLength(2);
    });

    it('returns empty array for no positions', () => {
      const markers = generateEntryMarkers([]);
      expect(markers).toHaveLength(0);
    });
  });

  describe('generateClosedTradeMarkers', () => {
    it('generates entry and exit markers', () => {
      const trades = [{
        id: 'trade-1',
        side: 'LONG' as const,
        entryPrice: 50000,
        entryTime: '2024-01-01T09:30:00Z',
        exitPrice: 50200,
        exitTime: '2024-01-01T11:00:00Z',
        pnl: 200,
        closeReason: 'TP HIT',
      } as any];

      const markers = generateClosedTradeMarkers(trades);
      expect(markers).toHaveLength(2);
      expect(markers[0].text).toBe('LONG @50000.00');
      expect(markers[1].text).toBe('TP HIT +200.00');
      expect(markers[1].shape).toBe('circle');
      expect(markers[1].color).toBe('#10b981');
    });

    it('shows red color for losing trades', () => {
      const trades = [{
        side: 'LONG',
        entryPrice: 50000,
        entryTime: '2024-01-01T09:30:00Z',
        exitPrice: 49900,
        exitTime: '2024-01-01T11:00:00Z',
        pnl: -100,
        closeReason: 'SL HIT',
      } as any];

      const markers = generateClosedTradeMarkers(trades);
      expect(markers[1].color).toBe('#ef4444');
      expect(markers[1].text).toBe('SL HIT -100.00');
    });

    it('handles missing exit time', () => {
      const trades = [{
        side: 'LONG',
        entryPrice: 50000,
        entryTime: '2024-01-01T09:30:00Z',
        exitPrice: null,
        exitTime: null,
        pnl: 0,
      } as any];

      const markers = generateClosedTradeMarkers(trades);
      expect(markers).toHaveLength(1);
    });

    it('defaults to EXIT if no close reason', () => {
      const trades = [{
        side: 'LONG',
        entryPrice: 50000,
        entryTime: '2024-01-01T09:30:00Z',
        exitPrice: 50100,
        exitTime: '2024-01-01T11:00:00Z',
        pnl: 100,
        closeReason: null,
      } as any];

      const markers = generateClosedTradeMarkers(trades);
      expect(markers[1].text).toContain('EXIT');
    });
  });

  describe('generateIBBreakMarker', () => {
    const data = [
      { time: '2024-01-01T09:15:00Z', close: 50000 },
      { time: '2024-01-01T09:30:00Z', close: 50050 },
      { time: '2024-01-01T09:45:00Z', close: 50100 },
    ] as any[];

    it('generates marker for UP break', () => {
      const amt = { breakDirection: 'UP', breakLevel: 50075 } as any;
      const marker = generateIBBreakMarker(data, amt);
      expect(marker).not.toBeNull();
      expect(marker?.text).toBe('IB BREAK UP @50075.00');
      expect(marker?.shape).toBe('arrowUp');
    });

    it('generates marker for DOWN break', () => {
      const downData = [
        { time: '2024-01-01T09:15:00Z', close: 50100 },
        { time: '2024-01-01T09:30:00Z', close: 50050 },
        { time: '2024-01-01T09:45:00Z', close: 50000 },
      ] as any[];

      const amt = { breakDirection: 'DOWN', breakLevel: 50075 } as any;
      const marker = generateIBBreakMarker(downData, amt);
      expect(marker).not.toBeNull();
      expect(marker?.text).toBe('IB BREAK DOWN @50075.00');
      expect(marker?.shape).toBe('arrowDown');
    });

    it('returns null when no break detected', () => {
      const amt = { breakDirection: 'UP', breakLevel: 50200 } as any;
      const marker = generateIBBreakMarker(data, amt);
      expect(marker).toBeNull();
    });

    it('returns null when no break direction', () => {
      const amt = { breakDirection: null, breakLevel: 50000 } as any;
      const marker = generateIBBreakMarker(data, amt);
      expect(marker).toBeNull();
    });
  });

  describe('generateCVDDivergenceMarkers', () => {
    const data = [
      { time: '2024-01-01T09:15:00Z' },
      { time: '2024-01-01T09:30:00Z' },
      { time: '2024-01-01T09:45:00Z' },
      { time: '2024-01-01T10:00:00Z' },
      { time: '2024-01-01T10:15:00Z' },
    ] as any[];

    it('generates markers for BEARISH divergence', () => {
      const amt = { cvdDivergence: 'BEARISH' } as any;
      const markers = generateCVDDivergenceMarkers(data, amt);
      expect(markers).toHaveLength(3);
      expect(markers[0].text).toBe('⚡CVD DIV');
      expect(markers[0].position).toBe('aboveBar');
    });

    it('generates markers for BULLISH divergence', () => {
      const amt = { cvdDivergence: 'BULLISH' } as any;
      const markers = generateCVDDivergenceMarkers(data, amt);
      expect(markers[0].position).toBe('belowBar');
    });

    it('returns empty array when no divergence', () => {
      const markers = generateCVDDivergenceMarkers(data, null);
      expect(markers).toHaveLength(0);
    });
  });

  describe('generateAcceptanceRejectionMarkers', () => {
    const data = [{ time: '2024-01-01T10:00:00Z' }] as any[];

    it('generates acceptance above marker', () => {
      const amt = { acceptanceAbove: true } as any;
      const markers = generateAcceptanceRejectionMarkers(data, amt);
      expect(markers).toHaveLength(1);
      expect(markers[0].text).toBe('ACCEPT ABOVE');
    });

    it('generates rejection from high marker', () => {
      const amt = { rejectionAtHigh: true } as any;
      const markers = generateAcceptanceRejectionMarkers(data, amt);
      expect(markers[0].text).toBe('REJECT VAH');
    });

    it('generates acceptance below marker', () => {
      const amt = { acceptanceBelow: true } as any;
      const markers = generateAcceptanceRejectionMarkers(data, amt);
      expect(markers[0].text).toBe('ACCEPT BELOW');
    });

    it('generates rejection from low marker', () => {
      const amt = { rejectionAtLow: true } as any;
      const markers = generateAcceptanceRejectionMarkers(data, amt);
      expect(markers[0].text).toBe('REJECT VAL');
    });

    it('returns empty array when no conditions met', () => {
      const amt = {} as any;
      const markers = generateAcceptanceRejectionMarkers(data, amt);
      expect(markers).toHaveLength(0);
    });
  });

  describe('generateAllExecutionMarkers', () => {
    it('generates markers in STANDARD mode', () => {
      const positions = [{ side: 'LONG', entryPrice: 50000, entryTime: '2024-01-01T09:30:00Z' } as any];
      const data = [{ time: '2024-01-01T09:15:00Z', close: 50000 }] as any[];
      const amt = { cvdDivergence: 'BEARISH' } as any;

      const markers = generateAllExecutionMarkers(positions, [], data, amt, { mode: 'STANDARD' });
      expect(markers.length).toBeGreaterThan(0);
    });

    it('limits markers to maxMarkers option', () => {
      const positions = Array(50).fill(null).map((_, i) => ({
        side: 'LONG',
        entryPrice: 50000 + i,
        entryTime: `2024-01-01T09:${30 + i}:00Z`,
      } as any));

      const markers = generateAllExecutionMarkers(positions, [], [], null, {
        mode: 'STANDARD',
        maxMarkers: 10,
      });

      expect(markers.length).toBeLessThanOrEqual(10);
    });

    it('generates VARS bullish and bearish reclaim markers', () => {
      const data = [{ time: '2024-01-01T09:15:00Z', close: 50000 }] as any[];
      const amtBull = {
        vars: {
          bullishReclaim: true,
          bearishReclaim: false,
          signalSource: 'CVA',
        },
      } as any;

      const markers = generateAllExecutionMarkers([], [], data, amtBull, { mode: 'STANDARD' });
      const varsMarker = markers.find(m => m.text === 'CVA BUY');
      expect(varsMarker).toBeDefined();
      expect(varsMarker?.color).toBe('#089981');
      expect(varsMarker?.shape).toBe('arrowUp');
      expect(varsMarker?.position).toBe('belowBar');
    });
  });

});
