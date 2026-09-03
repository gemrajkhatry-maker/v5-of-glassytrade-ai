/**
 * GlassyTrade AI - Frontend Configuration
 *
 * User-facing configuration for chart themes, thresholds, and display preferences.
 * These values can be overridden via environment variables or localStorage.
 *
 * Architecture: mirrors the backend's YAML-based approach but at the frontend level.
 * Default values here can be customized per-user, per-environment, or via admin settings.
 */

// =============================================================================
// Time Constants
// =============================================================================

/** IST offset from UTC in seconds (UTC+5:30) */
export const IST_OFFSET_SECONDS = 19800;

/** One day in milliseconds */
export const ONE_DAY_MS = 86_400_000;

// =============================================================================
// Chart Configuration Defaults
// =============================================================================

/** Default chart appearance and behavior */
export const DEFAULT_CHART_CONFIG = {
  // Symbol & data
  symbol: '',
  interval: '5m' as const,
  dataSource: 'DHAN' as const,

  // Theme colors (glassmorphism dark theme)
  bullColor: '#00c896',   // Institutional green (85% saturation)
  bearColor: '#ff4757',   // Institutional red (85% saturation)

  // Glassmorphism effects
  glassOpacity: 1.0,
  roughness: 0.1,         // Smooth glass
  transmission: 0.95,     // High transmission

  // Display toggles
  showGrid: true,
  autoRotate: false,
  showPredictions: true,
  showVolumeProfile: true,
  vpMode: 'combined' as const,
  showHalfTrend: true,
  trend: 'volatile' as const,
};

// =============================================================================
// Equity Panel Configuration
// =============================================================================

/** Equity panel display range (daily P&L circuit breaker and target) */
export const EQUITY_PANEL = {
  /** Circuit breaker level (loss threshold that triggers panel warning) */
  circuitBreaker: -10_000,

  /** Daily P&L target for the progress bar */
  dailyTarget: 20_000,

  /** Progress bar color thresholds */
  progress: {
    /** Below this % of target: red */
    warnThreshold: 0.25,
    /** Below this %: yellow */
    cautionThreshold: 0.5,
  },
};

// =============================================================================
// Diagnostics Panel Configuration
// =============================================================================

/** Thresholds and display settings for the diagnostics panel */
export const DIAGNOSTICS_CONFIG = {
  /** VWAP cross threshold as percentage from VWAP */
  vwapCrossThreshold: 0.3,  // 0.3% from VWAP

  /** Distance threshold for value area proximity checks */
  distThreshold: 0.25,

  /** Structure confidence display thresholds */
  structureConfidence: {
    /** Green threshold */
    good: 70,
    /** Yellow "wait for rejection" range start */
    cautionStart: 70,
    /** Yellow "wait for rejection" range end */
    cautionEnd: 80,
    /** Red threshold */
    poor: 40,
  },

  /** Number of rules in the diagnostics checklist */
  ruleCount: 3,
};

// =============================================================================
// Three-A Scoring Configuration
// =============================================================================

/** Thresholds for the Three-A (Valentini AMT) scoring system */
export const THREE_A_CONFIG = {
  /** Minimum aggression score to count as "Action" */
  aggressionMin: 2.0,

  /** Minimum CVD slope to count as "Action" */
  cvdSlopeMin: 2.0,
};

// =============================================================================
// Profile Context Configuration
// =============================================================================

/** Thresholds for POC confluence/divergence detection */
export const PROFILE_CONFIG = {
  /** POC difference ≤ this % → CONFLUENCE */
  confluenceThreshold: 0.001,  // 0.1%

  /** POC difference ≥ this % → DIVERGENCE */
  divergenceThreshold: 0.005,  // 0.5%
};

// =============================================================================
// Order Flow Card Configuration
// =============================================================================

/** Display thresholds and formatting for order flow metrics */
export const ORDER_FLOW_CONFIG = {
  /** CVD formatting thresholds */
  format: {
    millionsThreshold: 1_000_000,
    thousandsThreshold: 1_000,
  },

  /** Spread display color thresholds (in bps) */
  spread: {
    /** ≤ this: green (tight) */
    greenMax: 5,
    /** ≤ this: yellow (moderate) */
    yellowMax: 15,
  },

  /** CVD ratio display thresholds */
  cvdRatio: {
    low: 50,
    high: 70,
  },

  /** Aggression divergence detection thresholds */
  divergence: {
    deltaThreshold: 0.02,
    cvdThreshold: 0.01,
    ofiThreshold: 0.1,
  },
};

// =============================================================================
// Absorption Card Configuration
// =============================================================================

/** Thresholds for absorption and large print detection */
export const ABSORPTION_CONFIG = {
  /** Minimum swing delta magnitude to display (absolute value) */
  swingDeltaThreshold: 100,

  /** Large print display threshold (formatted as K if above this) */
  largePrintKThreshold: 1000,
};

// =============================================================================
// VA Freeze Card Configuration
// =============================================================================

/** Configuration for Value Area freeze detection */
export const VA_FREEZE_CONFIG = {
  /** Minimum number of VA snapshots required to show freeze analysis */
  minSnapshots: 2,
};

// =============================================================================
// Network / Connection Configuration
// =============================================================================

/** Network and connection settings */
export const NETWORK_CONFIG = {
  /** WebSocket reconnection delay (seconds) */
  reconnectDelaySeconds: 5,

  /** Maximum reconnection attempts */
  maxReconnectAttempts: 30,

  /** WebSocket ping interval (seconds) */
  pingIntervalSeconds: 30,

  /** Configuration fetch timeout (milliseconds) */
  configTimeoutMs: 180_000,  // 3 minutes

  /** Maximum pending RAF queue size (backpressure) */
  maxRafQueueSize: 10,
};

// =============================================================================
// Type Exports
// =============================================================================

/** Chart configuration shape */
export interface ChartConfig {
  symbol: string;
  interval: string;
  dataSource: string;
  bullColor: string;
  bearColor: string;
  glassOpacity: number;
  roughness: number;
  transmission: number;
  showGrid: boolean;
  autoRotate: boolean;
  showPredictions: boolean;
  showVolumeProfile: boolean;
  vpMode: string;
  trend: string;
}
