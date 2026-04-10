# AMT Live Trading System v2

> Production-grade Fabio Valentini Auction Market Theory trading system for Indian options (NIFTY / BANKNIFTY / CRUDE OIL)

[![Tests](https://img.shields.io/badge/tests-57%2F57%20passing-brightgreen)](#)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](#)
[![License](https://img.shields.io/badge/license-proprietary-red)](#)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        AMT Live System v2                        │
├──────────────────────────────────────────────────────────────────┤
│  Dhan WebSocket → Ticks → Candles → Volume Profile/VWAP/CVD    │
│                                    ↓                              │
│                    Auction State Machine (4 states)              │
│                                    ↓                              │
│                      12-Gate Pipeline (hard + soft)              │
│                                    ↓                              │
│                  Signal → TTL Manager → Execution                │
│                                    ↓                              │
│            Trade Lifecycle → Reconciliation → Journal            │
└──────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
cd appv2
cp .env.example .env    # Fill DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID
./start.sh              # Backend :8001, Frontend :5174
```

## Project Structure

```
appv2/
├── backend/
│   ├── appv2/
│   │   ├── config/              # Settings + AMT constants
│   │   ├── domain/
│   │   │   ├── models/          # OHLC, Tick, Signal, Trade, Option
│   │   │   ├── enums/           # MarketState, SignalType, SessionPhase
│   │   │   ├── ports/           # Abstract interfaces (DIP)
│   │   │   └── services/        # 33 domain services (see below)
│   │   ├── infrastructure/      # Dhan adapters, SQLite, Paper
│   │   ├── application/         # Orchestrators (TradingEngine, Pipeline)
│   │   ├── api/                 # FastAPI routes + WebSocket + middleware
│   │   └── main.py              # Entry point
│   └── tests/                   # 57 unit + integration tests
├── frontend/                    # React 18 + TypeScript + Tailwind
├── IMPLEMENTATION_PLAN.md       # 10-phase task breakdown
├── docker-compose.yml           # Docker support
├── .env.example                 # Environment template
└── start.sh                     # One-command start
```

## AMT Strategy (Fabio Valentini)

### Auction States
| State | Condition | Strategy |
|-------|-----------|----------|
| **NO_TRADE** | Price within ±5 ticks of POC | No signals |
| **BALANCED** | Price inside VAH-VAL, ≥70% candles inside VA | Mean reversion |
| **IMBALANCED** | Price outside VA + displacement + acceptance | Trend following |
| **PROBING** | Price outside VA without confirmation | Wait |

### Value Area (CME Method)
- POC = bin with max volume (VWAP tie-break for ties)
- VA = 70% of volume via two-row pairs method
- LVN = <15% mean volume (rejection zone)
- HVN = >200% mean volume (acceptance zone)

### Aggression Score (6 Signals)
| Signal | Weight | Description |
|--------|--------|-------------|
| Footprint | 25% | Aggressive prints + strong delta |
| CVD | 25% | Cumulative delta slope alignment |
| Big Trade | 15% | Volume > 2× average |
| Absorption | 15% | Large range + volume + small body |
| OFI | 10% | Order flow imbalance significant |
| Confluence | 5% | LVN near key level |
| Bubble | 5% | Volume bubble at key level |

### Entry Gates (12 Gates)
**Hard Gates** (any fail = reject): Session warm-up, Data quality, Risk halt, NO_TRADE state, PROBING without aggression, Key level proximity, Drive validation, Signal age, CVD hard gate

**Soft Gates** (need ≥3/4): Price at entry zone, Aggression score, Cushion to opposing level, R:R ≥ 1.5

### Options Adaptation
- **Strike Selection**: ATM (max gamma) or ITM (delta 0.60-0.75)
- **Expiry**: Weekly Thursday, gamma-trap avoidance after 14:30
- **Liquidity**: Min OI (NIFTY: 50K, BANKNIFTY: 10K, CRUDEOIL: 5K)
- **Theta**: Cost < 20% of expected profit
- **AMT on Underlying**: Always runs on futures, not option premium

## 33 Domain Services

| # | Service | Purpose |
|---|---------|---------|
| 1 | CandleAggregator | Tick→OHLCV, multi-timeframe, UTC-safe |
| 2 | IncrementalVolumeProfile | CME buckets, no rebuild |
| 3 | VWAPCalculator | Session VWAP + σ bands |
| 4 | CVDTracker | Cumulative delta, 40-bar slope |
| 5 | AggressionScorer | 6-signal composite scoring |
| 6 | DriveTracker | D1/D2/D3+ with exhaustion |
| 7 | MarketStateEngine | 4-state Fabio classification |
| 8 | ProfileClassifier | D/P/b/B shape, POC migration |
| 9 | AcceptanceRejection | 2-bar acceptance, 50% wick rejection |
| 10 | BreakDetector | Initiative vs responsive IB breaks |
| 11 | DisplacementDetector | Range > 1.5×ATR + vol > 1.5×avg |
| 12 | LVN/HVNDetector | Persistence-filtered nodes |
| 13 | OrderFlowDetectors | Big trades, absorption, OFI, bubbles |
| 14 | InitialBalance | 60-min IB with sticky break |
| 15 | SessionContext | NSE 5-phase + MCX 4-phase |
| 16 | AuctionStateMachine | Hysteresis, valid transitions |
| 17 | GatePipeline | 9 hard + 4 soft gates (quorum ≥3) |
| 18 | SignalGenerator | SL/TP from aggressive prints |
| 19 | ExitEngine | SL/TP/Trail/Time/Session exit |
| 20 | MTFAnalyzer | Daily + hourly + 5-min alignment |
| 21 | PositionSizer | Risk-based lot calculation |
| 22 | DailyLossTracker | P&L tracking, auto-halt |
| 23 | CircuitBreaker | Consecutive loss cooldown |
| 24 | BlackScholes | Delta/Gamma/Theta/Vega + IV |
| 25 | StrikeSelector | ATM/ITM with liquidity filter |
| 26 | ExpiryManager | Weekly expiry, gamma-trap |
| 27 | LiquidityFilter | OI/volume/spread/LTP filters |
| 28 | IVRankTracker | IV rank/percentile, IV crush |
| 29 | ThetaDecayAnalyzer | Theta cost < 20% expected profit |
| 30 | UnderlyingRouter | Options → futures routing |
| 31 | PositionReconciliation | Internal vs broker positions (30s) |
| 32 | SignalTTLManager | TTL, retry, deduplication |
| 33 | PostTradeAnalytics | Win rate, expectancy, drawdown |

## Tests (57/57 Passing)

```
test_blackscholes.py          6 tests
test_candle_aggregator.py     3 tests
test_e2e_integration.py       9 tests  ← End-to-end pipeline
test_gate_pipeline.py         5 tests
test_integration_replay.py    5 tests
test_market_state.py          5 tests
test_new_services.py          8 tests
test_production_services.py   8 tests
test_volume_profile.py        4 tests
test_vwap.py                  4 tests
```

## Safety Features

| Feature | Description |
|---------|-------------|
| Paper Trading Default | `LIVE_TRADING=false` by default |
| Real-Money Guard | Must explicitly enable in .env |
| Signal TTL | 10-minute expiration |
| Daily Loss Limit | Auto-halt at configurable % |
| Circuit Breaker | Per-symbol cooldown after losses |
| Position Reconciliation | 30-second broker vs internal check |
| Data Quality Gate | Minimum 5 candles before trading |
| Session Phase Lock | No entries during opening noise (09:15-09:30) |
| Gamma-Trap Avoidance | No entries after 14:30 on expiry day |

## Configuration

All settings via `.env` (see `.env.example`). Key parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CAPITAL` | 5,000,000 | Trading capital in INR |
| `RISK_PER_TRADE_PCT` | 1.0 | Max risk per trade (%) |
| `MAX_DAILY_LOSS_PCT` | 3.0 | Max daily loss (%) |
| `LIVE_TRADING` | false | Real money mode |
| `EXCHANGE` | NSE | NSE or MCX |
| `SYMBOLS` | NIFTY,BANKNIFTY | Comma-separated symbols |

## Reused Components

The system reuses the existing `brokers/` library for:
- Dhan WebSocket feed (rc=2/4/5/6/8 packet decoding)
- Dhan order execution (market, limit, SL, bracket)
- Option chain fetching
- Historical data fetching
- Symbol mapping

No code from the existing `backend/` or `frontend/` is modified or imported.
