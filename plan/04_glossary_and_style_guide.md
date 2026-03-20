# Consolidated Glossary & Style Guide
## GlassyTrade AI — AMT Order Flow Strategy Engine

**Document Version:** 1.0
**Date:** 2026-03-17
**Status:** Draft
**Source Documents:** srs.md, fulldoc.md, startergy.md

---

## 1. Glossary of Terms

### 1.1 Auction Market Theory (AMT) Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| Auction Market Theory | AMT | Trading methodology developed by Fabio Valentini that analyzes market structure through volume distribution at price levels | Core methodology |
| Point of Control | POC | The price level with the highest traded volume in a session or leg — represents fair value center | Profile analysis |
| Value Area High | VAH | The upper boundary of the price range containing 70% of total volume | Profile analysis |
| Value Area Low | VAL | The lower boundary of the price range containing 70% of total volume | Profile analysis |
| Value Area | VA | The price range between VAH and VAL containing 70% of total volume | Profile analysis |
| Low Volume Node | LVN | A price level with volume < 15% of mean volume — represents rejection/weakness | Profile analysis |
| High Volume Node | HVN | A price level with volume > 200% of mean volume — represents acceptance/strength | Profile analysis |
| Volume Profile | VP | Distribution of traded volume across price levels for a given time period | Profile analysis |
| Session Profile | SP | Volume profile built from session open to current tick | Profile analysis |
| Leg Profile | FRVP | Filtered Relative Volume Profile — volume profile for a specific price leg | Profile analysis |
| Combined Profile | CP | Profile showing confluence between leg LVNs and session levels | Profile analysis |

### 1.2 Order Flow Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| Cumulative Volume Delta | CVD | Running sum of (ask_vol - bid_vol) from session open — shows net buying/selling pressure | Order flow |
| CVD Slope | - | Rate of change of CVD over a rolling window (default 20 candles) — indicates momentum | Order flow |
| CVD Divergence | - | Price makes new extreme but CVD doesn't confirm — potential reversal signal | Order flow |
| Footprint | - | Per-candle, per-price-level breakdown of bid vs ask volume | Order flow |
| Footprint Imbalance | - | Cells where ask:bid or bid:ask ratio ≥ 3:1 (300%) — shows aggressive buying/selling | Order flow |
| Volume Bubble | - | Exceptionally large volume at a single price level within a candle (≥ mean + 2σ) | Order flow |
| Absorption | - | Small candle range (< ATR×0.30) with high volume (> avg×2.0) — one side absorbing the other | Order flow |
| Big Trade Cluster | - | 3+ institutional-sized prints (≥ 5× avg trade size) within 2 ticks of a level | Order flow |
| Order Flow Imbalance | OFI | (ask_vol - bid_vol) / total_vol averaged over rolling window — net directional pressure | Order flow |
| Volume Weighted Average Price | VWAP | Average price weighted by volume — institutional benchmark | Order flow |
| Initial Balance | IB | Price range of first 2 candles of session — sets early session context | Order flow |
| L2 DOM | - | Level 2 market depth — bid/ask order book showing pending orders | Order flow |
| Liquidity Wall | - | Large pending orders at a single level (≥ 5× avg depth) | Order flow |
| Iceberg Order | - | Large order that refreshes at same price after partial fills — hidden liquidity | Order flow |

### 1.3 Market State Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| Balanced Market | - | Price trading within VAH-VAL range — rotational, mean-reverting behavior | Market state |
| Imbalanced Market | - | Price outside value area with displacement candle + high volume — trending behavior | Market state |
| Probing | - | Price outside VA but without displacement — unconfirmed break, wait state | Market state |
| No Trade | - | Price within ±2 ticks of POC — dead zone with no edge | Market state |
| Near VAH | - | Price in upper half of value area (between VAH and POC midpoint) | Market state |
| Near VAL | - | Price in lower half of value area (between VAL and POC midpoint) | Market state |
| Near POC | - | Price near POC — no trade zone | Market state |
| Displacement Candle | - | Candle with range > ATR × 1.5 — shows strong directional move | Market state |

