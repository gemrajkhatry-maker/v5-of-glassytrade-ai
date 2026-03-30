# GlassyTrade AI — Internal Logic Documentation

## 1. System Architecture Overview
GlassyTrade AI is a high-frequency algorithmic trading system built on Auction Market Theory (AMT) and order flow analysis. It follows a clean architecture with a clear separation between domain logic and infrastructure.

### Major Modules & Responsibilities
- **Backend (Python / FastAPI)**:
  - `app/domain/fabio_ai/services/amt_analyzer.py`: Core logic for Volume Profile, Value Area, and Market State detection.
  - `app/domain/fabio_ai/services/agent_pipeline.py`: Aggregates quant analysis and manages directional probability.
  - `app/domain/fabio_ai/services/entry_gate.py`: Implements FABIO playbook rules (AAA PRE-1, etc.).
  - `app/application/handlers/llm_entry_handler.py`: Orchestrates the flow from market data to AI decision.
  - `app/domain/fabio_ai/services/generative_ai_service.py`: Interface for LLM inference (Gemini/OpenAI).
  - `app/domain/fabio_ai/services/trade_manager.py`: Deterministic trade management (SL/TP/Trail).
  - `app/infrastructure/storage/database.py`: SQLite persistence for ticks, trades, and decisions.
  - `app/infrastructure/adapters/dhan_adapter.py`: Market data source via DhanHQ API.
- **Frontend (React / TypeScript / Tailwind)**:
  - `components/AIAnalysisPanel.tsx`: Primary dashboard for real-time AMT analysis and Rule Checklist.
  - `components/MarketSidebar.tsx`: Multi-symbol scanner and active trade monitor.
  - `components/ai/DecisionHistoryPanel.tsx`: Audit trail for LLM decisions.

### Data Flow
`DhanHQ (Market Data)` → `DhanAdapter (Normalization)` → `MarketDataSubscriber` → `AMTAnalyzer (Indicators/AMT)` → `AgentPipeline (Probability)` → `LLMEntryHandler` → `GenerativeAIService (LLM Narrative)` → `Frontend (WebSocket)` → `UI Rendering`.

## 2. Market Data Pipeline
- **Sources**: Primary data source is **DhanHQ** using both WebSocket (LTP/Ticker) and REST API (Historical/OHLC). 
- **Symbols**: Tracks 9 symbols simultaneously (indices like NIFTY/BANKNIFTY and MCX commodities like CRUDEOIL/NATURALGAS). Symbols are loaded from `.env` and `config.py`.
- **Interval**: Streaming data via WebSocket (tick-by-tick) is aggregated into 1-minute and 5-minute candles for AMT analysis. Polling for scanner occurs every 60 seconds.
- **Normalization**: Data is converted into a standardized `OHLC` value object before entering the domain layer.

## 3. Volume Profile Implementation
The system implements a dual-profile approach: **Session Profile** (full day) and **Leg Profile** (last directional move).

- **Computation**: Computed using price-at-volume bins.
- **Formulas**:
  - **VAH / VAL**: Uses the **CME two-row pairs method**. Starting from POC, it expands into rows sharing higher volume until 70% of total session volume is enclosed.
    ```python
    while current_volume < target_volume:
        up_pair = profile[up_idx+1].vol + profile[up_idx+2].vol
        down_pair = profile[down_idx-1].vol + profile[down_idx-2].vol
        if up_pair >= down_pair: # Expand Up
    ```
  - **POC**: The price bin with the absolute maximum volume. In case of ties, the bin closest to **Session VWAP** is selected as the tie-breaker.
- **Histogram**: Uses 200 bins by default to maintain high granularity for options.
- **LVN (Low Volume Node)**: Detected as bins with `< 15% of the mean bin volume`.
- **HVN (High Volume Node)**: Detected as bins with `> 200% of the mean bin volume`.
- **Leg Profile**: Computed separately for the "Displacement Leg" (consecutive candles in one direction).
- **Update Frequency**: Full profile rebuild happens on every new candle; incremental updates happen on every tick.

## 4. Market Mode Detection
The system uses a **4-state model** determined in `market_state_engine.py`:
- **BALANCED**: Triggered if `balance_ratio > 0.55` (Indian market adjustment) and price is inside VA.
- **IMBALANCED**: Triggered by **Displacement** (range expansion > 1.5x ATR) or **Acceptance** (2+ closes outside VA).
- **PROBING**: Price is outside VA but lacks displacement or high aggression (unconfirmed break).
- **DEAD MARKET**: Volume is below 0.5σ of the 20-period moving average.

## 5. Session and Leg State
- **Session State**: Computed as `NO_TRADE`, `BALANCED`, `IMBALANCED`, or `PROBING` based on price location relative to VA and aggression.
- **Leg State**: Separate from Session. A **NEW LEG** is triggered by a "Displacement" event (large range candle with volume).
- **Leg Profile**: Focuses only on the volume distribution *within* that specific displacement move to find reaction levels (LVNs).

