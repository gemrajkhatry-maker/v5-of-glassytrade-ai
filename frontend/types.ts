
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

export interface RiskState {
  halted: boolean;
  haltReason: string;
  consecutiveLosses: number;
  dailyPnl: number;
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
  metadata?: {
    factorBreakdown: FactorBreakdown;
    generation: number;
  };
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
  aiAnalysis: AIAnalysis | null; // This refers to the numeric prediction model
  genAIAnalysis: GenAIAnalysis | null; // This refers to the Fabio Logic LLM
  amtAnalysis: AMTAnalysis | null;
  riskState: RiskState | null;
  llmHistory: LLMHistoryEntry[];
  predictions: OHLCData[];
  lastUpdate: number;
}

export type ChartMode = 'STANDARD' | 'FOOTPRINT';

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
  dataSource: 'BINANCE' | 'SIMULATION';
  bullColor: string;
  bearColor: string;
  glassOpacity: number;
  roughness: number;
  transmission: number;
  showGrid: boolean;
  autoRotate: boolean;
  showPredictions: boolean;
  showVolumeProfile: boolean;
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
  marketState: 'BALANCED' | 'IMBALANCED';
  poc: number;
  valueAreaHigh: number;
  valueAreaLow: number;
  lvns: number[];
  hvns: number[]; // High Volume Nodes
  aggression: number;
  signal: TradeSignal | null;
  setup: 'TREND_MODEL' | 'MEAN_REVERSION' | null;
  profile: VolumeProfileLevel[];
  aggressivePrints: AggressivePrint[]; // "Volume Bubbles"
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
}

export interface FootprintCandle {
  time: string;
  levels: FootprintLevel[];
  pocPrice: number;
  totalDelta: number;
  stepPrice: number; // Size of each price level (bucket)
}
