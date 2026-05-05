
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
  quantProbability?: number;
  quantDirection?: string;
}

export interface AgentDecision {
  direction: 'LONG' | 'SHORT' | 'FLAT';
  probability: number;
  regime: string;
  timing: string;
  sizeFraction: number;
  slAdjust: number;
  tpAdjust: number;
  latencyUs: number;
  rationale: string;
  playbook?: string;
  featureDrivers?: string[];
  stopLoss?: number;
  takeProfit?: number;
}

export interface RiskState {
  halted: boolean;
  haltReason: string;
  consecutiveLosses: number;
  dailyPnl: number;
  driftAlert?: boolean;
  driftMessage?: string;
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
  metadata?: {
    factorBreakdown: FactorBreakdown;
    generation: number;
  };

  // Lifecycle fields (from consolidated Position entity)
  cushionState?: 'OPEN' | 'CUSHIONED' | 'TRAILING' | 'CLOSED';
  atrTrailActive?: boolean;
  peakProfit?: number;
  mae?: number;
  mfe?: number;
  partialTaken?: boolean;
  runnerActive?: boolean;
  breakEvenSet?: boolean;
  tickCount?: number;
}

export interface Portfolio {
  balance: number;
  equity: number;
  leverage: number;
  positions: TradePosition[];
  closedTrades: TradePosition[];
  history: { time: string; pnl: number }[];
}

/**
 * Encapsulates the complete state of a single trading instrument.
 */
export interface InstrumentState {
  symbol: string;
  data: OHLCData[];
  orderBook: OrderBook | null;
  portfolio: Portfolio;
  modelWeights: ModelWeights;
  generation: number;
  aiAnalysis: AIAnalysis | null;
  genAIAnalysis: GenAIAnalysis | null;
  amtAnalysis: AMTAnalysis | null;
  riskState: RiskState | null;
  agentDecision: AgentDecision | null;
  llmHistory: LLMHistoryEntry[];
  predictions: OHLCData[];
  overseerAction: string;
  overseerReason: string;
  stats: StrategyStats | null;
  depth20Active: boolean;
  aggressionBlocked?: boolean;
  gateScore?: {
    passed: number;
    total: number;
  };
  stale?: boolean;
  ltp?: number;
  oi?: number;
  rangeBars?: RangeBarData;
  lastUpdate: number;
}

export type ChartMode = 'STANDARD' | 'FOOTPRINT' | 'RANGE';

// Range Bar types (price-movement-based bars)
export interface RangeBar {
  time: number;  // synthetic timestamp for chart rendering
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  buyVolume: number;
  sellVolume: number;
  delta: number;
  tickCount: number;
}

export interface RangeBarVPLevel {
  price: number;
  volume: number;
  buyVolume: number;
  sellVolume: number;
}

export interface RangeBarVP {
  poc: number;
  vah: number;
  val: number;
  levels: RangeBarVPLevel[];
}

export interface TripleAPattern {
  detected: boolean;
  phase: string;
  direction: string;
  absorptionBarIndex: number;
  aggressionBarIndex: number;
  pocAtDetection: number;
  vahAtDetection: number;
  valAtDetection: number;
}

export interface RangeBarData {
  bars: RangeBar[];
  volumeProfile: RangeBarVP;
  sessionProfile?: RangeBarVP;
  legProfile?: RangeBarVP;
  vwap: number;
  cumulativeDelta: number;
  tripleA: TripleAPattern;
  rangeSize: number;
}

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
  showPredictions: boolean;
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
  llmJson?: string;
  tickSize?: number;
  // Decision card fields (from backend agent)
  direction?: 'LONG' | 'SHORT' | 'FLAT';
  pLong?: number;
  pShort?: number;
  agentRegime?: string;
  agentTiming?: string;
  agentKelly?: number;
  agentRationale?: string;
  // Fabio playbook: Second drive detection (reclaim leg confirmation)
  isSecondDrive?: boolean;
  // Session identity and freshness (Phase 1, Task 1.6)
  sessionId?: string;
  computedAt?: string;
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
  // Fix 1: Option type for direction labeling
  optionType?: string;
  // Fix 4: AMT time window for timing transparency
  amtTimeWindow?: {
    window: string;
    label: string;
    rule: string;
    allowEntries: boolean;
  };
  // Fix 6: AMT structure label
  amtStructureLabel?: string;
  // Fix 7: Kelly breakdown
  kellyBreakdown?: {
    fullKelly: number;
    appliedKelly: number;
    fraction: string;
    capReason: string;
  };
  // Fix 5: CVD divergence playbook
  cvdDivPlaybook?: string;
}

export interface TradeSignal {
  type: 'BUY' | 'SELL';
  price: number;
  reason: string;
  stopLoss: number;
  takeProfit: number;
  timestamp: string;
  setup: 'TREND_MODEL' | 'MEAN_REVERSION' | 'PREDICTION_ENTRY';
  source: 'AMT' | 'PREDICTION' | 'LLM';
  metadata?: any;
}

export interface StrategyStats {
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  netProfit: number;
  avgProfit: number;
  largestWin: number;
  largestLoss: number;
}

/**
 * MessageRole enum for type-safe chat history management
 */
export enum MessageRole {
  USER = 'user',
  ASSISTANT = 'assistant',
  SYSTEM = 'system'
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
}

export interface AICommandResponse {
  message: string;
  configUpdates?: Partial<ChartConfig>;
  action?: 'UPDATE_CONFIG' | 'GENERATE_DATA' | 'RESET';
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

/**
 * Footprint Data Structures
 */
export interface FootprintLevel {
  price: number;
  bid: number; // Sell volume
  ask: number; // Buy volume
  delta: number;
  imbalance: boolean; // True if significant imbalance
  stacked: boolean; // Part of stacked imbalance (3+ consecutive)
}

export interface FootprintCandle {
  time: string;
  levels: FootprintLevel[];
  pocPrice: number;
  totalDelta: number;
  stepPrice: number; // Size of each price level (bucket)
}