### 1.4 Drive Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| First Drive | D1 | Market's initial push to a key level (VAH, VAL, LVN) — trap move, never enter | Drive system |
| Second Drive | D2 | Market returns to same level with less momentum — only valid entry point | Drive system |
| Third Drive | D3+ | Level is exhausted/overtraded — edge gone, avoid | Drive system |
| Drive Rejection | - | Price touches level but closes on opposite side (wick rejection) — confirms level strength | Drive system |
| Drive Tracker | - | Class that tracks touch count and rejection status per key level per session | Drive system |

### 1.5 Aggression Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| Aggression Score | - | Multi-signal composite score (0-4.5) confirming entry validity | Aggression |
| Aggression Signals | - | Individual components contributing to aggression score | Aggression |
| Confirmed | - | Aggression score ≥ 2.0 — minimum threshold for trade signal | Aggression |
| High Confidence | - | Aggression score ≥ 3.0 | Aggression |
| Medium Confidence | - | Aggression score ≥ 2.0 but < 3.0 | Aggression |
| Low Confidence | - | Aggression score < 2.0 — no trade | Aggression |

### 1.6 Trade Management Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| Entry Zone | - | Exact price level (LVN, VAH, VAL) where trade is initiated | Trade setup |
| Stop Loss | SL | Price level where trade is exited if wrong — limits risk | Trade setup |
| Target | - | Price level where profit is taken — typically session POC | Trade setup |
| Risk:Reward | R:R | Ratio of potential reward to risk — minimum 1.5:1 required | Trade setup |
| Cushion | - | Distance between entry and stop loss in ticks — must be ≤ 10 ticks | Trade setup |
| Invalidation | - | Price level beyond which trade structure is void | Trade setup |
| Partition 1 | P1 | First exit (30% of position) — seed recovery at 33% of R | Exit management |
| Partition 2 | P2 | Second exit (50% of position) — mandatory at target | Exit management |
| Partition 3 | P3 | Third exit (20% of position) — trail if momentum strong | Exit management |
| Break-Even | BE | Moving stop loss to entry price — zero risk trade | Exit management |
| Trailing Stop | - | Dynamic stop loss that follows price — locks in profits | Exit management |
| Counter-Aggression | - | Opposite-direction signals appearing during trade — hard exit trigger | Exit management |
| Pyramid | - | Adding to winning position at new LVN — structured scaling in | Position management |
| Seed Recovery | - | Exiting partial position to recover initial risk capital | Exit management |

### 1.7 Risk Management Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| Risk Per Trade | - | Maximum capital risked on single trade — 0.5% of equity | Risk management |
| Daily Loss Limit | - | Maximum loss allowed per session — 2% of session-start equity | Risk management |
| Consecutive Loss Limit | - | Maximum consecutive losing trades before pause — 3 losses | Risk management |
| Drawdown Limit | - | Maximum decline from equity peak — 3% | Risk management |
| Session Kill Switch | - | Hard stop when any risk limit is breached — no new entries | Risk management |
| Position Sizing | - | Calculating lot size based on risk amount and stop distance | Risk management |
| Fixed Fractional | - | Position sizing method: risk_amount / risk_per_lot | Risk management |

### 1.8 Technical Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| Tick | - | Smallest price movement — minimum price increment | Data |
| Tick Size | - | Minimum price increment for an instrument (e.g., 0.10 for NG) | Data |
| Lot Size | - | Contract multiplier — number of units per lot | Data |
| Point Value | - | INR value per price point (lot_size × multiplier) | Data |
| OHLCV | - | Open, High, Low, Close, Volume — standard candle data | Data |
| ATR | - | Average True Range — volatility measure over N periods | Indicators |
| Average Volume | - | Mean volume over rolling N periods (default 20) | Indicators |
| Average Trade Size | - | Mean trade size over rolling N periods | Indicators |
| Bucket | - | Price level in volume profile — rounded to tick_size | Profile |
| Session | - | Trading period from open to close | Time |
| Leg | - | Price movement from VA break to extreme — impulse leg | Time |
| Warm-up Period | - | Initial minutes of session to skip (15-30 min) | Time |
| Dead Zone | - | Low-activity period (12:00-13:30 IST) — reduced confidence | Time |

### 1.9 System Terms

