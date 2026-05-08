/**
 * SessionPhaseMarkers - Calculate session phase background zones
 * 
 * Calculates positioning for session phase shaded areas:
 * - IB Formation Period (9:15-10:15) - Amber tint
 * - Lunch Dead Zone (12:00-14:00) - Grey tint
 * - Closing Risk Zone (14:45-15:30) - Red tint
 * 
 * Benefits:
 * - 100% testable (pure functions)
 * - Separates time calculations from canvas rendering
 * - Easy to validate session boundaries
 * - Reusable across different chart modes
 */

export interface SessionPhase {
  name: string;
  startHour: number;
  startMinute: number;
  endHour: number;
  endMinute: number;
  color: string;
  labelOffset: number;
}

export interface SessionZoneConfig {
  startX: number;
  endX: number;
  y: number;
  height: number;
  color: string;
  label: string;
  labelX: number;
}

export const DEFAULT_SESSION_PHASES: SessionPhase[] = [
  {
    name: 'IB FORMATION',
    startHour: 9,
    startMinute: 15,
    endHour: 10,
    endMinute: 15,
    color: 'rgba(251,191,36,0.03)', // Amber
    labelOffset: 28,
  },
  {
    name: 'LUNCH ZONE',
    startHour: 12,
    startMinute: 0,
    endHour: 14,
    endMinute: 0,
    color: 'rgba(100,100,100,0.04)', // Grey
    labelOffset: 16,
  },
  {
    name: 'CLOSING RISK',
    startHour: 14,
    startMinute: 45,
    endHour: 15,
    endMinute: 30,
    color: 'rgba(239,68,68,0.04)', // Red
    labelOffset: 40,
  },
];

/**
 * IST timezone offset in seconds (UTC+5:30)
 */
const IST_OFFSET = 19800;

/**
 * Convert IST hour/minute to Unix timestamp for a given date
 * 
 * @param dateStr - Date string (e.g., '2024-01-01')
 * @param hour - Hour in IST
 * @param minute - Minute in IST
 * @returns Unix timestamp
 */
export function ISTtoTimestamp(dateStr: string, hour: number, minute: number): number {
  // Create date in UTC, then add IST offset
  const utcDate = new Date(`${dateStr}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00Z`);
  return utcDate.getTime() / 1000 - IST_OFFSET;
}

/**
 * Find X coordinate for a given time
 * 
 * @param timestamp - Target timestamp
 * @param dataTimeRange - Array of [timestamp, x] pairs
 * @returns X coordinate or null if not found
 */
export function findTimeXCoordinate(
  timestamp: number,
  dataTimeRange: Array<{ time: number; x: number }>
): number | null {
  if (!dataTimeRange || dataTimeRange.length === 0) {
    return null;
  }

  // Find the two points that bracket the timestamp
  for (let i = 1; i < dataTimeRange.length; i++) {
    const prev = dataTimeRange[i - 1];
    const curr = dataTimeRange[i];

    if (timestamp >= prev.time && timestamp <= curr.time) {
      // Linear interpolation
      const ratio = (timestamp - prev.time) / (curr.time - prev.time);
      return prev.x + ratio * (curr.x - prev.x);
    }
  }

  return null;
}

/**
 * Calculate session zone configuration
 * 
 * @param phase - Session phase definition
 * @param dateStr - Trading date
 * @param dataTimeRange - Chart time range mapping
 * @param canvasHeight - Canvas height
 * @returns Session zone configuration or null
 */
export function calculateSessionZone(
  phase: SessionPhase,
  dateStr: string,
  dataTimeRange: Array<{ time: number; x: number }>,
  canvasHeight: number
): SessionZoneConfig | null {
  const startTime = ISTtoTimestamp(dateStr, phase.startHour, phase.startMinute);
  const endTime = ISTtoTimestamp(dateStr, phase.endHour, phase.endMinute);

  const startX = findTimeXCoordinate(startTime, dataTimeRange);
  const endX = findTimeXCoordinate(endTime, dataTimeRange);

  if (startX === null || endX === null) {
    return null;
  }

  return {
    startX,
    endX,
    y: 0,
    height: canvasHeight,
    color: phase.color,
    label: phase.name,
    labelX: startX + (endX - startX) / 2,
  };
}

/**
 * Calculate all session phase zones
 * 
 * @param phases - Session phase definitions
 * @param dateStr - Trading date
 * @param dataTimeRange - Chart time range mapping
 * @param canvasHeight - Canvas height
 * @returns Array of session zone configurations
 */
export function calculateAllSessionZones(
  phases: SessionPhase[],
  dateStr: string,
  dataTimeRange: Array<{ time: number; x: number }>,
  canvasHeight: number
): SessionZoneConfig[] {
  const zones: SessionZoneConfig[] = [];

  phases.forEach(phase => {
    const zone = calculateSessionZone(phase, dateStr, dataTimeRange, canvasHeight);
    if (zone !== null) {
      zones.push(zone);
    }
  });

  return zones;
}

/**
 * Validate session phase definitions
 * 
 * @param phases - Session phase definitions
 * @returns Array of validation errors (empty if valid)
 */
export function validateSessionPhases(phases: SessionPhase[]): string[] {
  const errors: string[] = [];

  phases.forEach((phase, index) => {
    if (!phase.name) {
      errors.push(`Phase ${index}: Missing name`);
    }
    if (phase.startHour < 0 || phase.startHour > 23) {
      errors.push(`Phase ${index}: Invalid start hour (${phase.startHour})`);
    }
    if (phase.startMinute < 0 || phase.startMinute > 59) {
      errors.push(`Phase ${index}: Invalid start minute (${phase.startMinute})`);
    }
    if (phase.endHour < 0 || phase.endHour > 23) {
      errors.push(`Phase ${index}: Invalid end hour (${phase.endHour})`);
    }
    if (phase.endMinute < 0 || phase.endMinute > 59) {
      errors.push(`Phase ${index}: Invalid end minute (${phase.endMinute})`);
    }

    // Check if end time is after start time
    const startMinutes = phase.startHour * 60 + phase.startMinute;
    const endMinutes = phase.endHour * 60 + phase.endMinute;
    if (endMinutes <= startMinutes) {
      errors.push(`Phase ${index}: End time must be after start time`);
    }
  });

  return errors;
}

/**
 * Check if a given time falls within a session phase
 * 
 * @param timestamp - Timestamp to check
 * @param phase - Session phase
 * @param dateStr - Trading date
 * @returns true if time is within phase
 */
export function isTimeInSessionPhase(
  timestamp: number,
  phase: SessionPhase,
  dateStr: string
): boolean {
  const startTime = ISTtoTimestamp(dateStr, phase.startHour, phase.startMinute);
  const endTime = ISTtoTimestamp(dateStr, phase.endHour, phase.endMinute);

  return timestamp >= startTime && timestamp <= endTime;
}

/**
 * Get current session phase for a given time
 * 
 * @param timestamp - Current timestamp
 * @param dateStr - Trading date
 * @param phases - Session phase definitions
 * @returns Current session phase or null
 */
export function getCurrentSessionPhase(
  timestamp: number,
  dateStr: string,
  phases: SessionPhase[] = DEFAULT_SESSION_PHASES
): SessionPhase | null {
  for (const phase of phases) {
    if (isTimeInSessionPhase(timestamp, phase, dateStr)) {
      return phase;
    }
  }
  return null;
}
