
export interface OHLCData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap: number;
  takerBuyVolume: number;
  delta: number;
}

export interface OrderBook {
  bids: { price: number; quantity: number }[];
  asks: { price: number; quantity: number }[];
}

export interface ModelWeights {
  trend: number;
  momentum: number;
  delta: number;
  orderBook: number;
  volatility: number;
}

export interface FactorBreakdown extends ModelWeights { }

export interface AIAnalysis {
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  confidence: number;
  longTermTrend: 'UP' | 'DOWN' | 'SIDEWAYS';
  volatilityScore: number;
  quantScore: number;
  projectedPrice: number;
  reasoning: string[];
  factorBreakdown: FactorBreakdown;
}

export interface GenAIAnalysis {
  direction: 'LONG' | 'SHORT' | 'FLAT';
  rationale: string;
  confidence: 'High' | 'Medium' | 'Low';
  inputPrompt?: string;
  rawOutput?: string;
  marketState?: string;
  aggression?: string;
}

export interface AgentDecision {
  direction: 'LONG' | 'SHORT' | 'FLAT';
  probability: number;
  regime: string;
  timing: string;
  sizeFraction: number;
  latencyUs: number;
  rationale: string;
}

export interface RiskState {
  halted: boolean;
  haltReason: string;
  consecutiveLosses: number;
  dailyPnl: number;
  driftAlert?: boolean;
  driftMessage?: string;
}

export interface RuntimeSafetyState {
  brokerBound: boolean;
  feedStale: boolean;
  unsafeToTrade: boolean;
  feed?: Record<string, unknown>;
  execution?: Record<string, unknown>;
  stateDigest?: string;
  readiness?: Record<string, unknown>;
}

export interface LLMHistoryEntry {
  timestamp: number;
  direction: 'LONG' | 'SHORT' | 'FLAT';
  confidence: string;
  rationale: string;
  inputPrompt?: string;
  rawOutput?: string;
}

export interface TradePosition {
  id: string;
  symbol: string;
  side: 'LONG' | 'SHORT';
  source: 'AMT' | 'PREDICTION' | 'LLM';
  entryPrice: number;
  size: number;
  stopLoss: number;
  takeProfit: number;
  pnl: number;
  entryTime: string;
  status: 'OPEN' | 'CLOSED';
  exitPrice?: number;
  exitTime?: string;
  closeReason?: string;
  partialRealizedPnl?: number;
  originalSize?: number;
}

export interface Portfolio {
  balance: number;
  equity: number;
  leverage: number;
  positions: TradePosition[];
  closedTrades: TradePosition[];
}

/**
 * Encapsulates the complete state of a single trading instrument.
 */
export interface InstrumentState {
  symbol: string;
  data: OHLCData[];
  orderBook: OrderBook | null;
  portfolio: Portfolio;
  aiAnalysis: AIAnalysis | null;
  genAIAnalysis: GenAIAnalysis | null;
  amtAnalysis: AMTAnalysis | null;
  riskState: RiskState | null;
  agentDecision: AgentDecision | null;
  llmHistory: LLMHistoryEntry[];
  overseerAction: string;
  overseerReason: string;
  depth20Active: boolean;
  stale?: boolean;
  runtimeSafety?: RuntimeSafetyState;
  ltp?: number;
  oi?: number;
  lastUpdate: number;
}

export type ChartMode = 'STANDARD';

export interface AppState {
  config: ChartConfig; // Global visual config
  instruments: Record<string, InstrumentState>;
  activeSymbol: string;
  isScanning: boolean;
  chartMode: ChartMode;
}

export interface ChartConfig {
  symbol: string; // Used for display/API context
  interval: string;
  dataSource: 'DHAN' | 'SERVER';
  bullColor: string;
  bearColor: string;
  glassOpacity: number;
  roughness: number;
  transmission: number;
  showGrid: boolean;
  autoRotate: boolean;
  showVolumeProfile: boolean;
  vpMode: 'session' | 'leg' | 'combined' | 'off';
  trend: 'bullish' | 'bearish' | 'sideways' | 'volatile';
}

export interface AggressivePrint {
  price: number;
  time: string;
  side: 'BUY' | 'SELL';
  volume: number;
  delta: number;
}

export interface AMTAnalysis {
  marketState: string;
  poc: number;
  valueAreaHigh: number;
  valueAreaLow: number;
  lvns: number[];
  hvns: number[]; // High Volume Nodes
  aggression: number;
  setup: 'TREND_MODEL' | 'MEAN_REVERSION' | null;
  profile: VolumeProfileLevel[];
  aggressivePrints: AggressivePrint[]; // "Volume Bubbles"
  // Displacement leg profile
  legProfile: VolumeProfileLevel[];
  legLvns: number[];
  legPoc: number;
  legVah: number;
  legVal: number;
  hasDisplacement: boolean;
  // Verification metrics
  profileShape?: string;
  profileType?: string;  // "Session", "Combined", or "Leg"
  balanceRatio?: number;
  ofi?: number;
  cvdSlope?: number;
  cvdDivergence?: string;
  sessionVwap?: number;
  // VWAP bands
  vwapUpper1?: number;
  vwapLower1?: number;
  vwapUpper2?: number;
  vwapLower2?: number;
  vwapDeviationSigmas?: number | null;
  deltaNormalizedOption?: number;
  // Market structure (5-state classifier)
  marketStructure?: string;
  structureConfidence?: number;
  // Initial Balance
  ibHigh?: number;
  ibLow?: number;
  ibComplete?: boolean;
  // Prior day levels
  priorPoc?: number;
  priorVah?: number;
  priorVal?: number;
  gapType?: string;
  openingBias?: string;
  // Acceptance / Rejection
  acceptanceAbove?: boolean;
  acceptanceBelow?: boolean;
  rejectionAtHigh?: boolean;
  rejectionAtLow?: boolean;
  priceVelocity?: number;
  // Break detection
  breakDirection?: string;
  breakType?: string;
  breakLevel?: number;
  // POC migration + LVN play
  pocSignal?: string;
  pocVsPrice?: string;
  lvnPlay?: {
    lvn_price: number;
    direction: string;
    target: number;
    velocity_ratio: number;
    has_rejection: boolean;
    has_delta_flip: boolean;
  } | null;
  llmThinking?: string;
  // Fabio playbook: Second drive detection (reclaim leg confirmation)
  isSecondDrive?: boolean;
  // Multi-timeframe levels (used by location bar)
  dailyVal?: number;
  dailyVah?: number;
  dailyPoc?: number;
  hourlyPoc?: number;
  // Absorption detection (Items 3.16-3.17)
  absorptionSide?: string;
  absorptionRangeRatio?: number;
  absorptionVolRatio?: number;
  swingDelta?: number;
}

/**
 * VolumeProfileLevel for Auction Market Theory analysis
 */
export interface VolumeProfileLevel {
  price: number;
  volume: number;
  buyVolume: number;
  sellVolume: number;
}