## 6. Indicators Computed
| Indicator | Formula / Logic | Frequency | Output |
|---|---|---|---|
| **Delta Score** | Aggressor Volume (Buy - Sell) / Total Volume | Every Tick | -1.0 to +1.0 |
| **OFI** | Order Flow Imbalance (L2 depth changes) | Every Tick | normalized |
| **CVD Slope** | Linear regression of Cumulative Volume Delta | 1-min | degrees / rate |
| **VWAP** | Σ(Price * Volume) / Σ(Volume) | Every Tick | Absolute Price |
| **VWAP σ** | Standard Deviation bands based on variance | Every Tick | ±1σ, ±2σ |
| **IB Range** | High/Low of first 60 minutes (Initial Balance) | Continuous | Range |
| **Balance %** | % of candles in lookback closing inside VA | 1-min | 0 - 100% |
| **Aggression** | Institutional volume > 2.5σ (Fabio Spec) | Every Tick | Index (0 - 4.5) |

## 7. FABIO Playbook Engine Logic
The `entry_gate.py` enforces the primary rule checklist:
- **AAA PRE-1**: `market_state` must be `IMBALANCED` or `PROBING`.
- **MR Location**: `|LTP - (VAH or VAL)| < 20 ticks`.
- **Volume Alive**: `Aggression Score > 0.5`.
- **Timing**: Checked via `session_context.py` (Morning vs Afternoon volatility).

### P(target) Calculation
`P(target)` starts with a baseline from `AgentPipeline` (ML-informed) and is shifted by the **Delta Score**:
```python
delta_score = aggression - 1.0
if delta_score > 0:
    p_long += (delta_score * 0.15)
```
- **Direction**: `LONG` if `P > 0.60`, `SHORT` if `P < 0.40` (with margins).
- **Triple-A**: (Absorption, Accumulation, Aggression) — Partially implemented via `AbsorptionDetector` and `AggressionScorer`.

## 8. LLM / AI Decision Engine
- **Models**: Supports **Google Gemini 1.5 Pro** (Primary) and **OpenAI GPT-4o** (Fallback).
- **System Prompt**: Focuses on "Reading the Auction" using Fabio Valentini's AMT methodology. (See `GenerativeAIService._DEFAULT_INSTRUCTION`).
- **Context Injection**:
  - Live LTP (injected at the last millisecond to avoid lag).
  - VAH/VAL/POC levels.
  - Session Context (Phase, Gap Type, IB status).
  - Quant Engine P(target).
- **Parsing**: Uses `re.search` for JSON blocks with a **Fix-up Pipeline** to correct unquoted keys or missing trailing braces before `json.loads`.
- **Fallback**: If JSON parsing fails, moves to a **Keyword Regex** matching engine (detecting "Buy on Dip", "Failed Auction", etc.).

## 9. Decision History
- **Data per entry**: Symbol, Direction, Confidence, Rationale, Market State, Price, and VA levels.
- **Persistence**: SQLite table `llm_decisions`.
- **UI Display**: `DecisionHistoryPanel.tsx` renders a timestamped list with collapsible rationale blocks.

## 10. Scanner Panel Logic
- **Selection**: Hardcoded list of 9 key symbols (Indices + Commodities).
- **Row Data**: Mode (BALANCED/IMBALANCED), Action (ENTER NOW/WAIT/DEAD), Direction, P%, LTP, and Chg%.
- **Action Triggers**:
  - `ENTER NOW`: `P > 55%` + `Aggression > 1.0` + `Timing Rules Passed`.
  - `WAIT`: Aggression low or P(target) near 50%.
  - `DEAD`: Volume < threshold.

## 11. Risk / Execution Engine
- **Circuit Breakers**: 
  - Stop trading after **3 consecutive losses**.
  - Block entry if `Current Distance < 1.5 * ATR` from last stop level.
- **Daily Target**: Logic to stop trading if target % is reached (Configurable).
- **Sizing**: Default fixed sizing; "Cushion System" (Pyramiding) increases size by 30% if session PnL is positive.
- **Execution**: Semi-automated. Signal generated results in a "TARGET LOCKED" card on UI for user confirmation or auto-fire (if `AUTO_TRADE=True`).

## 12. Known Bugs / TODOs
- **Residual JSON**: Some symbols occasionally leak raw JSON into the `rationale` field if the repair parser hits an edge case.
- **Hardcoded**: Strike selection intervals for MCX are currently static in `option_scanner.py`.
- **Stubs**: `PyramidManager` is currently a placeholder logic shell.

## 13. Data Structures
### Python (AMTResult)
```python
class AMTResult(BaseModel):
    market_state: str  # BALANCED | IMBALANCED | PROBING
    poc: float
    vah: float
    val: float
    aggression: float
    balance_ratio: float
    has_displacement: bool
```

### TypeScript (Scanner Row)
```typescript
interface MarketData {
  symbol: string;
  mode: 'BALANCED' | 'IMBALANCED' | 'PROBING';
  action: 'ENTER NOW' | 'WAIT' | 'DEAD' | 'MONITORING';
  prob: number;
  direction: 'LONG' | 'SHORT' | 'FLAT';
  ltp: number;
  change: number;
}
```
