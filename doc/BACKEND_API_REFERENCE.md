# GlassyTrade AI — Backend API Reference

This document provides a comprehensive list of all backend REST and WebSocket APIs, their purpose, methods, and usage instructions.

---

## 1. System & Health APIs
**Base Path:** `/api`
**Tags:** `health`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | `GET` | Returns overall system health (Database, LLM, Probability Engine). |
| `/v1/metrics` | `GET` | Snapshot of current pipeline metrics. |
| `/system/halt` | `POST` | **Emergency Kill Switch** — immediately stops all trading activity. |
| `/system/resume` | `POST` | Clears the halt and resumes trading. |
| `/system/playbook-guard/reset` | `POST` | Resets playbook rejection counters for one or all symbols. |
| `/system/risk-state` | `GET` | Returns current system-wide risk state (drawdown, equity, etc.). |
| `/system/config` | `GET` | Returns active backend configuration (symbols, mode, LLM status). |
| `/debug/memory` | `GET` | Returns process memory usage and GC stats. |

---

## 2. Market Data APIs
**Base Path:** `/api/market`
**Tags:** `market`

| Endpoint | Method | Parameters | Description |
|----------|--------|------------|-------------|
| `/scan` | `GET` | `limit` (int) | Scans for potential trading candidates. |
| `/history/{symbol}` | `GET` | `symbol` (str), `interval` (str), `limit` (int) | Returns OHLCV history for a specific symbol. |
| `/orderbook/{symbol}` | `GET` | `symbol` (str) | Returns current L2 Order Book (Bids/Asks). |

---

## 3. Trading & Portfolio APIs
**Base Path:** `/api/trading`
**Tags:** `trading`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio/create` | `POST` | Creates a new in-memory portfolio for the session. |
| `/stats` | `POST` | Computes performance statistics (Win Rate, Profit Factor) from a list of trades. |
| `/positions/events` | `GET` | Queries append-only lifecycle events (OPENED, CLOSED, PARTIAL_EXIT). |
| `/positions/{id}/lifecycle`| `GET` | Returns a serialized "Replay" view of a specific position's history. |

---

## 4. AI & Analysis APIs
**Base Path:** `/api/ai`
**Tags:** `ai`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze` | `POST` | Performs low-level market analysis using the fine-tuned LLM. |
| `/command` | `POST` | **Natural Language Processor** — handles chat commands (e.g., "show nifty"). |
| `/history` | `GET` | Returns persisted LLM decisions and signal rejection history. |
| `/journal` | `GET` | Returns AI-generated trade journal entries for a specific date or run. |
| `/journal/summary` | `GET` | Returns daily performance summary (P&L, Winners, Losers). |
| `/journal/promotion` | `GET` | **Promotion Assessor** — evaluates if a paper run is ready for live trading. |

---

## 5. Domain Analysis APIs
**Base Path:** `/api/analysis`
**Tags:** `analysis`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/amt` | `POST` | Runs Auction Market Theory analysis (Volume Profile, VAH/VAL/POC). |
| `/predict` | `POST` | Generates "Ghost Candles" (Quant Engine predictions). |
| `/footprint` | `POST` | Generates Order Flow Footprint data (Bid/Ask delta per level). |

---

## 6. Reinforcement Learning (RL) APIs
**Base Path:** `/api/rl`
**Tags:** `reinforcement-learning`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/train` | `POST` | Starts a background task to train the Valentini AMT RL model. |
| `/status` | `GET` | Returns current training progress (Timesteps, Reward, Sharpe). |
| `/predict` | `POST` | Runs inference using a trained RL model checkpoint. |
| `/models` | `GET` | Lists all saved model checkpoints (`.zip` files). |
| `/load/{name}` | `POST` | Loads a specific model into the active inference slot. |

---

## 7. WebSocket API
**Endpoint:** `/api/trading/ws/gameloop`
**Protocol:** WebSocket (`ws://` or `wss://`)

The main real-time data conduit between the backend and frontend.

### Usage:
1.  **Subscription:** Send `{"subscribe": "SYMBOL"}` to start receiving live state updates.
2.  **Streaming:** The server will stream a "Full State" snapshot followed by "Delta" compressed updates.
3.  **Content:** Includes current Price, Portfolio, AMT Analysis, Footprint, and LLM Decisions.

---

## 8. Development & Monitoring
- **Automatic Docs:** Visit `http://localhost:9090/docs` for the interactive Swagger UI.
- **Redoc:** Visit `http://localhost:9090/redoc` for the human-readable API documentation.
- **Port:** Defaults to `9090` (configured in `.env`).
