// JSON-safe DTOs mirroring the TradeX backend contracts
// (sdk/services/amt.py snapshot_to_dict + interface/fastapi_app.py).

export interface AMTSnapshot {
  instrument: string;
  timestamp: string | null;
  close: string | null;
  poc: string | null;
  vah: string | null;
  val: string | null;
  vwap: string;
  upper_1: string;
  lower_1: string;
  upper_2: string;
  lower_2: string;
  vwap_std: string;
  delta: string;
  cvd: string;
  cvd_slope: string;
  cvd_divergence: "BULLISH" | "BEARISH" | "NONE";
  absorption_side: "BUY" | "SELL" | "NONE" | null;
  absorption_strength: string;
  absorption_age: number;
  ib_high: string | null;
  ib_low: string | null;
  ib_complete: boolean;
  location: string;
  nearest_level: string | null;
  profile_shape: string;
  lvn_levels: string[];
  hvn_levels: string[];
  phase: string;
  direction: string;
  book_imbalance: string;
  book_polr: string;
  book_swept_bids: number;
  book_swept_asks: number;
  absorption_confirmed: boolean;
  aggression_score: string;
}

export interface AMTScanRow {
  instrument: string;
  phase: string;
  direction: string;
  setup: string;
  score: number;
  absorption_side: string | null;
  absorption_strength: string;
  timestamp: string | null;
}

export interface AMTDecision {
  timestamp: string | null;
  approved: boolean;
  setup: string;
  direction: string | null;
  entry: string | null;
  stop_loss: string | null;
  take_profit: string | null;
  risk_reward: string;
  reason: string;
  failed_gates: string[];
  cushion: string;
  pyramid: boolean;
}

export interface CandleBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Position {
  instrument: string;
  side: string;
  quantity: number;
  avg_price: number;
  unrealized_pnl?: number;
  realized_pnl?: number;
}

export interface Order {
  order_id: string;
  instrument: string;
  side: string;
  quantity: number;
  price?: number | null;
  status?: string;
  tag?: string | null;
}

export interface Account {
  margin_available?: number;
  cash?: number;
  equity?: number;
  [key: string]: unknown;
}
