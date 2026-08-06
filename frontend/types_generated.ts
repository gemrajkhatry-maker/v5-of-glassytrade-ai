// Auto-generated from Python Pydantic DTOs
// Generated: 2026-05-01T18:38:57.721486
// Source: backend/app/infrastructure/serialization/schemas.py
// DO NOT EDIT MANUALLY - regenerate via: python scripts/generate_types.py

/**
 * Shared types generated from Python Pydantic DTOs.
 * Import these for data that comes directly from the backend.
 */

export interface VolumeProfileLevel {
  price: number;
  volume?: number;
  buyVolume?: number;
  sellVolume?: number;
}

export interface AggressivePrint {
  price: number;
  time: string;
  volume: number;
  delta: number;
  side: 'BUY' | 'SELL';
}

export interface OIWall {
  price: number;
  callOi?: number;
  putOi?: number;
  totalOi?: number;
  optionType?: string;
}

export interface SqueezeState {
  isSqueezeOn?: boolean;
  squeezeDirection?: string;
  bollingerBandWidth?: number;
  keltnerBandWidth?: number;
  breakoutProbability?: number;
}

export interface TradeSignal {
  type: 'BUY' | 'SELL';
  price: number;
  reason: string;
  stopLoss?: number;
  takeProfit?: number;
  timestamp?: string;
  setup?: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Backend DTO for AMT analysis.
 * This represents the pure backend data structure.
 * For frontend-specific extensions, use AMTAnalysis from types.ts.
 */
export interface AMTAnalysisDTO {
  marketState?: string;
  poc?: number;
  valueAreaHigh?: number;
  valueAreaLow?: number;
  lvns?: number[];
  hvns?: number[];
  aggression?: number;
  signal?: TradeSignal;
  setup?: string;
  profile?: VolumeProfileLevel[];
  aggressivePrints?: AggressivePrint[];
  cvdSlope?: number;
  cvdDivergence?: string;
  profileShape?: string;
  profileType?: string;
  sessionVwap?: number;
  vwapUpper1?: number;
  vwapLower1?: number;
  vwapUpper2?: number;
  vwapLower2?: number;
  vwapDeviationSigmas?: number | null;
  balanceRatio?: number;
  legProfile?: VolumeProfileLevel[];
  legLvns?: number[];
  legPoc?: number;
  legVah?: number;
  legVal?: number;
  legRegime?: string;
  swingDelta?: number;
  hasDisplacement?: boolean;
  marketStructure?: string;
  structureConfidence?: number;
  ibHigh?: number;
  ibLow?: number;
  ibComplete?: boolean;
  priorPoc?: number;
  priorVah?: number;
  priorVal?: number;
  gapType?: string;
  openingBias?: string;
  acceptanceAbove?: boolean;
  acceptanceBelow?: boolean;
  rejectionAtHigh?: boolean;
  rejectionAtLow?: boolean;
  liquiditySweep?: string;
  absorptionSide?: string;
  absorptionRangeRatio?: number;
  absorptionVolRatio?: number;
  priceVelocity?: number;
  ofi?: number;
  breakDirection?: string;
  breakType?: string;
  breakLevel?: number;
  pocSignal?: string;
  pocVsPrice?: string;
  lvnPlay?: Record<string, unknown>;
  isSecondDrive?: boolean;
  bubbleRetests?: AggressivePrint[];
  npocAbove?: number;
  npocBelow?: number;
  driveNumber?: number;
  driveEntryValid?: boolean;
  dailyVah?: number;
  dailyVal?: number;
  dailyPoc?: number;
  hourlyPoc?: number;
  deltaNormalizedOption?: number;
  isExtremeDeviation?: boolean;
  underlyingPrice?: number;
  optionType?: string;
  vahProbeState?: string;
  exhaustionWarning?: string;
  swingDeltaTimestamp?: string;
  swingDeltaPrice?: number;
  volumeAboveVahPct?: number;
  pcr?: number;
  oiWalls?: OIWall[];
  squeezeState?: SqueezeState;
  sessionFavorStrategy?: string;
}