| Term | Abbreviation | Definition | Context |
|---|---|---|---|
| WebSocket | WS | Persistent bidirectional connection for real-time data | Infrastructure |
| REST API | - | Request-response API for polling data | Infrastructure |
| DuckDB | - | Embedded analytical database for persistence | Infrastructure |
| FastAPI | - | Python web framework for API + WebSocket server | Infrastructure |
| Pydantic | - | Python data validation library for schemas | Infrastructure |
| asyncio | - | Python async I/O framework for concurrency | Infrastructure |
| OutputSchema | - | Pydantic model defining complete signal output structure | Output |
| AI Commander | - | Rule-based rationale generator (no LLM) | Output |
| Gate | - | Sequential validation step in signal pipeline | Pipeline |
| Pipeline | - | Complete tick-to-signal processing flow | Pipeline |

---

## 2. Abbreviations Index

| Abbreviation | Full Form |
|---|---|
| AMT | Auction Market Theory |
| API | Application Programming Interface |
| ATR | Average True Range |
| BE | Break-Even |
| BO | Business Objective |
| CVD | Cumulative Volume Delta |
| DOM | Depth of Market |
| EIA | Energy Information Administration |
| FR | Functional Requirement |
| FRVP | Filtered Relative Volume Profile |
| HVN | High Volume Node |
| IB | Initial Balance |
| IST | Indian Standard Time |
| L2 | Level 2 (market depth) |
| LVN | Low Volume Node |
| MCX | Multi Commodity Exchange |
| NFR | Non-Functional Requirement |
| NSE | National Stock Exchange |
| OFI | Order Flow Imbalance |
| OHLCV | Open High Low Close Volume |
| P1/P2/P3 | Partition 1/2/3 |
| POC | Point of Control |
| R:R | Risk to Reward |
| SL | Stop Loss |
| VA | Value Area |
| VAH | Value Area High |
| VAL | Value Area Low |
| VP | Volume Profile |
| VWAP | Volume Weighted Average Price |
| WS | WebSocket |

---

## 3. Style Guide

### 3.1 Document Naming Convention

```
{number}_{descriptive_name}.md

Examples:
01_master_requirements_specification.md
02_architectural_plan.md
03_responsibility_matrix.md
04_glossary_and_style_guide.md
05_traceability_matrix.md
```

### 3.2 Document Header Template

```markdown
# {Document Title}
## GlassyTrade AI — AMT Order Flow Strategy Engine

**Document Version:** {X.Y}
**Date:** {YYYY-MM-DD}
**Status:** Draft | Review | Approved
**Source Documents:** {list of source documents}

---
```

### 3.3 Section Numbering

- Level 1: `## 1. Section Name`
- Level 2: `### 1.1 Subsection Name`
- Level 3: `#### 1.1.1 Sub-subsection Name`

### 3.4 Table Formatting

- Always include header row
- Use consistent column alignment
- Include ID column for traceable items
- Use Priority/Status columns where applicable

### 3.5 Code Block Formatting

- Use language-specific syntax highlighting
- Include docstrings for functions
- Keep examples concise and focused

### 3.6 Requirement ID Format

```
{Category}-{Number}

Examples:
BO-01 (Business Objective)
FR-01-01 (Functional Requirement - Section - Item)
NFR-01 (Non-Functional Requirement)
OI-01 (Open Item)
```

### 3.7 Status Values

| Status | Meaning |
|---|---|
| Draft | Initial creation, not reviewed |
| Review | Under review by stakeholders |
| Approved | Reviewed and accepted |
| Active | Currently in effect |
| Deprecated | No longer applicable |
| Open | Action item not yet resolved |
| Closed | Action item resolved |

### 3.8 Priority Levels

| Priority | Meaning | Action |
|---|---|---|
| Critical | Must have — system cannot function without it | Implement first |
| High | Important — significant value/impact | Implement early |
| Medium | Useful — adds value but not essential | Implement if time permits |
| Low | Nice to have — minimal impact | Implement last or defer |

---

## 4. Naming Conventions

### 4.1 Python Module Names

```
snake_case.py

Examples:
tick_processor.py
candle_builder.py
volume_profile.py
market_state_engine.py
```

### 4.2 Python Class Names

```
PascalCase

Examples:
TickProcessor
CandleBuilder
VolumeProfileEngine
MarketStateEngine
SessionRiskManager
```

