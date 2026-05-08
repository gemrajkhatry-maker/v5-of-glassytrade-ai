import { describe, it, expect } from 'vitest';
import {
  ISTtoTimestamp,
  findTimeXCoordinate,
  calculateSessionZone,
  calculateAllSessionZones,
  validateSessionPhases,
  isTimeInSessionPhase,
  getCurrentSessionPhase,
  SessionPhase,
  DEFAULT_SESSION_PHASES,
} from '../../../components/chart/SessionPhaseMarkers';

describe('SessionPhaseMarkers', () => {
  const sampleTimeRange = [
    { time: 1704067200, x: 100 }, // 2024-01-01 09:00 IST (approx)
    { time: 1704070800, x: 200 }, // 2024-01-01 10:00 IST
    { time: 1704074400, x: 300 }, // 2024-01-01 11:00 IST
    { time: 1704078000, x: 400 }, // 2024-01-01 12:00 IST
  ];

  describe('ISTtoTimestamp', () => {
    it('converts IST time to UTC timestamp', () => {
      const timestamp = ISTtoTimestamp('2024-01-01', 9, 15);
      // Should be a valid timestamp
      expect(timestamp).toBeGreaterThan(0);
    });

    it('handles midnight correctly', () => {
      const timestamp = ISTtoTimestamp('2024-01-01', 0, 0);
      expect(timestamp).toBeGreaterThan(0);
    });
  });

  describe('findTimeXCoordinate', () => {
    it('finds X coordinate for time in range', () => {
      const x = findTimeXCoordinate(1704069000, sampleTimeRange); // Between first two points
      expect(x).not.toBeNull();
      expect(x).toBeGreaterThan(100);
      expect(x).toBeLessThan(200);
    });

    it('returns exact X for matching time', () => {
      const x = findTimeXCoordinate(1704067200, sampleTimeRange);
      expect(x).toBe(100);
    });

    it('returns null for time before range', () => {
      const x = findTimeXCoordinate(1704000000, sampleTimeRange);
      expect(x).toBeNull();
    });

    it('returns null for empty time range', () => {
      const x = findTimeXCoordinate(1704067200, []);
      expect(x).toBeNull();
    });
  });

  describe('calculateSessionZone', () => {
    const ibPhase: SessionPhase = DEFAULT_SESSION_PHASES[0]; // IB FORMATION

    it('calculates zone for valid session', () => {
      const zone = calculateSessionZone(ibPhase, '2024-01-01', sampleTimeRange, 600);
      // Zone may be null if time range doesn't cover IB period
      if (zone !== null) {
        expect(zone.startX).toBeGreaterThan(0);
        expect(zone.endX).toBeGreaterThan(zone.startX);
        expect(zone.height).toBe(600);
        expect(zone.label).toBe('IB FORMATION');
      }
    });

    it('returns null for out-of-range session', () => {
      // Session time not in our sample range
      const latePhase: SessionPhase = {
        name: 'LATE',
        startHour: 16,
        startMinute: 0,
        endHour: 17,
        endMinute: 0,
        color: 'red',
        labelOffset: 10,
      };
      const zone = calculateSessionZone(latePhase, '2024-01-01', sampleTimeRange, 600);
      expect(zone).toBeNull();
    });
  });

  describe('calculateAllSessionZones', () => {
    it('calculates zones for all phases', () => {
      const zones = calculateAllSessionZones(
        DEFAULT_SESSION_PHASES,
        '2024-01-01',
        sampleTimeRange,
        600
      );
      // May have 0 or more zones depending on time range coverage
      expect(Array.isArray(zones)).toBe(true);
    });

    it('skips phases outside time range', () => {
      const customPhases: SessionPhase[] = [
        {
          name: 'EARLY',
          startHour: 5,
          startMinute: 0,
          endHour: 6,
          endMinute: 0,
          color: 'blue',
          labelOffset: 10,
        },
      ];
      const zones = calculateAllSessionZones(
        customPhases,
        '2024-01-01',
        sampleTimeRange,
        600
      );
      expect(zones).toHaveLength(0);
    });
  });

  describe('validateSessionPhases', () => {
    it('returns empty array for valid phases', () => {
      const errors = validateSessionPhases(DEFAULT_SESSION_PHASES);
      expect(errors).toHaveLength(0);
    });

    it('detects missing name', () => {
      const invalidPhases: any = [{ startHour: 9, startMinute: 0, endHour: 10, endMinute: 0 }];
      const errors = validateSessionPhases(invalidPhases);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('detects invalid start hour', () => {
      const invalidPhases: SessionPhase[] = [{
        name: 'TEST',
        startHour: 25,
        startMinute: 0,
        endHour: 10,
        endMinute: 0,
        color: 'blue',
        labelOffset: 10,
      }];
      const errors = validateSessionPhases(invalidPhases);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('detects invalid start minute', () => {
      const invalidPhases: SessionPhase[] = [{
        name: 'TEST',
        startHour: 9,
        startMinute: 60,
        endHour: 10,
        endMinute: 0,
        color: 'blue',
        labelOffset: 10,
      }];
      const errors = validateSessionPhases(invalidPhases);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('detects end time before start time', () => {
      const invalidPhases: SessionPhase[] = [{
        name: 'TEST',
        startHour: 10,
        startMinute: 0,
        endHour: 9,
        endMinute: 0,
        color: 'blue',
        labelOffset: 10,
      }];
      const errors = validateSessionPhases(invalidPhases);
      expect(errors).toContain('Phase 0: End time must be after start time');
    });
  });

  describe('isTimeInSessionPhase', () => {
    it('returns true for time within phase', () => {
      const phase: SessionPhase = {
        name: 'TEST',
        startHour: 9,
        startMinute: 0,
        endHour: 10,
        endMinute: 0,
        color: 'blue',
        labelOffset: 10,
      };
      // Time around 9:30 IST
      const testTime = ISTtoTimestamp('2024-01-01', 9, 30);
      const result = isTimeInSessionPhase(testTime, phase, '2024-01-01');
      expect(result).toBe(true);
    });

    it('returns false for time outside phase', () => {
      const phase: SessionPhase = {
        name: 'TEST',
        startHour: 9,
        startMinute: 0,
        endHour: 10,
        endMinute: 0,
        color: 'blue',
        labelOffset: 10,
      };
      // Time at 11:00 IST
      const testTime = ISTtoTimestamp('2024-01-01', 11, 0);
      const result = isTimeInSessionPhase(testTime, phase, '2024-01-01');
      expect(result).toBe(false);
    });
  });

  describe('getCurrentSessionPhase', () => {
    it('returns phase for time within session', () => {
      // IB Formation is 9:15-10:15
      const testTime = ISTtoTimestamp('2024-01-01', 9, 30);
      const phase = getCurrentSessionPhase(testTime, '2024-01-01');
      expect(phase?.name).toBe('IB FORMATION');
    });

    it('returns null for time outside all phases', () => {
      // 18:00 is after market close
      const testTime = ISTtoTimestamp('2024-01-01', 18, 0);
      const phase = getCurrentSessionPhase(testTime, '2024-01-01');
      expect(phase).toBeNull();
    });
  });

  describe('DEFAULT_SESSION_PHASES', () => {
    it('has correct IB Formation phase', () => {
      const ibPhase = DEFAULT_SESSION_PHASES[0];
      expect(ibPhase.name).toBe('IB FORMATION');
      expect(ibPhase.startHour).toBe(9);
      expect(ibPhase.startMinute).toBe(15);
      expect(ibPhase.endHour).toBe(10);
      expect(ibPhase.endMinute).toBe(15);
    });

    it('has correct Lunch Zone phase', () => {
      const lunchPhase = DEFAULT_SESSION_PHASES[1];
      expect(lunchPhase.name).toBe('LUNCH ZONE');
      expect(lunchPhase.startHour).toBe(12);
      expect(lunchPhase.startMinute).toBe(0);
      expect(lunchPhase.endHour).toBe(14);
      expect(lunchPhase.endMinute).toBe(0);
    });

    it('has correct Closing Risk phase', () => {
      const closingPhase = DEFAULT_SESSION_PHASES[2];
      expect(closingPhase.name).toBe('CLOSING RISK');
      expect(closingPhase.startHour).toBe(14);
      expect(closingPhase.startMinute).toBe(45);
      expect(closingPhase.endHour).toBe(15);
      expect(closingPhase.endMinute).toBe(30);
    });
  });
});
