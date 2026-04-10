export interface AMTState {
  symbol: string
  poc: number
  vah: number
  val: number
  vwap: number
  marketState: string
  sessionPhase: string
  aggressionScore: number
  cvd: number
  cvdSlope: number
}

export interface Signal {
  symbol: string
  direction: 'LONG' | 'SHORT'
  entryPrice: number
  stopLoss: number
  takeProfit: number
  confidence: number
  marketState: string
  sessionPhase: string
  timestamp: number
  ageSeconds: number
  isExpired: boolean
  riskRewardRatio: number
  optionType?: string
  expiryDate?: string
}

export interface Position {
  tradeId: string
  symbol: string
  side: 'BUY' | 'SELL'
  entryPrice: number
  quantity: number
  lots: number
  stopLoss: number
  takeProfit: number
  trailPrice: number
  status: string
  entryTime: number
  realizedPnl: number
  netPnl: number
  durationMinutes: number
}

export interface RiskState {
  dailyPnl: number
  maxDrawdown: number
  consecutiveLosses: number
  circuitBreakerActive: boolean
  availableBalance: number
  totalExposure: number
}

export interface SystemHealth {
  status: string
  version: string
  uptimeSeconds: number
  timestamp: string
  liveTrading: boolean
  symbolsConnected: number
  dataLatencyMs: number
}