### 4.3 Python Function Names

```
snake_case

Examples:
process_tick()
build_candle()
calc_poc()
detect_market_state()
calculate_position_size()
```

### 4.4 Python Variable Names

```
snake_case

Examples:
current_price
session_profile
cvd_series
aggression_score
tick_size
```

### 4.5 Python Constants

```
UPPER_SNAKE_CASE

Examples:
CONFIG
INSTRUMENTS
MIN_AGGRESSION_SCORE
MAX_DAILY_LOSS_PCT
```

### 4.6 Configuration Keys

```
snake_case

Examples:
tick_size
profile_bucket_size
value_area_pct
lvn_threshold
big_trade_multiplier
```

---

## 5. Data Type Conventions

### 5.1 Price Values

- Type: `float`
- Precision: 2 decimal places
- Rounding: Round to tick_size

### 5.2 Volume Values

- Type: `int`
- No decimal places

### 5.3 Timestamps

- Type: `datetime`
- Format: ISO 8601 with timezone
- Timezone: IST (Asia/Kolkata)

### 5.4 Percentages

- Type: `float`
- Range: 0.0 to 1.0 (not 0 to 100)
- Example: 0.005 for 0.5%

### 5.5 Scores

- Type: `float`
- Precision: 2 decimal places
- Example: 2.50, 3.00

---

## 6. Error Message Conventions

### 6.1 Format

```
{COMPONENT}: {error_type} — {description}

Examples:
DhanWSClient: CONNECTION_LOST — WebSocket disconnected, attempting reconnect
SessionRiskManager: DAILY_LIMIT_HIT — 2% daily loss reached, session killed
TradeConstructor: INVALID_CUSHION — Stop loss distance > 10 ticks
```

### 6.2 Error Types

| Error Type | Meaning |
|---|---|
| CONNECTION_LOST | Network/WS connection dropped |
| DATA_STALE | No data received for > 30 seconds |
| LIMIT_HIT | Risk limit exceeded |
| INVALID_SETUP | Trade setup fails validation |
| CONFIG_ERROR | Configuration issue |
| STATE_ERROR | Invalid state transition |

---

## 7. Log Message Conventions

### 7.1 Format

```
[{timestamp}] [{level}] [{component}] {message}

Example:
[2026-03-17T09:45:00+05:30] [INFO] [MarketStateEngine] NATURALGAS: BALANCED → IMBALANCED (UP)
```

### 7.2 Log Levels

| Level | Usage |
|---|---|
| DEBUG | Detailed diagnostic information |
| INFO | General informational messages |
| WARNING | Potential issues, non-critical |
| ERROR | Error conditions, may affect operation |
| CRITICAL | Critical errors, system may stop |

---

## 8. API Response Conventions

### 8.1 Success Response

```json
{
  "status": "success",
  "data": { ... },
  "timestamp": "2026-03-17T09:45:00+05:30"
}
```

### 8.2 Error Response

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_SYMBOL",
    "message": "Symbol XYZ not found in instruments registry"
  },
  "timestamp": "2026-03-17T09:45:00+05:30"
}
```

---

## 9. File Organization

### 9.1 Source Code Structure

```
src/
├── core/           # Core processing modules
├── profile/        # Volume profile modules
├── orderflow/      # Order flow analysis modules
├── strategy/       # Strategy and decision modules
├── risk/           # Risk management modules
├── trade_management/  # Trade management modules
├── data/           # Data ingestion and storage
├── output/         # Output formatting and publishing
├── config/         # Configuration modules
└── main.py         # Entry point
```

### 9.2 Documentation Structure

```
enginev2/
├── plan/           # Planning and reference documents
│   ├── 01_master_requirements_specification.md
│   ├── 02_architectural_plan.md
│   ├── 03_responsibility_matrix.md
│   ├── 04_glossary_and_style_guide.md
│   └── 05_traceability_matrix.md
├── fulldoc.md      # Full technical documentation
├── srs.md          # Software requirements specification
├── startergy.md    # Strategy algorithm documentation
└── technial_design_document.md  # Technical design (TDD)
```

---

**Document Control:**
- Created: 2026-03-17
- Last Modified: 2026-03-17
- Next Review: TBD
- Approved By: TBD
